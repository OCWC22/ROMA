"""Hybrid RLM-backed OfficeQA text-artifact optimization benchmark adapter."""

from .base import OfficeQAOptimizableModuleBenchmarkSolver


class RLMOptimizeAnythingPlannerTextSolver(OfficeQAOptimizableModuleBenchmarkSolver):
    name = "rlm_optimize_anything_planner_text"
    default_profile = "officeqa/hybrid"
    optimization_mode = "optimize_anything"
    artifact_component = "planner"
