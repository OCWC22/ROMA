"""Track A OfficeQA text-artifact optimization benchmark adapter."""

from .base import OfficeQAOptimizableModuleBenchmarkSolver


class TrackAOptimizeAnythingPlannerTextSolver(OfficeQAOptimizableModuleBenchmarkSolver):
    name = "track_a_optimize_anything_planner_text"
    default_profile = "officeqa/default"
    optimization_mode = "optimize_anything"
    artifact_component = "planner"
