"""Lazy registry for benchmark-family adapters."""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from .contracts import BenchmarkFamilyAdapter

_FAMILY_LOADERS: dict[str, Callable[[], BenchmarkFamilyAdapter]] = {}
_FAMILY_CACHE: dict[str, BenchmarkFamilyAdapter] = {}
_BOOTSTRAPPED = False


def _normalize_name(name: Optional[str]) -> Optional[str]:
    if name is None:
        return None
    normalized = name.strip().lower().replace("-", "_")
    return normalized or None


def register_family(name: str, loader: Callable[[], BenchmarkFamilyAdapter]) -> None:
    normalized = _normalize_name(name)
    if normalized is None:
        raise ValueError("Benchmark family name cannot be empty")
    _FAMILY_LOADERS[normalized] = loader


def _bootstrap_default_families() -> None:
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    _BOOTSTRAPPED = True

    register_family(
        "officeqa",
        lambda: __import__(
            "prompt_optimization.benchmarking.families.officeqa",
            fromlist=["OfficeQABenchmarkFamily"],
        ).OfficeQABenchmarkFamily(),
    )

    for family_name in ("aimo", "frames", "simpleqa", "simpleqa_verified", "seal0"):
        register_family(
            family_name,
            lambda family_name=family_name: __import__(
                "prompt_optimization.benchmarking.families.standard",
                fromlist=["get_standard_family"],
            ).get_standard_family(family_name),
        )


def available_families() -> list[str]:
    _bootstrap_default_families()
    return sorted(_FAMILY_LOADERS.keys())


def get_family(name: str) -> BenchmarkFamilyAdapter:
    _bootstrap_default_families()
    normalized = _normalize_name(name)
    if normalized is None:
        raise ValueError("Benchmark family name cannot be empty")
    cached = _FAMILY_CACHE.get(normalized)
    if cached is not None:
        return cached
    loader = _FAMILY_LOADERS.get(normalized)
    if loader is None:
        raise ValueError(
            f"Unknown benchmark family '{name}'. Available: {', '.join(available_families())}"
        )
    family = loader()
    _FAMILY_CACHE[normalized] = family
    return family


def resolve_family_name(
    *,
    dataset_name: Optional[str] = None,
    profile_name: Optional[str] = None,
    explicit: Optional[str] = None,
) -> str:
    _bootstrap_default_families()

    for candidate in (explicit, dataset_name):
        normalized = _normalize_name(candidate)
        if normalized and normalized in _FAMILY_LOADERS:
            return normalized

    if profile_name:
        normalized = _normalize_name(profile_name.split("/", 1)[0])
        if normalized and normalized in _FAMILY_LOADERS:
            return normalized

    requested = explicit or dataset_name or profile_name or "<unset>"
    raise ValueError(
        f"Could not resolve benchmark family from '{requested}'. "
        f"Available families: {', '.join(available_families())}"
    )
