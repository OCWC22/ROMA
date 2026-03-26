"""Tests for OfficeQA-specific prompt-optimization policy."""

from types import SimpleNamespace

import pytest

from prompt_optimization.config import (
    OptimizationConfig,
    normalized_artifact_override,
    normalized_dataset_options,
    normalized_runtime_options,
    patch_romaconfig,
)
from prompt_optimization.dataset_loaders import load_officeqa_datasets
from prompt_optimization.metrics import OfficeQAMetric
from prompt_optimization.optimize_anything_adapter import (
    OptimizeAnythingResult,
    optimize_text_artifact,
)
from prompt_optimization.solver_setup import create_benchmark_solver_module, create_solver_module
from roma_dspy.config import load_config
from roma_dspy.officeqa import OfficeQAQuestion
from roma_dspy.types import AgentType, LMBackend


@pytest.fixture
def sample_questions():
    return [
        OfficeQAQuestion(
            uid=f"q{i}",
            question=f"Question {i}",
            answer=str(i),
            source_docs="",
            source_files=f"file_{i}.txt",
            difficulty="hard",
            question_type="lookup",
        )
        for i in range(6)
    ]


def test_patch_romaconfig_preserves_officeqa_prompt_sources_by_default():
    base_config = load_config(profile="officeqa/default")
    opt_config = OptimizationConfig(profile_name="officeqa/default")

    patched = patch_romaconfig(opt_config, base_config)

    assert patched.agents.atomizer.signature_instructions == base_config.agents.atomizer.signature_instructions
    assert patched.agents.planner.signature_instructions == base_config.agents.planner.signature_instructions
    assert patched.agents.executor.signature_instructions == base_config.agents.executor.signature_instructions
    assert patched.agents.aggregator.signature_instructions == base_config.agents.aggregator.signature_instructions
    assert patched.agents.verifier.signature_instructions == base_config.agents.verifier.signature_instructions


def test_patch_romaconfig_can_force_full_officeqa_bundle():
    base_config = load_config(profile="officeqa/default")
    opt_config = OptimizationConfig(
        profile_name="officeqa/default",
        prompt_source_policy="officeqa_bundle",
    )

    patched = patch_romaconfig(opt_config, base_config)

    assert patched.agents.atomizer.signature_instructions.endswith("atomizer_officeqa.jinja")
    assert patched.agents.planner.signature_instructions.endswith("planner_officeqa.jinja")
    assert patched.agents.executor.signature_instructions.endswith("executor_officeqa.jinja")
    assert patched.agents.aggregator.signature_instructions.endswith("aggregator_officeqa.jinja")
    assert patched.agents.verifier.signature_instructions.endswith("verifier_officeqa.jinja")


def test_patch_romaconfig_normalizes_generic_and_legacy_officeqa_options():
    opt_config = OptimizationConfig(
        dataset_name="officeqa",
        dataset_options={"subset": "full"},
        runtime_options={"corpus_dir": "/tmp/corpus"},
        artifact_component="planner",
        artifact_path="/tmp/generic_planner.jinja",
        officeqa_subset="pro",
        officeqa_corpus_dir="/tmp/legacy_corpus",
        officeqa_artifact_component="aggregator",
        officeqa_artifact_path="/tmp/legacy_aggregator.jinja",
    )

    assert normalized_dataset_options(opt_config)["subset"] == "full"
    assert normalized_runtime_options(opt_config)["corpus_dir"] == "/tmp/corpus"
    assert normalized_artifact_override(opt_config) == (
        "planner",
        "/tmp/generic_planner.jinja",
    )


def test_patch_romaconfig_can_override_single_officeqa_artifact():
    base_config = load_config(profile="officeqa/default")
    opt_config = OptimizationConfig(
        profile_name="officeqa/default",
        officeqa_artifact_component="planner",
        officeqa_artifact_path="/tmp/custom_planner.jinja",
    )

    patched = patch_romaconfig(opt_config, base_config)

    assert patched.agents.planner.signature_instructions == "/tmp/custom_planner.jinja"
    assert patched.agents.atomizer.signature_instructions == base_config.agents.atomizer.signature_instructions


