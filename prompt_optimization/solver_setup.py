"""Solver setup that adapts ROMA configs for prompt optimization."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
from typing import Any, Optional

from roma_dspy import RecursiveSolverModule
from roma_dspy.config import load_config
from roma_dspy.core.engine.solve import RecursiveSolver
from roma_dspy.utils.lm_factory import (
    apply_backend_capability_constraints,
    apply_global_lm_override,
)

from prompt_optimization.benchmarking import BenchmarkBuildRequest, get_family
from prompt_optimization.config import (
    OptimizationConfig,
    normalized_runtime_options,
    patch_romaconfig,
)


def _stage_benchmark_workspace_root() -> Path:
    """Create a writable workspace root for benchmark/optimization runs."""
    return Path(tempfile.mkdtemp(prefix="roma_benchmark_run_")).resolve()


def _build_module_from_patched_config(
    resolved_config: OptimizationConfig,
    patched_config,
) -> RecursiveSolverModule:
    solver = RecursiveSolver(
        config=patched_config,
        max_depth=resolved_config.max_depth,
        enable_logging=resolved_config.enable_logging,
        enable_checkpoints=False,
    )
    return RecursiveSolverModule(solver=solver)


def create_solver_module(
    config: OptimizationConfig,
    *,
    profile: Optional[str] = None,
    mlflow_tracking_uri: Optional[str] = None,
    lm_model: Optional[str] = None,
    lm_backend: Optional[str] = None,
) -> RecursiveSolverModule:
    """Create a generic RecursiveSolverModule configured for optimization."""
    resolved_config = deepcopy(config)
    effective_profile = profile or resolved_config.profile_name
    if effective_profile and not resolved_config.profile_name:
        resolved_config.profile_name = effective_profile

    workspace_root = _stage_benchmark_workspace_root()
    config_overrides = [
        f"storage.base_path={workspace_root.as_posix()}",
        "storage.flat_structure=true",
    ]

    try:
        base_config = load_config(profile=effective_profile, overrides=config_overrides)
        patched_config = patch_romaconfig(resolved_config, base_config, mlflow_tracking_uri)
        apply_global_lm_override(
            patched_config,
            model=lm_model,
            backend=lm_backend,
        )
        apply_backend_capability_constraints(patched_config)
        module = _build_module_from_patched_config(resolved_config, patched_config)
        module._benchmark_workspace_root = workspace_root
        return module
    except Exception:
        shutil.rmtree(workspace_root, ignore_errors=True)
        raise


def create_benchmark_solver_module(
    config: OptimizationConfig,
    *,
    family: Optional[str] = None,
    profile: Optional[str] = None,
    overrides: Optional[list[str]] = None,
    mlflow_tracking_uri: Optional[str] = None,
    lm_model: Optional[str] = None,
    lm_backend: Optional[str] = None,
    runtime_options: Optional[dict[str, Any]] = None,
) -> RecursiveSolverModule:
    """Create a family-aware RecursiveSolverModule."""
    resolved_config = deepcopy(config)
    effective_profile = profile or resolved_config.profile_name
    if effective_profile and not resolved_config.profile_name:
        resolved_config.profile_name = effective_profile

    family_name = family or resolved_config.benchmark_family or resolved_config.dataset_name or (
        effective_profile.split("/", 1)[0] if effective_profile else None
    )
    if not family_name:
        raise ValueError(
            "Could not determine benchmark family. Set config.dataset_name, config.benchmark_family, or pass family=..."
        )

    request = BenchmarkBuildRequest(
        family=family_name,
        profile=effective_profile,
        overrides=tuple(overrides or ()),
        mlflow_tracking_uri=mlflow_tracking_uri,
        lm_model=lm_model,
        lm_backend=lm_backend,
        runtime_options=runtime_options or normalized_runtime_options(resolved_config),
    )
    adapter = get_family(family_name)
    return adapter.create_solver_module(resolved_config, request)


def create_officeqa_solver_module(
    config: OptimizationConfig,
    *,
    profile: Optional[str] = None,
    corpus_dir: Optional[str | Path] = None,
    overrides: Optional[list[str]] = None,
    mlflow_tracking_uri: Optional[str] = None,
    runner=None,
    workspace=None,
    allow_autodiscovery: bool = True,
    disable_filesystem_mcp: bool = True,
    lm_model: Optional[str] = None,
    lm_backend: Optional[str] = None,
) -> RecursiveSolverModule:
    """Backward-compatible wrapper for the OfficeQA family-aware builder."""
    runtime_options = normalized_runtime_options(config)
    if corpus_dir is not None:
        runtime_options["corpus_dir"] = str(corpus_dir)
    runtime_options.update(
        {
            "runner": runner,
            "workspace": workspace,
            "allow_autodiscovery": allow_autodiscovery,
            "disable_filesystem_mcp": disable_filesystem_mcp,
            "enable_checkpoints": False,
        }
    )
    return create_benchmark_solver_module(
        config,
        family="officeqa",
        profile=profile or config.profile_name or "officeqa/default",
        overrides=overrides,
        mlflow_tracking_uri=mlflow_tracking_uri,
        lm_model=lm_model,
        lm_backend=lm_backend,
        runtime_options=runtime_options,
    )
