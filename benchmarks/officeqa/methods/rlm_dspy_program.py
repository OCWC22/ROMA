"""Hybrid RLM-backed OfficeQA DSPy program benchmark adapter."""

from .base import OfficeQAModuleBenchmarkSolver


class RLMDSPyProgramSolver(OfficeQAModuleBenchmarkSolver):
    name = "rlm_dspy_program"
    default_profile = "officeqa/hybrid"
