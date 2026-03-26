"""Shared OfficeQA benchmark primitives and runtime-backed solver adapters."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional, Tuple

from prompt_optimization.config import (
    OptimizationConfig,
    apply_optimization_lm_override,
    get_default_config,
)
from prompt_optimization.experiment_cli.pipeline import create_feedback_metric
from prompt_optimization.optimizer import create_optimizer
from prompt_optimization.optimize_anything_adapter import optimize_text_artifact
from prompt_optimization.solver_setup import create_benchmark_solver_module
from prompt_optimization.benchmarking.families.officeqa import OfficeQABenchmarkFamily
from roma_dspy.officeqa import (
    DEFAULT_DATA_DIR,
    OFFICEQA_FULL_URL,
    OFFICEQA_PRO_URL,
    OfficeQAQuestion,
    OfficeQARuntimeRunner,
    extract_final_answer,
    extract_officeqa_answer,
    load_officeqa_benchmark,
    load_source_documents,
    score_answer,
)
from roma_dspy.utils.lm_factory import backend_from_cli_name, create_gepa_reflection_lm


BENCHMARKS_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BENCHMARKS_ROOT.parent.parent
DATA_DIR = DEFAULT_DATA_DIR

OptimizationStatus = Literal[
    "not_required",
    "pending",
    "not_requested",
    "failed",
    "completed",
    "timed_out",
    "interrupted",
    "running",
]


@dataclass
class OptimizationOutcome:
    method: str
    required: bool
    optimization_mode: str
    status: str
    artifact_dir: Optional[str]

    def to_dict(self):
        return asdict(self)


class OptimizationTimeoutError(Exception):
    pass


@dataclass
class SolverResult:
    """Standard result from any solver. Every method returns this."""

    method: str
    predicted: str
    expected: str
    score: float = 0.0
    duration: float = 0.0
    used_context: bool = False
    raw_output: str = ""
    final_answer: str = ""
    trace: dict = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class BaseSolver(ABC):
    """Every benchmark method implements this contract."""

    name: str = "base"
    context_policy: str = "raw_context"
    default_profile: str = "officeqa/default"

    @abstractmethod
    def solve(self, question: OfficeQAQuestion, context: str = "") -> SolverResult:
        ...

    def close(self) -> None:  # pragma: no cover - default no-op lifecycle hook
        return None


class OptimizableSolver(BaseSolver, ABC):
    """Marker/base class for benchmark methods that support optimization."""

    @abstractmethod
    def optimize(
        self,
        trainset: list[OfficeQAQuestion],
        valset: list[OfficeQAQuestion],
        *,
        optimize_budget: int,
        artifact_dir: Path,
    ) -> None:
        ...


@dataclass
class CLIResult:
    success: bool
    output: str
    error: str = ""
    duration: float = 0.0


class LLMClient:
    """Small benchmark-only LLM client used by legacy prompt baselines."""

    def __init__(self, model: str = "claude-haiku-4-5", cli: str = "claude", timeout: int = 120):
        self.model = model
        self.cli = cli
        self.timeout = timeout
        self._api_client = None

        try:
            subprocess.run([self.cli, "--version"], capture_output=True, timeout=5)
            self._cli_available = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._cli_available = False

        if not self._cli_available:
            try:
                import anthropic

                self._api_client = anthropic.Anthropic()
            except Exception:
                pass

    def call(self, prompt: str, system: str = "", model: str = None) -> CLIResult:
        model = model or self.model
        start = time.time()

        if self._cli_available:
            return self._call_cli(prompt, system, model, start)
        if self._api_client:
            return self._call_api(prompt, system, model, start)
        return CLIResult(
            success=False,
            output="",
            error=f"Neither {self.cli} CLI nor Anthropic API available",
            duration=time.time() - start,
        )

    def _call_cli(self, prompt: str, system: str, model: str, start: float) -> CLIResult:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        if self.cli == "codex":
            cmd = ["codex", "--model", model, "--quiet", full_prompt]
        else:
            cmd = ["claude", "--print", "--model", model, full_prompt]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
            return CLIResult(
                success=result.returncode == 0,
                output=result.stdout.strip(),
                error=result.stderr if result.returncode != 0 else "",
                duration=time.time() - start,
            )
        except subprocess.TimeoutExpired:
            return CLIResult(success=False, output="", error="TIMEOUT", duration=self.timeout)
        except Exception as exc:  # noqa: BLE001
            return CLIResult(success=False, output="", error=str(exc), duration=time.time() - start)

    def _call_api(self, prompt: str, system: str, model: str, start: float) -> CLIResult:
        try:
            messages = [{"role": "user", "content": prompt}]
            kwargs = {"model": model, "max_tokens": 512, "messages": messages}
            if system:
                kwargs["system"] = system
            resp = self._api_client.messages.create(**kwargs)
            return CLIResult(
                success=True,
                output=resp.content[0].text.strip(),
                duration=time.time() - start,
            )
        except Exception as exc:  # noqa: BLE001
            return CLIResult(success=False, output="", error=str(exc), duration=time.time() - start)


def resolve_litellm_model(model: str) -> str:
    """Ensure model string has provider prefix for litellm."""
    return model if "/" in model else f"anthropic/{model}"


def atomic_write_json(path: Path, payload: dict | list) -> None:
    """Write JSON atomically to avoid partial benchmark snapshots."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, default=str)
        handle.write("\n")
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def build_error_solver_result(
    *,
    method: str,
    question: OfficeQAQuestion,
    duration: float,
    error_message: str,
    error_type: str,
    used_context: bool,
    trace: Optional[dict] = None,
    raw_output: str = "",
    error_stage: Optional[str] = None,
) -> SolverResult:
    """Build a canonical failed solver result for benchmark persistence and analysis."""
    trace_payload = dict(trace or {})
    trace_payload.setdefault("error_type", error_type)
    if error_stage:
        trace_payload.setdefault("error_stage", error_stage)
    if getattr(question, "uid", None):
        trace_payload.setdefault("question_uid", question.uid)
    if getattr(question, "question_type", None):
        trace_payload.setdefault("question_type", question.question_type)

    return SolverResult(
        method=method,
        predicted="",
        expected=question.answer,
        score=0.0,
        duration=duration,
        used_context=used_context,
        raw_output=raw_output or f"ERROR: {error_message}",
        final_answer="",
        trace=trace_payload,
        error=error_message,
    )


