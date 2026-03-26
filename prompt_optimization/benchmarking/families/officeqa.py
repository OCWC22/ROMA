"""OfficeQA benchmark-family adapter."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import random
from typing import Optional

import dspy

from prompt_optimization.metrics import OfficeQAMetric
from prompt_optimization.prompts import AGGREGATOR_PROMPT, ATOMIZER_PROMPT, PLANNER_PROMPT
from roma_dspy import RecursiveSolverModule
from roma_dspy.core.engine.solve import RecursiveSolver
from roma_dspy.officeqa import OfficeQAQuestion, load_officeqa_benchmark
from roma_dspy.officeqa.runtime import OfficeQARuntimeRunner, apply_officeqa_lm_overrides

from ..contracts import BenchmarkBuildRequest, BenchmarkFamilyAdapter

OFFICEQA_COMPONENTS = ("atomizer", "planner", "executor", "aggregator", "verifier")
GENERIC_PROMPT_BUNDLE = {
    "atomizer": ATOMIZER_PROMPT,
    "planner": PLANNER_PROMPT,
    "executor": None,
    "aggregator": AGGREGATOR_PROMPT,
    "verifier": None,
}
OFFICEQA_PROMPT_BUNDLE = {
    "atomizer": "config/examples/prompts/officeqa/atomizer_officeqa.jinja",
    "planner": "config/examples/prompts/officeqa/planner_officeqa.jinja",
    "executor": "config/examples/prompts/officeqa/executor_officeqa.jinja",
    "aggregator": "config/examples/prompts/officeqa/aggregator_officeqa.jinja",
    "verifier": "config/examples/prompts/officeqa/verifier_officeqa.jinja",
}


class OfficeQABenchmarkFamily(BenchmarkFamilyAdapter):
    family_name = "officeqa"
    default_profile = "officeqa/default"

    def to_example(self, record: OfficeQAQuestion):
        return dspy.Example(
            {
                "uid": record.uid,
                "goal": record.question,
                "answer": record.answer,
                "source_files": record.source_files,
                "question_type": record.question_type,
            }
        ).with_inputs("goal")

    def load_examples(self, opt_config, *, no_split: bool = False):
        from prompt_optimization.config import normalized_dataset_options

        options = normalized_dataset_options(opt_config)
        questions = load_officeqa_benchmark(
            subset=options.get("subset", "pro"),
            data_dir=options.get("data_dir"),
        )
        shuffled = list(questions)
        random.Random(opt_config.dataset_seed).shuffle(shuffled)
        examples = [self.to_example(question) for question in shuffled]

        if no_split:
            return examples

        train_end = opt_config.train_size
        val_end = train_end + opt_config.val_size
        test_end = val_end + opt_config.test_size
        return (
            examples[:train_end],
            examples[train_end:val_end],
            examples[val_end:test_end],
        )

    def create_scoring_metric(self, opt_config):
        return OfficeQAMetric()

    def resolve_prompt_overrides(self, opt_config):
        from prompt_optimization.config import normalized_artifact_override

        overrides = {component: None for component in OFFICEQA_COMPONENTS}
        policy = opt_config.prompt_source_policy
        if policy == "preserve_profile":
            pass
        elif policy == "generic_bundle":
            overrides.update(GENERIC_PROMPT_BUNDLE)
        elif policy == "officeqa_bundle":
            overrides.update(OFFICEQA_PROMPT_BUNDLE)
        else:
            raise ValueError(
                f"Unknown prompt_source_policy '{policy}'. Expected one of: preserve_profile, generic_bundle, officeqa_bundle."
            )

        component, artifact_path = normalized_artifact_override(opt_config)
        if artifact_path:
            if component not in overrides:
                raise ValueError(
                    f"Unknown artifact_component '{component}'. Expected one of: {', '.join(OFFICEQA_COMPONENTS)}."
                )
            overrides[component] = artifact_path
        return overrides

    def create_runtime_runner(self, build_request: BenchmarkBuildRequest):
        runtime_options = dict(build_request.runtime_options or {})
        return OfficeQARuntimeRunner(
            profile=build_request.profile or self.default_profile,
            corpus_dir=runtime_options.get("corpus_dir"),
            overrides=list(build_request.overrides),
            allow_autodiscovery=runtime_options.get("allow_autodiscovery", True),
            disable_filesystem_mcp=runtime_options.get("disable_filesystem_mcp", True),
            enable_checkpoints=runtime_options.get("enable_checkpoints", False),
            lm_model=build_request.lm_model,
            lm_backend=build_request.lm_backend,
        )

    def create_solver_module(self, config, build_request: BenchmarkBuildRequest):
        from prompt_optimization.config import patch_romaconfig

        resolved_config = deepcopy(config)
        effective_profile = build_request.profile or resolved_config.profile_name or self.default_profile
        resolved_config.profile_name = effective_profile
        if effective_profile == "officeqa/default" and resolved_config.max_depth == 1:
            resolved_config.max_depth = 2
        elif effective_profile == "officeqa/hybrid" and resolved_config.max_depth == 1:
            resolved_config.max_depth = 5

        runtime_options = dict(build_request.runtime_options or {})
        active_runner = runtime_options.get("runner") or self.create_runtime_runner(build_request)
        workspace = runtime_options.get("workspace")

        base_config, active_workspace = active_runner.create_workspace_config(workspace=workspace)
        patched_config = patch_romaconfig(
            resolved_config,
            base_config,
            build_request.mlflow_tracking_uri,
        )
        apply_officeqa_lm_overrides(
            patched_config,
            lm_model=build_request.lm_model,
            lm_backend=build_request.lm_backend,
        )

        solver = RecursiveSolver(
            config=patched_config,
            max_depth=resolved_config.max_depth,
            enable_logging=resolved_config.enable_logging,
            enable_checkpoints=False,
        )
        module = RecursiveSolverModule(solver=solver)
        module._officeqa_runner = active_runner
        module._officeqa_workspace = active_workspace
        return module

    def cleanup_module(self, module) -> None:
        if module is None:
            return
        runner = getattr(module, "_officeqa_runner", None)
        workspace = getattr(module, "_officeqa_workspace", None)
        cleanup = getattr(runner, "cleanup_workspace", None)
        if callable(cleanup) and workspace is not None:
            cleanup(workspace)

    def get_text_artifact_seed(self, opt_config, *, component: Optional[str] = None) -> Path:
        from prompt_optimization.config import normalized_artifact_override

        override_component, override_path = normalized_artifact_override(opt_config)
        target_component = component or override_component or "planner"
        if target_component not in OFFICEQA_PROMPT_BUNDLE:
            raise ValueError(
                f"Unknown OfficeQA artifact component '{target_component}'. Expected one of: {', '.join(OFFICEQA_COMPONENTS)}."
            )
        if override_path and (override_component in (None, target_component)):
            return Path(override_path).expanduser().resolve()
        return Path(OFFICEQA_PROMPT_BUNDLE[target_component]).expanduser().resolve()
