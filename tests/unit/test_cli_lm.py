"""Tests for CLI-backed DSPy LM support."""

from pathlib import Path
from types import SimpleNamespace

import dspy

from roma_dspy.types import LMBackend
from roma_dspy.utils.cli_lm import CLILM
from roma_dspy.utils.cli_runner import CLIRunResult, CLIRunner, render_cli_prompt
from roma_dspy.utils.lm_factory import create_gepa_reflection_lm, create_lm
from prompt_optimization.config import LMConfig as OptimizationLMConfig


class DummyRunner:
    def __init__(self):
        self.calls = []

    def run(self, *, model, prompt, system_prompt="", cache=True, timeout=None):
        self.calls.append(
            {
                "model": model,
                "prompt": prompt,
                "system_prompt": system_prompt,
                "cache": cache,
                "timeout": timeout,
            }
        )
        return CLIRunResult(
            text="final answer",
            backend="claude",
            model=model,
            duration=0.01,
            usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        )


def test_render_cli_prompt_splits_system_and_messages():
    system_prompt, prompt = render_cli_prompt(
        messages=[
            {"role": "system", "content": "Be precise."},
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "Prior answer"},
            {"role": "user", "content": "Follow up"},
        ]
    )

    assert system_prompt == "Be precise."
    assert "USER:\nQuestion" in prompt
    assert "ASSISTANT:\nPrior answer" in prompt
    assert "USER:\nFollow up" in prompt


def test_cli_lm_returns_dspy_compatible_outputs():
    lm = CLILM(
        model="claude-sonnet-4-5",
        backend=LMBackend.CLAUDE,
        runner=DummyRunner(),
        cache=True,
        timeout=77,
    )

    outputs = lm(messages=[{"role": "system", "content": "Be terse."}, {"role": "user", "content": "Hello"}])

    assert outputs == ["final answer"]
    assert lm.history[-1]["usage"]["total_tokens"] == 5
    assert lm.history[-1]["response"].cache_hit is False


def test_cli_lm_copy_is_deepcopy_safe():
    lm = CLILM(
        model="claude-sonnet-4-5",
        backend="claude",
        runner=DummyRunner(),
        cache=True,
    )

    copied = lm.copy(rollout_id=7)

    assert copied is not lm
    assert copied.backend == LMBackend.CLAUDE
    assert copied.kwargs["rollout_id"] == 7


def test_lm_factory_creates_api_and_cli_variants():
    api_lm = create_lm("openai/gpt-4o-mini", backend="api")
    cli_lm = create_lm("claude-sonnet-4-5", backend="claude", runner=DummyRunner())

    assert isinstance(api_lm, dspy.LM)
    assert isinstance(cli_lm, CLILM)


def test_create_gepa_reflection_lm_wraps_cli_backends():
    reflection = create_gepa_reflection_lm(
        OptimizationLMConfig(
            model="claude-sonnet-4-5",
            backend=LMBackend.CLAUDE,
        )
    )

    assert callable(reflection)


def test_cli_runner_builds_stable_subprocess_path(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    env = CLIRunner._build_subprocess_env()
    path_entries = env["PATH"].split(":")

    expected_prefix = [
        candidate
        for candidate in ("/opt/homebrew/bin", "/usr/local/bin")
        if Path(candidate).exists()
    ]
    assert path_entries[: len(expected_prefix)] == expected_prefix
    assert "/usr/bin" in path_entries
    assert env["TERM"]
