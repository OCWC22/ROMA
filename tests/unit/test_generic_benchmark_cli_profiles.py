"""Tests for generic benchmark profiles under CLI-backed execution."""

from prompt_optimization.config import (
    OptimizationConfig,
    apply_optimization_lm_override,
    patch_romaconfig,
)
from prompt_optimization.solver_setup import create_benchmark_solver_module
from roma_dspy.config import ConfigManager, load_config
from roma_dspy.types import LMBackend
from roma_dspy.utils.lm_factory import apply_backend_capability_constraints


def test_generic_cli_overrides_propagate_into_agent_mapping_profiles():
    base_config = load_config(profile="test")
    opt_config = OptimizationConfig(profile_name="test")
    apply_optimization_lm_override(
        opt_config,
        model="sonnet",
        backend=LMBackend.CLAUDE,
    )

    patched = patch_romaconfig(opt_config, base_config)

    assert patched.agents.executor.llm.backend == LMBackend.CLAUDE
    assert patched.agent_mapping.executors["RETRIEVE"].llm.backend == LMBackend.CLAUDE
    assert patched.agent_mapping.executors["THINK"].llm.backend == LMBackend.CLAUDE
    assert patched.agent_mapping.executors["WRITE"].llm.backend == LMBackend.CLAUDE


def test_cli_capability_constraints_disable_api_only_web_search_toolkits():
    base_config = load_config(profile="test")
    opt_config = OptimizationConfig(profile_name="test")
    apply_optimization_lm_override(
        opt_config,
        model="sonnet",
        backend=LMBackend.CLAUDE,
    )

    patched = patch_romaconfig(opt_config, base_config)
    apply_backend_capability_constraints(patched)

    assert patched.agents.planner.toolkits[0].enabled is False
    assert patched.agents.executor.toolkits[0].enabled is False
    assert patched.agent_mapping.executors["RETRIEVE"].toolkits[0].enabled is False
    assert patched.agent_mapping.executors["THINK"].toolkits[0].enabled is False


def test_create_benchmark_solver_module_supports_generic_cli_profile_build():
    config = OptimizationConfig(
        dataset_name="simpleqa",
        profile_name="test",
        enable_logging=False,
    )
    apply_optimization_lm_override(
        config,
        model="sonnet",
        backend=LMBackend.CLAUDE,
    )

    module = create_benchmark_solver_module(config, family="simpleqa", profile="test")

    assert module._solver.config.agents.planner.llm.backend == LMBackend.CLAUDE
    assert module._solver.config.agent_mapping.executors["RETRIEVE"].llm.backend == LMBackend.CLAUDE
    assert module._solver.config.agents.planner.toolkits[0].enabled is False
    assert module._solver.config.agent_mapping.executors["RETRIEVE"].toolkits[0].enabled is False


def test_all_shipped_romaconfig_profiles_load_cleanly():
    manager = ConfigManager()
    profiles = manager.get_available_profiles()

    assert "officeqa/arena/arena" not in profiles

    for profile in profiles:
        load_config(profile=profile)


def test_tb2_default_profile_exposes_a_default_e2b_template():
    config = load_config(profile="tb2/default")

    e2b_toolkit = next(
        toolkit
        for toolkit in config.agents.executor.toolkits
        if toolkit.class_name == "E2BToolkit"
    )
    assert e2b_toolkit.toolkit_config["template"] == "roma-dspy-sandbox-dev"
