"""Prompt optimization utilities for ROMA-DSPy."""

from .config import OptimizationConfig, get_default_config, LMConfig, patch_romaconfig, load_config_from_yaml, save_config_to_yaml
from .solver_setup import create_benchmark_solver_module, create_officeqa_solver_module, create_solver_module
from .judge import ComponentJudge, JudgeSignature
from .metrics import MetricWithFeedback, NumberMetric, OfficeQAMetric, SearchMetric
from .component_selectors import (
    SELECTORS,
    planner_only_selector,
    atomizer_only_selector,
    executor_only_selector,
    aggregator_only_selector,
    round_robin_selector,
)
from .optimizer import create_optimizer
from .benchmarking import available_families, get_family, resolve_family_name


# Lazy import for dataset_loaders (requires 'datasets' library which is optional)
def __getattr__(name):
    """Lazy import for dataset loader functions that require the 'datasets' library."""
    _dataset_functions = {
        "load_aimo_datasets",
        "load_frames_dataset",
        "load_officeqa_datasets",
        "load_seal0_dataset",
        "load_simpleqa_verified_dataset",
    }
    if name in _dataset_functions:
        from . import dataset_loaders
        return getattr(dataset_loaders, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Config
    "OptimizationConfig",
    "get_default_config",
    "LMConfig",
    "patch_romaconfig",
    "load_config_from_yaml",
    "save_config_to_yaml",
    # Dataset (lazy imported - require 'datasets' library)
    "load_aimo_datasets",
    "load_frames_dataset",
    "load_officeqa_datasets",
    "load_seal0_dataset",
    "load_simpleqa_verified_dataset",
    # Solver
    "create_benchmark_solver_module",
    "create_officeqa_solver_module",
    "create_solver_module",
    # Judge
    "ComponentJudge",
    "JudgeSignature",
    # Metrics
    "MetricWithFeedback",
    "SearchMetric",
    "NumberMetric",
    "OfficeQAMetric",
    # Selectors
    "SELECTORS",
    "planner_only_selector",
    "atomizer_only_selector",
    "executor_only_selector",
    "aggregator_only_selector",
    "round_robin_selector",
    # Optimizer
    "create_optimizer",
    # Benchmarking
    "available_families",
    "get_family",
    "resolve_family_name",
]