def make_splits(
    questions: list[OfficeQAQuestion],
    train_size: int = 20,
    val_size: int = 10,
    seed: int = 42,
) -> Tuple[list[OfficeQAQuestion], list[OfficeQAQuestion], list[OfficeQAQuestion]]:
    import random

    rng = random.Random(seed)
    shuffled = list(questions)
    rng.shuffle(shuffled)

    train = shuffled[:train_size]
    val = shuffled[train_size : train_size + val_size]
    test = shuffled[train_size + val_size :]
    return train, val, test


def save_splits(train, val, test, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, qs in [("train_uids.json", train), ("val_uids.json", val), ("test_uids.json", test)]:
        with open(output_dir / name, "w", encoding="utf-8") as handle:
            json.dump([q.uid for q in qs], handle, indent=2)


class OfficeQARuntimeBenchmarkSolver(BaseSolver):
    """Thin benchmark adapter over OfficeQARuntimeRunner."""

    context_policy = "tool_search"
    default_profile = "officeqa/default"

    def __init__(
        self,
        *,
        model: str = "claude-haiku-4-5",
        cli: str = "api",
        profile: Optional[str] = None,
        corpus_dir: Optional[Path] = None,
        overrides: Optional[list[str]] = None,
        allow_autodiscovery: bool = True,
    ) -> None:
        self.model = model
        self.cli = cli
        self.profile = profile or self.default_profile
        self.corpus_dir = corpus_dir
        self.native_overrides = list(overrides or [])
        self.allow_autodiscovery = allow_autodiscovery
        self._runner = OfficeQARuntimeRunner(
            profile=self.profile,
            corpus_dir=corpus_dir,
            overrides=self.native_overrides,
            allow_autodiscovery=allow_autodiscovery,
            lm_model=model,
            lm_backend=self._lm_backend_override(),
        )

    def _lm_backend_override(self):
        if not self.cli or self.cli == "api":
            return None
        return backend_from_cli_name(self.cli)

    def solve(self, question: OfficeQAQuestion, context: str = "") -> SolverResult:
        started = time.time()
        try:
            runtime_result = self._runner.solve(question.question)
            trace = {
                **dict(runtime_result.trace),
                "runtime_mode": "officeqa_native",
                "context_policy": self.context_policy,
                "raw_context_ignored": bool(context),
                "profile": self.profile,
            }
            return SolverResult(
                method=self.name,
                predicted=runtime_result.final_answer,
                expected=question.answer,
                score=score_answer(question.answer, runtime_result.final_answer),
                duration=time.time() - started,
                used_context=False,
                raw_output=runtime_result.raw_output,
                final_answer=runtime_result.final_answer,
                trace=trace,
                error=None,
            )
        except Exception as exc:  # noqa: BLE001
            return build_error_solver_result(
                method=self.name,
                question=question,
                duration=time.time() - started,
                error_message=str(exc),
                error_type="solver_error",
                used_context=False,
                trace={
                    "runtime_mode": "officeqa_native",
                    "context_policy": self.context_policy,
                    "profile": self.profile,
                },
                raw_output=f"ERROR: {exc}",
            )


class OfficeQAModuleBenchmarkSolver(BaseSolver):
    """Benchmark adapter over the canonical OfficeQA prompt-optimization/runtime path."""

    context_policy = "tool_search"
    default_profile = "officeqa/default"

    def __init__(
        self,
        *,
        model: str = "claude-haiku-4-5",
        cli: str = "api",
        profile: Optional[str] = None,
        corpus_dir: Optional[Path] = None,
        overrides: Optional[list[str]] = None,
        allow_autodiscovery: bool = True,
        optimization_config: Optional[OptimizationConfig] = None,
    ) -> None:
        self.model = model
        self.cli = cli
        self.profile = profile or self.default_profile
        self.corpus_dir = corpus_dir
        self.native_overrides = list(overrides or [])
        self.allow_autodiscovery = allow_autodiscovery
        self.optimization_config = deepcopy(optimization_config) if optimization_config is not None else get_default_config()
        self._family = OfficeQABenchmarkFamily()
        self._module = None
        self._optimization_metadata: dict[str, Any] = {}

    def _lm_backend_override(self):
        if not self.cli or self.cli == "api":
            return None
        return backend_from_cli_name(self.cli)

    def _runtime_options(self) -> dict[str, Any]:
        options = {
            "allow_autodiscovery": self.allow_autodiscovery,
            "disable_filesystem_mcp": True,
            "enable_checkpoints": False,
        }
        if self.corpus_dir is not None:
            options["corpus_dir"] = str(self.corpus_dir)
        return options

    def _base_optimization_config(self) -> OptimizationConfig:
        config = deepcopy(self.optimization_config)
        config.dataset_name = config.dataset_name or "officeqa"
        config.benchmark_family = "officeqa"
        config.profile_name = self.profile
        if self.profile == "officeqa/default" and config.max_depth == 1:
            config.max_depth = 2
        elif self.profile == "officeqa/hybrid" and config.max_depth == 1:
            config.max_depth = 5
        if self.corpus_dir is not None:
            config.officeqa_corpus_dir = str(self.corpus_dir)
        apply_optimization_lm_override(
            config,
            model=self.model,
            backend=self._lm_backend_override(),
        )
        return config

    def _build_module(self, config: Optional[OptimizationConfig] = None):
        build_config = config or self._base_optimization_config()
        return create_benchmark_solver_module(
            build_config,
            family="officeqa",
            profile=self.profile,
            overrides=self.native_overrides,
            lm_model=self.model,
            lm_backend=self._lm_backend_override(),
            runtime_options=self._runtime_options(),
        )

    def _set_active_module(self, module) -> None:
        if self._module is not None and self._module is not module:
            self._family.cleanup_module(self._module)
        self._module = module

    def _rebuild_optimized_module(self):
        metadata = dict(self._optimization_metadata or {})

        program_path = metadata.get("program_path")
        if program_path:
            resolved_program_path = Path(program_path)
            if resolved_program_path.exists():
                module = self._build_module()
                load = getattr(module, "load", None)
                if callable(load):
                    load(str(resolved_program_path))
                    return module
                self._family.cleanup_module(module)

        artifact_path = metadata.get("artifact_path")
        if artifact_path:
            resolved_artifact_path = Path(artifact_path)
            if resolved_artifact_path.exists():
                config = self._base_optimization_config()
                component = metadata.get("artifact_component") or getattr(
                    self, "artifact_component", None
                )
                if component:
                    config.artifact_component = component
                    config.officeqa_artifact_component = component
                config.artifact_path = str(resolved_artifact_path)
                config.officeqa_artifact_path = str(resolved_artifact_path)
                return self._build_module(config)

        return self._build_module()

    def _ensure_module(self):
        if self._module is None:
            self._module = self._rebuild_optimized_module()
        return self._module

    def __getstate__(self):
        state = self.__dict__.copy()
        state["_module"] = None
        state["_family"] = None
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._module = None
        self._family = OfficeQABenchmarkFamily()
        self._optimization_metadata = dict(self.__dict__.get("_optimization_metadata") or {})

    def _prediction_trace(self, prediction: Any, *, ignored_context: bool) -> dict[str, Any]:
        trace = {
            "runtime_mode": "officeqa_module",
            "context_policy": self.context_policy,
            "raw_context_ignored": ignored_context,
            "profile": self.profile,
            "output_trace": getattr(prediction, "output_trace", ""),
        }
        completed_task = getattr(prediction, "completed_task", None)
        if completed_task is not None and hasattr(completed_task, "get_execution_summary"):
            trace["execution_summary"] = completed_task.get_execution_summary()
        workspace = getattr(self._module, "_officeqa_workspace", None)
        if workspace is not None:
            trace["workspace_root"] = str(workspace.root)
        return trace

    def solve(self, question: OfficeQAQuestion, context: str = "") -> SolverResult:
        started = time.time()
        ignored_context = bool(context)
        try:
            module = self._ensure_module()
            prediction = module(goal=question.question)
            raw_output = str(getattr(prediction, "result_text", "") or "")
            final_answer = extract_officeqa_answer(raw_output)
            return SolverResult(
                method=self.name,
                predicted=final_answer,
                expected=question.answer,
                score=score_answer(question.answer, final_answer),
                duration=time.time() - started,
                used_context=False,
                raw_output=raw_output,
                final_answer=final_answer,
                trace=self._prediction_trace(prediction, ignored_context=ignored_context),
                error=None,
            )
        except Exception as exc:  # noqa: BLE001
            return build_error_solver_result(
                method=self.name,
                question=question,
                duration=time.time() - started,
                error_message=str(exc),
                error_type="solver_error",
                used_context=False,
                trace={
                    "runtime_mode": "officeqa_module",
                    "context_policy": self.context_policy,
                    "raw_context_ignored": ignored_context,
                    "profile": self.profile,
                },
                raw_output=f"ERROR: {exc}",
            )

    def close(self) -> None:
        if self._module is not None:
            self._family.cleanup_module(self._module)
            self._module = None


class OfficeQAOptimizableModuleBenchmarkSolver(OfficeQAModuleBenchmarkSolver, OptimizableSolver):
    """Shared optimization-capable benchmark adapter."""

    optimization_mode = "gepa"
    artifact_component = "planner"

    def optimize(
        self,
        trainset: list[OfficeQAQuestion],
        valset: list[OfficeQAQuestion],
        *,
        optimize_budget: int,
        artifact_dir: Path,
    ) -> None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        if self.optimization_mode == "gepa":
            self._optimize_with_gepa(trainset, valset, optimize_budget=optimize_budget, artifact_dir=artifact_dir)
            return
        if self.optimization_mode == "optimize_anything":
            self._optimize_text_artifact(trainset, valset, optimize_budget=optimize_budget, artifact_dir=artifact_dir)
            return
        raise ValueError(f"Unsupported optimization mode: {self.optimization_mode}")

    def _optimize_with_gepa(
        self,
        trainset: list[OfficeQAQuestion],
        valset: list[OfficeQAQuestion],
        *,
        optimize_budget: int,
        artifact_dir: Path,
    ) -> None:
        config = self._base_optimization_config()
        config.max_metric_calls = optimize_budget
        train_examples = [self._family.to_example(record) for record in trainset]
        val_examples = [self._family.to_example(record) for record in valset]
        candidate_module = self._build_module(config)
        _, feedback_metric = create_feedback_metric(config, self._family)
        optimizer = create_optimizer(config, feedback_metric, run_name=self.name)
        optimized_module = optimizer.compile(candidate_module, trainset=train_examples, valset=val_examples)

        program_path = artifact_dir / "optimized_program.json"
        save = getattr(optimized_module, "save", None)
        if callable(save):
            save(str(program_path))
        if candidate_module is not optimized_module:
            self._family.cleanup_module(candidate_module)
        self._set_active_module(optimized_module)
        self._optimization_metadata = {
            "optimization_mode": "gepa",
            "profile": self.profile,
            "artifact_dir": str(artifact_dir.resolve()),
            "program_path": str(program_path.resolve()) if program_path.exists() else None,
            "train_size": len(train_examples),
            "val_size": len(val_examples),
            "max_metric_calls": optimize_budget,
        }
        atomic_write_json(artifact_dir / "optimization_metadata.json", self._optimization_metadata)

    def _optimize_text_artifact(
        self,
        trainset: list[OfficeQAQuestion],
        valset: list[OfficeQAQuestion],
        *,
        optimize_budget: int,
        artifact_dir: Path,
    ) -> None:
        config = self._base_optimization_config()
        config.max_metric_calls = optimize_budget
        component = self.artifact_component
        train_examples = [self._family.to_example(record) for record in trainset]
        val_examples = [self._family.to_example(record) for record in valset]
        seed_path = self._family.get_text_artifact_seed(config, component=component)
        seed_text = Path(seed_path).read_text(encoding="utf-8")
        reflection_model = create_gepa_reflection_lm(config.reflection_lm)

        def rollout(candidate_text: str, example: Any) -> dict[str, Any]:
            module = None
            with tempfile.NamedTemporaryFile("w", suffix=".jinja", encoding="utf-8", delete=False) as handle:
                handle.write(candidate_text)
                candidate_path = Path(handle.name)
            try:
                candidate_config = deepcopy(config)
                candidate_config.artifact_component = component
                candidate_config.artifact_path = str(candidate_path)
                candidate_config.officeqa_artifact_component = component
                candidate_config.officeqa_artifact_path = str(candidate_path)
                module = self._build_module(candidate_config)
                prediction = module(goal=example["goal"])
                raw_output = str(getattr(prediction, "result_text", "") or "")
                final_answer = extract_officeqa_answer(raw_output)
                return {
                    "uid": example.get("uid"),
                    "question": example["goal"],
                    "predicted": final_answer,
                    "expected": example["answer"],
                    "raw_output": raw_output,
                    "score": score_answer(example["answer"], final_answer),
                }
            finally:
                if module is not None:
                    self._family.cleanup_module(module)
                candidate_path.unlink(missing_ok=True)

        result = optimize_text_artifact(
            seed_text=seed_text,
            rollout=rollout,
            objective=f"Improve the {component} artifact for OfficeQA hybrid execution.",
            budget=optimize_budget,
            reflection_model=reflection_model,
            trainset=train_examples,
            valset=val_examples,
            component_name=component,
        )

        artifact_path = artifact_dir / f"{component}_optimized.jinja"
        artifact_path.write_text(result.best_candidate_text, encoding="utf-8")

        optimized_config = deepcopy(config)
        optimized_config.artifact_component = component
        optimized_config.artifact_path = str(artifact_path)
        optimized_config.officeqa_artifact_component = component
        optimized_config.officeqa_artifact_path = str(artifact_path)
        optimized_module = self._build_module(optimized_config)
        self._set_active_module(optimized_module)
        self._optimization_metadata = {
            "optimization_mode": "optimize_anything",
            "profile": self.profile,
            "artifact_dir": str(artifact_dir.resolve()),
            "artifact_component": component,
            "artifact_path": str(artifact_path.resolve()),
            "best_score": result.best_score,
            "metadata": result.metadata,
        }
        atomic_write_json(artifact_dir / "optimization_metadata.json", self._optimization_metadata)


OFFICEQA_SEED_PROMPT = """You are an expert analyst of U.S. Treasury Bulletins (1939-2025).
Answer with ONLY the value. No explanation. No refusal.

RULES:
1. If a table header says "in millions of dollars", report the base number as-is (e.g., 2,602 not 2,602,000,000).
2. Fiscal year conventions:
   - Before FY1977: Jul 1 of prior year to Jun 30 (e.g., FY1975 = Jul 1974 - Jun 1975)
   - FY1977 onward: Oct 1 of prior year to Sep 30 (e.g., FY2020 = Oct 2019 - Sep 2020)
   - Transition Quarter (TQ/1976): Jul 1 - Sep 30, 1976
3. Extract exact values from tables. Only calculate if explicitly asked.
4. For sums: add all individual values. For geometric mean: GM = (y1*y2*...*yn)^(1/n).
5. Match the format of the original table.
6. ALWAYS provide your best answer as a single value."""
