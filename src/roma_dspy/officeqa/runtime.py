"""Helpers for running the native ROMA OfficeQA profile against a real corpus."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from roma_dspy.config import load_config
from roma_dspy.core.engine.solve import RecursiveSolver
from roma_dspy.types import LMBackend
from roma_dspy.utils.lm_factory import (
    apply_global_lm_override,
    config_uses_cli_backend,
    disable_toolkits_by_class_name,
    normalize_lm_backend,
)

from .dataset import resolve_officeqa_transformed_dir
from .scoring import extract_officeqa_answer


@dataclass(frozen=True)
class OfficeQACorpusLayout:
    """Filesystem layout expected by the OfficeQA runtime prompts."""

    root: Path
    transformed_dir: Path
    parsed_dir: Optional[Path] = None
    raw_dir: Optional[Path] = None
    pdfs_dir: Optional[Path] = None
    staged: bool = False


@dataclass
class OfficeQARuntimeResult:
    """Structured result from a native ROMA OfficeQA execution."""

    completed_task: Any
    raw_output: str
    final_answer: str
    trace: dict


def _safe_symlink_or_copy(source: Path, target: Path) -> None:
    if target.exists():
        return
    try:
        target.symlink_to(source, target_is_directory=True)
    except OSError:
        shutil.copytree(source, target)


def _unique_existing_paths(*paths: Optional[Path | str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path:
            continue
        resolved = Path(path).expanduser().resolve()
        if not resolved.exists():
            continue
        normalized = resolved.as_posix()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def resolve_officeqa_corpus_layout(
    corpus_dir: Optional[Path | str] = None,
) -> OfficeQACorpusLayout:
    """Resolve the source OfficeQA corpus layout from a root or transformed dir."""
    requested = Path(corpus_dir).expanduser().resolve() if corpus_dir else None

    if requested and requested.exists() and (requested / "transformed").is_dir():
        return OfficeQACorpusLayout(
            root=requested,
            transformed_dir=(requested / "transformed").resolve(),
            parsed_dir=(requested / "parsed").resolve() if (requested / "parsed").exists() else None,
            raw_dir=(requested / "raw").resolve() if (requested / "raw").exists() else None,
            pdfs_dir=(requested / "pdfs").resolve() if (requested / "pdfs").exists() else None,
            staged=False,
        )

    transformed_dir = resolve_officeqa_transformed_dir(requested or corpus_dir)
    if not transformed_dir:
        raise FileNotFoundError(
            "Could not find an OfficeQA corpus. Provide --corpus-dir pointing to a "
            "directory containing transformed/*.txt files or a corpus root with a "
            "transformed/ subdirectory."
        )

    if transformed_dir.name == "transformed":
        root = transformed_dir.parent.resolve()
        return OfficeQACorpusLayout(
            root=root,
            transformed_dir=transformed_dir.resolve(),
            parsed_dir=(root / "parsed").resolve() if (root / "parsed").exists() else None,
            raw_dir=(root / "raw").resolve() if (root / "raw").exists() else None,
            pdfs_dir=(root / "pdfs").resolve() if (root / "pdfs").exists() else None,
            staged=False,
        )

    return OfficeQACorpusLayout(
        root=transformed_dir.resolve(),
        transformed_dir=transformed_dir.resolve(),
        staged=False,
    )


def _stringify_task_result(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, indent=2, default=str)
        except TypeError:
            return str(value)
    return str(value)


def _extract_native_final_answer(raw_output: str) -> str:
    return extract_officeqa_answer(raw_output)


def officeqa_config_uses_cli_backend(config) -> bool:
    """Whether any core OfficeQA agent has been configured to use a CLI backend."""
    return config_uses_cli_backend(config)


def disable_officeqa_api_only_toolkits(config) -> None:
    """Disable toolkits that still depend on API-native LM features."""
    disable_toolkits_by_class_name(config, {"WebSearchToolkit"}, roles=("planner", "executor"))


def apply_officeqa_lm_overrides(
    config,
    *,
    lm_model: Optional[str] = None,
    lm_backend: Optional[LMBackend | str] = None,
):
    """Apply a single LM override across OfficeQA agents and disable API-only toolkits when needed."""
    apply_global_lm_override(config, model=lm_model, backend=lm_backend)
    if officeqa_config_uses_cli_backend(config):
        disable_officeqa_api_only_toolkits(config)
    return config


class OfficeQARuntimeRunner:
    """Thin runner that executes the real ROMA OfficeQA profile."""

    def __init__(
        self,
        *,
        profile: str = "officeqa/default",
        corpus_dir: Optional[Path | str] = None,
        overrides: Optional[list[str]] = None,
        allow_autodiscovery: bool = True,
        disable_filesystem_mcp: bool = True,
        enable_checkpoints: bool = False,
        lm_model: Optional[str] = None,
        lm_backend: Optional[LMBackend | str] = None,
    ) -> None:
        self.profile = profile
        self.allow_autodiscovery = allow_autodiscovery
        self.disable_filesystem_mcp = disable_filesystem_mcp
        self.enable_checkpoints = enable_checkpoints
        self.lm_model = lm_model
        self.lm_backend = (
            normalize_lm_backend(lm_backend) if lm_backend is not None else None
        )
        self.extra_overrides = list(overrides or [])
        if corpus_dir is None and not self.allow_autodiscovery:
            raise FileNotFoundError(
                "OfficeQA corpus autodiscovery is disabled for this run. "
                "Provide --corpus-dir or use a corpus-enabled benchmark mode."
            )
        self.corpus_layout = resolve_officeqa_corpus_layout(corpus_dir)

    def create_execution_workspace(self) -> OfficeQACorpusLayout:
        """Create an isolated per-run workspace that still exposes transformed/ etc."""
        workspace_root = Path(tempfile.mkdtemp(prefix="roma_officeqa_run_")).resolve()
        transformed_dir = workspace_root / "transformed"
        _safe_symlink_or_copy(self.corpus_layout.transformed_dir, transformed_dir)

        parsed_dir = None
        raw_dir = None
        pdfs_dir = None
        if self.corpus_layout.parsed_dir and self.corpus_layout.parsed_dir.exists():
            parsed_dir = workspace_root / "parsed"
            _safe_symlink_or_copy(self.corpus_layout.parsed_dir, parsed_dir)
        if self.corpus_layout.raw_dir and self.corpus_layout.raw_dir.exists():
            raw_dir = workspace_root / "raw"
            _safe_symlink_or_copy(self.corpus_layout.raw_dir, raw_dir)
        if self.corpus_layout.pdfs_dir and self.corpus_layout.pdfs_dir.exists():
            pdfs_dir = workspace_root / "pdfs"
            _safe_symlink_or_copy(self.corpus_layout.pdfs_dir, pdfs_dir)

        return OfficeQACorpusLayout(
            root=workspace_root,
            transformed_dir=transformed_dir,
            parsed_dir=parsed_dir,
            raw_dir=raw_dir,
            pdfs_dir=pdfs_dir,
            staged=True,
        )

    def cleanup_workspace(self, workspace: Optional[OfficeQACorpusLayout]) -> None:
        """Best-effort cleanup for staged workspaces created by this runner."""
        if not workspace or not workspace.staged:
            return
        shutil.rmtree(workspace.root, ignore_errors=True)

    def build_config_overrides(self, workspace_root: Path) -> list[str]:
        overrides = [
            f"storage.base_path={workspace_root.as_posix()}",
            "storage.flat_structure=true",
        ]
        overrides.extend(self.extra_overrides)
        return overrides

    def _source_corpus_roots(self) -> list[str]:
        """Absolute source corpus roots that staged workspaces may expose via symlinks."""
        return _unique_existing_paths(
            self.corpus_layout.transformed_dir,
            self.corpus_layout.parsed_dir,
            self.corpus_layout.raw_dir,
            self.corpus_layout.pdfs_dir,
        )

    def _configure_executor_toolkits(
        self,
        config,
        workspace: OfficeQACorpusLayout,
    ) -> None:
        executor_toolkits = getattr(config.agents.executor, "toolkits", []) or []
        source_roots = self._source_corpus_roots()

        for toolkit in executor_toolkits:
            toolkit_config = toolkit.toolkit_config or {}

            if toolkit.class_name == "FileToolkit":
                existing_roots = toolkit_config.get("additional_allowed_roots") or []
                toolkit_config["additional_allowed_roots"] = _unique_existing_paths(
                    *existing_roots,
                    *source_roots,
                )
                toolkit.toolkit_config = toolkit_config
                continue

            if toolkit.class_name != "MCPToolkit":
                continue
            if toolkit_config.get("server_name") != "filesystem":
                continue

            if self.disable_filesystem_mcp:
                toolkit.enabled = False
                continue

            args = list(toolkit_config.get("args") or [])
            prefix = args[:2]
            retained_paths = args[3:] if len(args) > 3 else []
            toolkit_config["args"] = prefix + _unique_existing_paths(
                workspace.root,
                *source_roots,
                *retained_paths,
            )
            toolkit.toolkit_config = toolkit_config

    def create_workspace_config(
        self,
        workspace: Optional[OfficeQACorpusLayout] = None,
    ):
        """Create an isolated OfficeQA workspace and load the profile into it."""
        workspace = workspace or self.create_execution_workspace()
        config = load_config(
            profile=self.profile,
            overrides=self.build_config_overrides(workspace.root),
        )
        apply_officeqa_lm_overrides(
            config,
            lm_model=self.lm_model,
            lm_backend=self.lm_backend,
        )
        self._configure_executor_toolkits(config, workspace)
        return config, workspace

    def create_solver(self) -> tuple[RecursiveSolver, OfficeQACorpusLayout]:
        config, workspace = self.create_workspace_config()
        solver = RecursiveSolver(
            config=config,
            enable_logging=config.runtime.enable_logging,
            enable_checkpoints=self.enable_checkpoints,
        )
        return solver, workspace

    def solve(self, question: str) -> OfficeQARuntimeResult:
        solver, workspace = self.create_solver()
        try:
            completed_task = solver.event_solve(question)
            raw_output = _stringify_task_result(getattr(completed_task, "result", None))
            final_answer = extract_officeqa_answer(raw_output)

            trace = {
                "profile": self.profile,
                "source_corpus_root": str(self.corpus_layout.root),
                "workspace_root": str(workspace.root),
                "corpus_staged": workspace.staged,
                "status": getattr(getattr(completed_task, "status", None), "value", None),
                "node_type": getattr(getattr(completed_task, "node_type", None), "value", None),
                "modules_executed": list(getattr(completed_task, "execution_history", {}).keys()),
                "input_tokens": solver.get_total_input_tokens(),
                "output_tokens": solver.get_total_output_tokens(),
                "execution_summary": completed_task.get_execution_summary() if hasattr(completed_task, "get_execution_summary") else {},
            }

            return OfficeQARuntimeResult(
                completed_task=completed_task,
                raw_output=raw_output,
                final_answer=final_answer,
                trace=trace,
            )
        finally:
            self.cleanup_workspace(workspace)
