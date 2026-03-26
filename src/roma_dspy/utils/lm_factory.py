"""Shared helpers for constructing API-backed or CLI-backed DSPy LMs."""

from __future__ import annotations

from typing import Any, Optional

from roma_dspy.types import LMBackend
from roma_dspy.utils.cli_lm import CLILM
from roma_dspy.utils.alibaba_lm import AlibabaLM

AGENT_LM_FIELDS = (
    "atomizer",
    "planner",
    "executor",
    "aggregator",
    "verifier",
)
ROLE_TO_MAPPING_ATTR = {
    "atomizer": "atomizers",
    "planner": "planners",
    "executor": "executors",
    "aggregator": "aggregators",
    "verifier": "verifiers",
}


def normalize_lm_backend(backend: LMBackend | str | None) -> LMBackend:
    """Normalize optional backend input."""
    if backend is None:
        return LMBackend.API
    return LMBackend.from_string(backend)


def backend_from_cli_name(cli: str | None) -> LMBackend:
    """Map benchmark CLI names onto LM backends."""
    if not cli:
        return LMBackend.CLAUDE
    return LMBackend.from_string(cli)


def iter_role_agent_configs(config: Any, role: str) -> list[Any]:
    """Return all configs for a role across base agents and task-aware mappings."""
    if role not in ROLE_TO_MAPPING_ATTR:
        raise ValueError(
            f"Unsupported role '{role}'. Expected one of: {', '.join(AGENT_LM_FIELDS)}"
        )

    results: list[Any] = []
    agents = getattr(config, "agents", None)
    if agents is not None:
        agent_cfg = getattr(agents, role, None)
        if agent_cfg is not None:
            results.append(agent_cfg)

    agent_mapping = getattr(config, "agent_mapping", None)
    if agent_mapping is None:
        return results

    default_cfg = getattr(agent_mapping, f"default_{role}", None)
    if default_cfg is not None:
        results.append(default_cfg)

    mapped_cfgs = getattr(agent_mapping, ROLE_TO_MAPPING_ATTR[role], {}) or {}
    results.extend(cfg for cfg in mapped_cfgs.values() if cfg is not None)
    return results


def config_uses_cli_backend(config: Any) -> bool:
    """Whether any configured agent or mapped agent uses a CLI backend."""
    for role in AGENT_LM_FIELDS:
        for agent_cfg in iter_role_agent_configs(config, role):
            llm_cfg = getattr(agent_cfg, "llm", None)
            if llm_cfg is not None and getattr(llm_cfg, "backend", LMBackend.API).is_cli:
                return True
    return False


def disable_toolkits_by_class_name(
    config: Any,
    toolkit_class_names: set[str] | list[str] | tuple[str, ...],
    *,
    roles: tuple[str, ...] | list[str] | None = None,
) -> None:
    """Disable toolkit classes anywhere they appear on relevant agent configs."""
    target_names = set(toolkit_class_names)
    target_roles = tuple(roles or AGENT_LM_FIELDS)

    for role in target_roles:
        for agent_cfg in iter_role_agent_configs(config, role):
            for toolkit in getattr(agent_cfg, "toolkits", []) or []:
                if toolkit.class_name in target_names:
                    toolkit.enabled = False


def apply_backend_capability_constraints(config: Any) -> Any:
    """Disable API-only toolkit integrations when the config uses CLI LMs."""
    if config_uses_cli_backend(config):
        disable_toolkits_by_class_name(config, {"WebSearchToolkit"})
    return config


def build_lm_kwargs_from_config(llm_config: Any) -> dict[str, Any]:
    """Extract DSPy LM kwargs from a config-like object."""
    lm_kwargs = {
        "temperature": getattr(llm_config, "temperature", 0.0),
        "max_tokens": getattr(llm_config, "max_tokens", 4000),
        "timeout": getattr(llm_config, "timeout", 120),
        "num_retries": getattr(llm_config, "num_retries", 1),
        "cache": getattr(llm_config, "cache", True),
    }
    if getattr(llm_config, "api_key", None):
        lm_kwargs["api_key"] = llm_config.api_key
    if getattr(llm_config, "base_url", None):
        lm_kwargs["base_url"] = llm_config.base_url
    if getattr(llm_config, "rollout_id", None) is not None:
        lm_kwargs["rollout_id"] = llm_config.rollout_id
    if getattr(llm_config, "extra_body", None):
        lm_kwargs["extra_body"] = llm_config.extra_body
    return lm_kwargs


def create_lm(
    model: str,
    *,
    backend: LMBackend | str | None = None,
    **kwargs,
):
    """Create the appropriate DSPy LM implementation for the chosen backend."""
    normalized_backend = normalize_lm_backend(backend)
    if normalized_backend == LMBackend.API:
        return AlibabaLM(model=model, **kwargs)
    return CLILM(model=model, backend=normalized_backend, **kwargs)


def create_lm_from_config(llm_config: Any):
    """Build an LM from an LLMConfig-like object."""
    return create_lm(
        getattr(llm_config, "model"),
        backend=getattr(llm_config, "backend", LMBackend.API),
        **build_lm_kwargs_from_config(llm_config),
    )


def create_gepa_reflection_lm(lm_config: Any):
    """Build a GEPA-compatible reflection LM object for API or CLI backends."""
    backend = normalize_lm_backend(getattr(lm_config, "backend", LMBackend.API))
    if backend == LMBackend.API:
        return getattr(lm_config, "model")

    cli_lm = create_lm_from_config(lm_config)

    def _reflection_callable(prompt: str) -> str:
        outputs = cli_lm(prompt=prompt)
        if isinstance(outputs, list) and outputs:
            return str(outputs[0])
        return str(outputs)

    return _reflection_callable


def apply_global_lm_override(
    config: Any,
    *,
    model: Optional[str] = None,
    backend: LMBackend | str | None = None,
):
    """Apply a single LM model/backend override across all core ROMA agents."""
    if model is None and backend is None:
        return config

    normalized_backend = None if backend is None else normalize_lm_backend(backend)
    for field_name in AGENT_LM_FIELDS:
        for agent_cfg in iter_role_agent_configs(config, field_name):
            llm_cfg = getattr(agent_cfg, "llm", None)
            if llm_cfg is None:
                continue
            if model is not None:
                llm_cfg.model = model
            if normalized_backend is not None:
                llm_cfg.backend = normalized_backend

    return config

