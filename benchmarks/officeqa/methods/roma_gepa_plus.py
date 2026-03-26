"""ROMA OfficeQA GEPA benchmark adapter."""

from .base import OfficeQAOptimizableModuleBenchmarkSolver


class ROMAGEPAPlusSolver(OfficeQAOptimizableModuleBenchmarkSolver):
    name = "roma_gepa_plus"
    default_profile = "officeqa/default"
    optimization_mode = "gepa"
