"""Integration test: Config -> Registry -> Solver."""

import pytest
from pathlib import Path

from prompt_optimization.config import OptimizationConfig
from prompt_optimization.solver_setup import create_benchmark_solver_module, create_officeqa_solver_module
from roma_dspy.config.manager import ConfigManager
from roma_dspy.core.engine.solve import RecursiveSolver
from roma_dspy.core.registry import AgentRegistry
from roma_dspy.types import AgentType, LMBackend, TaskType


class TestConfigToSolver:
    """Test complete integration from YAML config to working solver."""

    def test_load_example_config_and_create_solver(self):
        """Load example agent_mapping config and create solver."""
        config_path = Path("config/examples/agent_mapping_example.yaml")

        if not config_path.exists():
            pytest.skip("Example config not found")

        # Load config
        manager = ConfigManager()
        config = manager.load_config(str(config_path))

        # Create solver from config
        solver = RecursiveSolver(config=config)

        # Verify solver has registry
        assert solver.registry is not None
        assert isinstance(solver.registry, AgentRegistry)

        # Verify registry stats
        stats = solver.registry.get_stats()
        assert stats["total_agents"] > 0
        assert stats["task_specific"] > 0
        assert stats["defaults"] > 0

    def test_load_simple_mapping_and_create_solver(self):
        """Load simple mapping config and create solver."""
        config_path = Path("config/profiles/simple_mapping.yaml")

        if not config_path.exists():
            pytest.skip("Simple mapping config not found")

        # Load config
        manager = ConfigManager()
        config = manager.load_config(str(config_path))

        # Create solver
        solver = RecursiveSolver(config=config)

        # Verify registry has task-specific executors
        assert solver.registry.has_agent(AgentType.EXECUTOR, TaskType.RETRIEVE)
        assert solver.registry.has_agent(AgentType.EXECUTOR, TaskType.CODE_INTERPRET)

        # Verify defaults exist
        assert solver.registry.has_agent(AgentType.ATOMIZER, None)
        assert solver.registry.has_agent(AgentType.PLANNER, None)

    def test_registry_task_aware_lookup(self):
        """Verify registry performs task-aware agent selection."""
        config_path = Path("config/examples/agent_mapping_example.yaml")

        if not config_path.exists():
            pytest.skip("Example config not found")

        manager = ConfigManager()
        config = manager.load_config(str(config_path))
        solver = RecursiveSolver(config=config)

        # Get task-specific executor
        retrieve_executor = solver.registry.get_agent(
            AgentType.EXECUTOR, TaskType.RETRIEVE
        )

        # Get different task-specific executor
        write_executor = solver.registry.get_agent(AgentType.EXECUTOR, TaskType.WRITE)

        # They should be different instances
        assert retrieve_executor is not write_executor

        # Get agent for unmapped task type (should fallback to default)
        default_executor = solver.registry.get_agent(
            AgentType.EXECUTOR,
            None,  # No task type
        )

        assert default_executor is not None

    def test_solver_with_config_max_depth(self):
        """Verify solver respects max_depth from config."""
        config_path = Path("config/profiles/simple_mapping.yaml")

        if not config_path.exists():
            pytest.skip("Simple mapping config not found")

        manager = ConfigManager()
        config = manager.load_config(str(config_path))

        # Create solver (should use max_depth from config)
        solver = RecursiveSolver(config=config)

        # Simple mapping has max_depth: 3
        assert solver.max_depth == 3

    def test_solver_max_depth_override(self):
        """Verify solver allows max_depth override."""
        config_path = Path("config/profiles/simple_mapping.yaml")

        if not config_path.exists():
            pytest.skip("Simple mapping config not found")

        manager = ConfigManager()
        config = manager.load_config(str(config_path))

        # Override max_depth
        solver = RecursiveSolver(config=config, max_depth=10)

        # Should use override value
        assert solver.max_depth == 10

    def test_create_officeqa_solver_module_stages_workspace(self, tmp_path):
        """Verify the OfficeQA-aware solver builder stages a workspace-backed solver."""
        transformed = tmp_path / "transformed"
        transformed.mkdir()
        (transformed / "treasury_bulletin_1965_01.txt").write_text("PUBLIC DEBT: 317274")

        config = OptimizationConfig(
            profile_name="officeqa/default",
            enable_logging=False,
        )
        module = create_officeqa_solver_module(
            config,
            corpus_dir=transformed,
        )

        workspace = module._officeqa_workspace
        assert workspace.root != transformed.resolve()
        assert workspace.transformed_dir.exists()
        assert module._solver.config.storage.base_path == str(workspace.root)

    def test_create_benchmark_solver_module_supports_officeqa_family(self, tmp_path):
        transformed = tmp_path / "transformed"
        transformed.mkdir()
        (transformed / "treasury_bulletin_1965_01.txt").write_text("PUBLIC DEBT: 317274")

        config = OptimizationConfig(
            dataset_name="officeqa",
            profile_name="officeqa/default",
            enable_logging=False,
        )
        module = create_benchmark_solver_module(
            config,
            family="officeqa",
            runtime_options={"corpus_dir": str(transformed), "allow_autodiscovery": False},
        )

        assert module._officeqa_workspace.transformed_dir.exists()
        assert module._solver.config.storage.base_path == str(module._officeqa_workspace.root)

    def test_create_officeqa_solver_module_applies_cli_overrides(self, tmp_path):
        transformed = tmp_path / "transformed"
        transformed.mkdir()
        (transformed / "treasury_bulletin_1965_01.txt").write_text("PUBLIC DEBT: 317274")

        config = OptimizationConfig(
            profile_name="officeqa/default",
            enable_logging=False,
        )
        module = create_officeqa_solver_module(
            config,
            corpus_dir=transformed,
            lm_model="claude-sonnet-4-5",
            lm_backend="claude",
        )

        assert module._solver.config.agents.executor.llm.backend == LMBackend.CLAUDE
        assert module._solver.config.agents.aggregator.llm.model == "claude-sonnet-4-5"
