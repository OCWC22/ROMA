"""Contracts for benchmark-family adapters used by prompt optimization."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
import shutil
from typing import Any, Optional


@dataclass(frozen=True)
class BenchmarkDatasetSplit:
    """Deterministic train/val/test split for a benchmark family."""

    train: list[Any]
    val: list[Any]
    test: list[Any]


@dataclass(frozen=True)
class BenchmarkBuildRequest:
    """Runtime/module build request shared across benchmark families."""

    family: str
    profile: Optional[str] = None
    overrides: tuple[str, ...] = ()
    mlflow_tracking_uri: Optional[str] = None
    lm_model: Optional[str] = None
    lm_backend: Optional[str] = None
    runtime_options: dict[str, Any] = field(default_factory=dict)


class BenchmarkFamilyAdapter(ABC):
    """Family-specific dataset, metric, and runtime/module adapter."""

    family_name: str = ""
    default_profile: Optional[str] = None

    @abstractmethod
    def load_examples(self, opt_config: Any, *, no_split: bool = False):
        """Load examples for optimization/evaluation."""

    @abstractmethod
    def create_scoring_metric(self, opt_config: Any):
        """Create the family-native scalar scoring metric."""

    def to_example(self, record: Any):
        """Convert a benchmark record into a DSPy example."""
        return record

    def resolve_prompt_overrides(self, opt_config: Any) -> dict[str, Optional[str]]:
        """Resolve family-aware prompt overrides for patch_romaconfig()."""
        return {}

    def create_runtime_runner(self, build_request: BenchmarkBuildRequest):
        """Create a family-native runtime runner if the family supports one."""
        raise NotImplementedError(
            f"Benchmark family '{self.family_name}' does not provide a native runtime runner"
        )

    def create_solver_module(self, config: Any, build_request: BenchmarkBuildRequest):
        """Create a family-aware RecursiveSolverModule."""
        from prompt_optimization.solver_setup import create_solver_module

        return create_solver_module(
            config,
            profile=build_request.profile,
            mlflow_tracking_uri=build_request.mlflow_tracking_uri,
            lm_model=build_request.lm_model,
            lm_backend=build_request.lm_backend,
        )

    def cleanup_module(self, module: Any) -> None:
        """Best-effort module cleanup hook for staged resources."""
        workspace_root = getattr(module, "_benchmark_workspace_root", None)
        if workspace_root is not None:
            shutil.rmtree(workspace_root, ignore_errors=True)

    def get_text_artifact_seed(
        self,
        opt_config: Any,
        *,
        component: Optional[str] = None,
    ) -> Path:
        """Resolve a family-native seed artifact path for text optimization."""
        raise NotImplementedError(
            f"Benchmark family '{self.family_name}' does not expose a text artifact seed"
        )
