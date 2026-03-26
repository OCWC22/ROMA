"""Track A OfficeQA GEPA benchmark adapter."""

from .base import OfficeQAOptimizableModuleBenchmarkSolver


class TrackADSPyGEPASolver(OfficeQAOptimizableModuleBenchmarkSolver):
    name = "track_a_dspy_gepa"
    default_profile = "officeqa/default"
    optimization_mode = "gepa"
