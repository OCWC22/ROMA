"""Tests for benchmark-family registry and dispatch."""

from prompt_optimization.benchmarking import available_families, get_family, resolve_family_name
from prompt_optimization.config import OptimizationConfig


def test_available_families_exposes_builtin_adapters():
    families = available_families()
    assert "officeqa" in families
    assert "aimo" in families
    assert "frames" in families
    assert "simpleqa" in families
    assert "simpleqa_verified" in families
    assert "seal0" in families


def test_resolve_family_name_uses_dataset_name_before_profile():
    assert resolve_family_name(dataset_name="aimo", profile_name="officeqa/default") == "aimo"


def test_resolve_family_name_can_infer_from_profile_prefix():
    assert resolve_family_name(profile_name="officeqa/default") == "officeqa"


def test_get_family_returns_cached_adapter_instance():
    first = get_family("officeqa")
    second = get_family("officeqa")
    assert first is second
    assert first.family_name == "officeqa"


def test_standard_family_uses_generic_bundle_policy():
    family = get_family("aimo")
    config = OptimizationConfig(dataset_name="aimo", prompt_source_policy="generic_bundle")

    overrides = family.resolve_prompt_overrides(config)

    assert overrides["atomizer"] is not None
    assert overrides["planner"] is not None
