"""Hybrid RLM-in-ROMA OfficeQA runtime benchmark adapter."""

from .base import OfficeQARuntimeBenchmarkSolver


class RLMRuntimeSolver(OfficeQARuntimeBenchmarkSolver):
    name = "rlm_runtime"
    default_profile = "officeqa/hybrid"
