"""Configuration management for prompt optimization."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from omegaconf import OmegaConf

from roma_dspy.config.schemas.root import ROMAConfig
from roma_dspy.types import LMBackend
from roma_dspy.utils.lm_factory import iter_role_agent_configs

from prompt_optimization.prompts import (
    AGGREGATOR_PROMPT,
    ATOMIZER_PROMPT,
    PLANNER_PROMPT,
)

OFFICEQA_COMPONENTS = (
    "atomizer",
    "planner",
    "executor",
    "aggregator",
    "verifier",
)

GENERIC_PROMPT_OVERRIDES = {
    "atomizer": ATOMIZER_PROMPT,
    "planner": PLANNER_PROMPT,
    "executor": None,
    "aggregator": AGGREGATOR_PROMPT,
    "verifier": None,
}

OFFICEQA_TRACK_A_TEXT_ARTIFACTS = {
    "atomizer": "config/examples/prompts/officeqa/atomizer_officeqa.jinja",
    "planner": "config/examples/prompts/officeqa/planner_officeqa.jinja",
    "executor": "config/examples/prompts/officeqa/executor_officeqa.jinja",
    "aggregator": "config/examples/prompts/officeqa/aggregator_officeqa.jinja",
    "verifier": "config/examples/prompts/officeqa/verifier_officeqa.jinja",
}
OPTIMIZATION_LM_FIELDS = (
    "executor_lm",
    "atomizer_lm",
    "planner_lm",
    "aggregator_lm",
    "verifier_lm",
    "judge_lm",
    "reflection_lm",
)


@dataclass
class LMConfig:
    """Language model configuration."""

    model: str
    backend: LMBackend = LMBackend.API
    temperature: float = 0.6
    max_tokens: int = 120000
    timeout: int = 120
    cache: bool = False


@dataclass
class OptimizationConfig:
    """Complete configuration for optimization pipeline."""

    executor_lm: LMConfig = field(
        default_factory=lambda: LMConfig("fireworks_ai/accounts/fireworks/models/gpt-oss-120b")
    )
    atomizer_lm: LMConfig = field(default_factory=lambda: LMConfig("gemini/gemini-2.5-flash"))
    planner_lm: LMConfig = field(default_factory=lambda: LMConfig("gemini/gemini-2.5-flash"))
    aggregator_lm: LMConfig = field(
        default_factory=lambda: LMConfig("fireworks_ai/accounts/fireworks/models/gpt-oss-120b")
    )
    verifier_lm: LMConfig = field(default_factory=lambda: LMConfig("gemini/gemini-2.5-flash"))
    judge_lm: LMConfig = field(
        default_factory=lambda: LMConfig(
            "openrouter/anthropic/claude-sonnet-4.5",
            temperature=1.0,
            max_tokens=64000,
        )
    )
    reflection_lm: LMConfig = field(
        default_factory=lambda: LMConfig(
            "openrouter/anthropic/claude-sonnet-4.5",
            temperature=1.0,
            max_tokens=64000,
        )
    )

    dataset_name: Optional[str] = None
    benchmark_family: Optional[str] = None
    profile_name: Optional[str] = None
    prompt_source_policy: str = "preserve_profile"
    preserve_profile_lms: bool = False

    dataset_options: dict[str, Any] = field(default_factory=dict)
    runtime_options: dict[str, Any] = field(default_factory=dict)
    artifact_component: Optional[str] = None
    artifact_path: Optional[str] = None

    # Backward-compatible OfficeQA-specific aliases
    officeqa_subset: str = "pro"
    officeqa_data_dir: Optional[str] = None
    officeqa_corpus_dir: Optional[str] = None
    officeqa_artifact_component: str = "planner"
    officeqa_artifact_path: Optional[str] = None

    train_size: int = 32
    val_size: int = 8
    test_size: int = 8
    dataset_seed: int = 0

    max_parallel: int = 4
    concurrency: int = 4

    max_metric_calls: int = 10
    num_threads: int = 4
    reflection_minibatch_size: int = 8
    component_selector: str = "round_robin"

    track_stats: bool = True
    track_best_outputs: bool = True
    log_dir: Optional[str] = "logs/gepa_experiments"
    use_mlflow: bool = True

    use_wandb: bool = False
    wandb_project: Optional[str] = "roma-optimization"
    wandb_entity: Optional[str] = None
    wandb_api_key: Optional[str] = None
    wandb_tags: list[str] = field(default_factory=list)
    wandb_notes: Optional[str] = None

    max_depth: int = 1
    enable_logging: bool = True

    output_path: Optional[str] = None
    env_file: Optional[str] = "../../.env"


def normalized_dataset_options(opt_config: OptimizationConfig) -> dict[str, Any]:
    options = dict(opt_config.dataset_options or {})
    if "subset" not in options and opt_config.officeqa_subset:
        options["subset"] = opt_config.officeqa_subset
    if "data_dir" not in options and opt_config.officeqa_data_dir:
        options["data_dir"] = opt_config.officeqa_data_dir
    return options


def normalized_runtime_options(opt_config: OptimizationConfig) -> dict[str, Any]:
    options = dict(opt_config.runtime_options or {})
    if "corpus_dir" not in options and opt_config.officeqa_corpus_dir:
        options["corpus_dir"] = opt_config.officeqa_corpus_dir
    return options


def normalized_artifact_override(
    opt_config: OptimizationConfig,
) -> tuple[Optional[str], Optional[str]]:
    component = opt_config.artifact_component or opt_config.officeqa_artifact_component
    path = opt_config.artifact_path or opt_config.officeqa_artifact_path
    return component, path


def resolve_benchmark_family_name(
    opt_config: OptimizationConfig,
    *,
    explicit_family: Optional[str] = None,
) -> str:
    from prompt_optimization.benchmarking import resolve_family_name

    return resolve_family_name(
        dataset_name=opt_config.dataset_name,
        profile_name=opt_config.profile_name,
        explicit=explicit_family or opt_config.benchmark_family,
    )


def apply_optimization_lm_override(
    opt_config: OptimizationConfig,
    *,
    model: Optional[str] = None,
    backend: LMBackend | str | None = None,
) -> Optional[LMBackend]:
    """Apply a model/backend override across all optimization LM roles."""
    normalized_backend = None if backend is None else LMBackend.from_string(backend)

    for field_name in OPTIMIZATION_LM_FIELDS:
        lm_cfg = getattr(opt_config, field_name, None)
        if lm_cfg is None:
            continue
        if model is not None:
            lm_cfg.model = model
        if normalized_backend is not None:
            lm_cfg.backend = normalized_backend

    return normalized_backend


def patch_romaconfig(
    opt_config: OptimizationConfig,
    base_config: ROMAConfig,
    mlflow_tracking_uri: Optional[str] = None,
) -> ROMAConfig:
    """Merge prompt optimization overrides into a ROMAConfig."""

    cfg = deepcopy(base_config)
    prompt_overrides = _resolve_prompt_overrides(opt_config)

    def _apply_agent_lm(agent_cfg, lm_cfg: LMConfig, instructions: Optional[str] = None) -> None:
        if agent_cfg is None:
            return
        if not opt_config.preserve_profile_lms:
            agent_cfg.llm.model = lm_cfg.model
            agent_cfg.llm.backend = lm_cfg.backend
            agent_cfg.llm.temperature = lm_cfg.temperature
            agent_cfg.llm.max_tokens = lm_cfg.max_tokens
            agent_cfg.llm.timeout = lm_cfg.timeout
            agent_cfg.llm.cache = lm_cfg.cache
        if instructions is not None:
            agent_cfg.signature_instructions = instructions

    for agent_cfg in iter_role_agent_configs(cfg, "atomizer"):
        _apply_agent_lm(agent_cfg, opt_config.atomizer_lm, prompt_overrides.get("atomizer"))
    for agent_cfg in iter_role_agent_configs(cfg, "planner"):
        _apply_agent_lm(agent_cfg, opt_config.planner_lm, prompt_overrides.get("planner"))
    for agent_cfg in iter_role_agent_configs(cfg, "executor"):
        _apply_agent_lm(agent_cfg, opt_config.executor_lm, prompt_overrides.get("executor"))
    for agent_cfg in iter_role_agent_configs(cfg, "aggregator"):
        _apply_agent_lm(agent_cfg, opt_config.aggregator_lm, prompt_overrides.get("aggregator"))
    for agent_cfg in iter_role_agent_configs(cfg, "verifier"):
        _apply_agent_lm(agent_cfg, opt_config.verifier_lm, prompt_overrides.get("verifier"))

    cfg.runtime.max_depth = opt_config.max_depth
    cfg.runtime.enable_logging = opt_config.enable_logging

    if opt_config.use_mlflow and mlflow_tracking_uri:
        cfg.observability.mlflow.enabled = True
        cfg.observability.mlflow.tracking_uri = mlflow_tracking_uri
        cfg.observability.mlflow.log_traces = True

    return cfg


def _resolve_prompt_overrides(opt_config: OptimizationConfig) -> dict[str, Optional[str]]:
    try:
        from prompt_optimization.benchmarking import get_family

        family_name = resolve_benchmark_family_name(opt_config)
        return get_family(family_name).resolve_prompt_overrides(opt_config)
    except ValueError:
        return _resolve_generic_prompt_overrides(opt_config)


def _resolve_generic_prompt_overrides(
    opt_config: OptimizationConfig,
) -> dict[str, Optional[str]]:
    overrides = {component: None for component in OFFICEQA_COMPONENTS}
    policy = opt_config.prompt_source_policy
    if policy == "preserve_profile":
        pass
    elif policy == "generic_bundle":
        overrides.update(GENERIC_PROMPT_OVERRIDES)
    else:
        raise ValueError(
            f"Unknown prompt_source_policy '{policy}'. Expected one of: preserve_profile, generic_bundle."
        )

    component, artifact_path = normalized_artifact_override(opt_config)
    if artifact_path:
        if component not in overrides:
            raise ValueError(
                f"Unknown artifact_component '{component}'. Expected one of: {', '.join(OFFICEQA_COMPONENTS)}."
            )
        overrides[component] = artifact_path
    return overrides


def get_default_config() -> OptimizationConfig:
    return OptimizationConfig()


def load_config_from_yaml(path: str) -> OptimizationConfig:
    cfg = OmegaConf.load(path)
    structured = OmegaConf.structured(OptimizationConfig)
    merged = OmegaConf.merge(structured, cfg)
    return OmegaConf.to_object(merged)


def save_config_to_yaml(config: OptimizationConfig, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    cfg = OmegaConf.structured(config)
    OmegaConf.save(cfg, path)
