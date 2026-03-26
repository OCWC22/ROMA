"""Hybrid RLM-backed OfficeQA GEPA benchmark adapter."""

from .base import OfficeQAOptimizableModuleBenchmarkSolver


class RLMDSPyGEPASolver(OfficeQAOptimizableModuleBenchmarkSolver):
    name = "rlm_dspy_gepa"
    default_profile = "officeqa/hybrid"
    optimization_mode = "gepa"
