"""Standard dataset-family adapters for non-OfficeQA optimization tasks."""

from __future__ import annotations

import dspy

from prompt_optimization.metrics import NumberMetric, SearchMetric
from prompt_optimization.prompts import AGGREGATOR_PROMPT, ATOMIZER_PROMPT, PLANNER_PROMPT

from ..contracts import BenchmarkFamilyAdapter

GENERIC_COMPONENTS = ("atomizer", "planner", "executor", "aggregator", "verifier")
GENERIC_PROMPT_BUNDLE = {
    "atomizer": ATOMIZER_PROMPT,
    "planner": PLANNER_PROMPT,
    "executor": None,
    "aggregator": AGGREGATOR_PROMPT,
    "verifier": None,
}


class StandardDatasetFamily(BenchmarkFamilyAdapter):
    """Adapter around an existing dataset_loader function plus a metric choice."""

    def __init__(self, family_name: str, loader_name: str, metric_kind: str):
        self.family_name = family_name
        self.loader_name = loader_name
        self.metric_kind = metric_kind
        self.default_profile = None

    def load_examples(self, opt_config, *, no_split: bool = False):
        from prompt_optimization import dataset_loaders as loaders

        loader = getattr(loaders, self.loader_name)
        dataset_options = dict(getattr(opt_config, "dataset_options", {}) or {})
        return loader(
            train_size=opt_config.train_size,
            val_size=opt_config.val_size,
            test_size=opt_config.test_size,
            seed=opt_config.dataset_seed,
            no_split=no_split,
            **dataset_options,
        )

    def create_scoring_metric(self, opt_config):
        if self.metric_kind == "number":
            return NumberMetric()
        if self.metric_kind == "search":
            return SearchMetric(lm_config=opt_config.judge_lm)
        raise ValueError(f"Unsupported metric kind '{self.metric_kind}'")

    def resolve_prompt_overrides(self, opt_config):
        overrides = {component: None for component in GENERIC_COMPONENTS}
        policy = opt_config.prompt_source_policy
        if policy == "preserve_profile":
            pass
        elif policy == "generic_bundle":
            overrides.update(GENERIC_PROMPT_BUNDLE)
        else:
            raise ValueError(
                f"Prompt policy '{policy}' is not supported for benchmark family '{self.family_name}'."
            )

        component = getattr(opt_config, "artifact_component", None)
        artifact_path = getattr(opt_config, "artifact_path", None)
        if artifact_path:
            if component not in overrides:
                raise ValueError(
                    f"Unknown artifact_component '{component}'. Expected one of: {', '.join(GENERIC_COMPONENTS)}."
                )
            overrides[component] = artifact_path
        return overrides

    def to_example(self, record):
        if isinstance(record, dspy.Example):
            return record
        return dspy.Example(record).with_inputs("goal")


_STANDARD_FAMILIES = {
    "aimo": ("load_aimo_datasets", "number"),
    "frames": ("load_frames_dataset", "search"),
    "simpleqa": ("load_simpleqa_dataset", "search"),
    "simpleqa_verified": ("load_simpleqa_verified_dataset", "search"),
    "seal0": ("load_seal0_dataset", "search"),
}


def get_standard_family(name: str) -> StandardDatasetFamily:
    loader_name, metric_kind = _STANDARD_FAMILIES[name]
    return StandardDatasetFamily(name, loader_name, metric_kind)
