"""Native ROMA OfficeQA runtime benchmark adapter."""

from .base import OfficeQARuntimeBenchmarkSolver


class ROMARuntimeSolver(OfficeQARuntimeBenchmarkSolver):
    name = "roma_runtime"
    default_profile = "officeqa/default"