def test_patch_romaconfig_can_preserve_profile_lms():
    base_config = load_config(profile="officeqa/default")
    opt_config = OptimizationConfig(
        profile_name="officeqa/default",
        preserve_profile_lms=True,
    )

    patched = patch_romaconfig(opt_config, base_config)

    assert patched.agents.atomizer.llm.model == base_config.agents.atomizer.llm.model
    assert patched.agents.executor.llm.model == base_config.agents.executor.llm.model
    assert patched.agents.verifier.llm.model == base_config.agents.verifier.llm.model


def test_patch_romaconfig_applies_backend_when_overriding_lms():
    base_config = load_config(profile="officeqa/default")
    opt_config = OptimizationConfig(
        profile_name="officeqa/default",
        preserve_profile_lms=False,
    )
    opt_config.executor_lm.model = "claude-sonnet-4-5"
    opt_config.executor_lm.backend = LMBackend.CLAUDE
    opt_config.verifier_lm.model = "claude-sonnet-4-5"
    opt_config.verifier_lm.backend = LMBackend.CLAUDE

    patched = patch_romaconfig(opt_config, base_config)

    assert patched.agents.executor.llm.model == "claude-sonnet-4-5"
    assert patched.agents.executor.llm.backend == LMBackend.CLAUDE
    assert patched.agents.verifier.llm.model == "claude-sonnet-4-5"
    assert patched.agents.verifier.llm.backend == LMBackend.CLAUDE


def test_create_benchmark_solver_module_honors_officeqa_family_dispatch(tmp_path):
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


def test_create_benchmark_solver_module_builds_hybrid_executor_profile(tmp_path):
    transformed = tmp_path / "transformed"
    transformed.mkdir()
    (transformed / "treasury_bulletin_1965_01.txt").write_text("PUBLIC DEBT: 317274")

    config = OptimizationConfig(
        dataset_name="officeqa",
        profile_name="officeqa/hybrid",
        enable_logging=False,
    )
    module = create_benchmark_solver_module(
        config,
        family="officeqa",
        runtime_options={"corpus_dir": str(transformed), "allow_autodiscovery": False},
    )

    executor = module._solver.registry.get_agent(AgentType.EXECUTOR)
    assert executor.__class__.__name__ == "OfficeQARLMExecutor"
    assert module._solver.config.runtime.max_depth == 5
    assert module._solver.config.runtime.max_concurrency == 1


def test_create_solver_module_honors_profile_name_without_explicit_profile_arg():
    config = OptimizationConfig(profile_name="officeqa/default")
    module = create_solver_module(config)

    instructions = module._solver.config.agents.atomizer.signature_instructions
    assert instructions.startswith("prompt_optimization.prompts.seed_prompts.officeqa.") or "Classify" in instructions


def test_load_officeqa_datasets_is_deterministic(sample_questions, monkeypatch):
    monkeypatch.setattr(
        "prompt_optimization.dataset_loaders.load_officeqa_benchmark",
        lambda subset="pro", data_dir=None: list(sample_questions),
    )

    train_a, val_a, test_a = load_officeqa_datasets(train_size=2, val_size=2, test_size=2, seed=7)
    train_b, val_b, test_b = load_officeqa_datasets(train_size=2, val_size=2, test_size=2, seed=7)

    assert [example["uid"] for example in train_a] == [example["uid"] for example in train_b]
    assert [example["uid"] for example in val_a] == [example["uid"] for example in val_b]
    assert [example["uid"] for example in test_a] == [example["uid"] for example in test_b]


def test_officeqa_metric_uses_canonical_answer_extraction():
    metric = OfficeQAMetric()
    example = {"answer": "42"}
    prediction = SimpleNamespace(result_text="synthesized_answer: 42")

    assert metric(example=example, prediction=prediction) == 1.0


def test_optimize_anything_adapter_falls_back_to_gepa(monkeypatch):
    monkeypatch.setattr(
        "prompt_optimization.optimize_anything_adapter._load_backend",
        lambda: (None, None),
    )
    monkeypatch.setattr(
        "prompt_optimization.optimize_anything_adapter._run_gepa_fallback",
        lambda **kwargs: OptimizeAnythingResult(
            best_candidate_text="best",
            best_score=0.75,
            metadata={"backend_mode": "gepa_text_fallback"},
        ),
    )

    result = optimize_text_artifact(
        seed_text="seed",
        rollout=lambda candidate, example: {"score": 1.0},
        objective="test",
        trainset=[{"uid": "q1"}],
    )

    assert result.best_candidate_text == "best"
    assert result.metadata["backend_mode"] == "gepa_text_fallback"
