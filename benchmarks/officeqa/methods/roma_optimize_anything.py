"""ROMA OfficeQA text-artifact optimization benchmark adapter."""

from .base import OfficeQAOptimizableModuleBenchmarkSolver


class ROMAOptimizeAnythingSolver(OfficeQAOptimizableModuleBenchmarkSolver):
    name = "roma_optimize_anything"
    default_profile = "officeqa/default"
    optimization_mode = "optimize_anything"
    artifact_component = "planner"
