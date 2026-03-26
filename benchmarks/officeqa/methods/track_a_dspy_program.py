"""Track A OfficeQA DSPy program benchmark adapter."""

from .base import OfficeQAModuleBenchmarkSolver


class TrackADSPyProgramSolver(OfficeQAModuleBenchmarkSolver):
    name = "track_a_dspy_program"
    default_profile = "officeqa/default"
