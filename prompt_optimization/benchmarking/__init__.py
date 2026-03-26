"""Benchmark-family registry and contracts for prompt optimization."""

from .contracts import BenchmarkBuildRequest, BenchmarkDatasetSplit, BenchmarkFamilyAdapter
from .registry import available_families, get_family, register_family, resolve_family_name

__all__ = [
    "BenchmarkBuildRequest",
    "BenchmarkDatasetSplit",
    "BenchmarkFamilyAdapter",
    "available_families",
    "get_family",
    "register_family",
    "resolve_family_name",
]
