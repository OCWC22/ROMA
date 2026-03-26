"""DSPy-compatible LM wrapper backed by Claude Code / Codex CLIs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from dspy.clients.base_lm import BaseLM
from loguru import logger

from roma_dspy.types import LMBackend
from roma_dspy.utils.cli_runner import CLIRunner, render_cli_prompt


@dataclass
class _CLIMessage:
    content: str
    tool_calls: Optional[list[dict[str, Any]]] = None


@dataclass
class _CLIChoice:
    message: _CLIMessage
    logprobs: Optional[Any] = None


@dataclass
class CLICompletionResponse:
    """Minimal chat-completion response shape expected by DSPy BaseLM."""

    model: str
    choices: list[_CLIChoice]
    usage: dict[str, int] = field(default_factory=dict)
    cache_hit: bool = False
    _hidden_params: dict[str, Any] = field(default_factory=dict)


class CLILM(BaseLM):
    """A DSPy BaseLM implementation that executes through a subscription CLI."""

    def __init__(
        self,
        model: str,
        *,
        backend: LMBackend | str,
        model_type: str = "chat",
        temperature: float = 0.0,
        max_tokens: int = 4000,
        cache: bool = True,
        timeout: int = 120,
        num_retries: int = 1,
        runner: Optional[CLIRunner] = None,
        **kwargs,
    ) -> None:
        backend_enum = LMBackend.from_string(backend)
        if not backend_enum.is_cli:
            raise ValueError(f"CLILM requires a CLI backend, got {backend_enum}")

        super().__init__(
            model=model,
            model_type=model_type,
            temperature=temperature,
            max_tokens=max_tokens,
            cache=cache,
            timeout=timeout,
            **kwargs,
        )
        self.backend = backend_enum
        self.timeout = timeout
        self.num_retries = num_retries
        self.runner = runner or CLIRunner(backend=backend_enum, timeout=timeout)
        self.finetuning_model = None
        self.launch_kwargs = None
        self.train_kwargs = None
        self.use_developer_role = False
        self._warned_unsupported: set[str] = set()

    def forward(self, prompt=None, messages=None, **kwargs):
        request_kwargs = {**self.kwargs, **kwargs}
        cache_enabled = kwargs.pop("cache", self.cache)
        timeout = int(request_kwargs.get("timeout", self.timeout))
        system_prompt, rendered_prompt = render_cli_prompt(prompt=prompt, messages=messages)
        self._warn_on_unsupported_request_kwargs(request_kwargs)

        last_error: Exception | None = None
        for attempt in range(self.num_retries + 1):
            try:
                result = self.runner.run(
                    model=self.model,
                    prompt=rendered_prompt,
                    system_prompt=system_prompt,
                    cache=cache_enabled,
                    timeout=timeout,
                )
                return CLICompletionResponse(
                    model=self.model,
                    choices=[_CLIChoice(message=_CLIMessage(content=result.text))],
                    usage=dict(result.usage),
                    cache_hit=result.cache_hit,
                    _hidden_params={"cli_backend": self.backend.value, **result.metadata},
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= self.num_retries:
                    raise
                logger.warning(
                    "CLI LM call failed on attempt {attempt}/{total} for {backend}:{model}: {error}",
                    attempt=attempt + 1,
                    total=self.num_retries + 1,
                    backend=self.backend.value,
                    model=self.model,
                    error=exc,
                )

        assert last_error is not None
        raise last_error

    async def aforward(self, prompt=None, messages=None, **kwargs):
        return await asyncio.to_thread(
            self.forward,
            prompt=prompt,
            messages=messages,
            **kwargs,
        )

    def _warn_on_unsupported_request_kwargs(self, request_kwargs: dict[str, Any]) -> None:
        unsupported_keys = []
        if request_kwargs.get("temperature") not in (None, 0.0):
            unsupported_keys.append("temperature")
        if request_kwargs.get("max_tokens") not in (None, self.kwargs.get("max_tokens")):
            unsupported_keys.append("max_tokens")
        for key in ("tools", "tool_choice", "extra_body", "api_key", "base_url"):
            if request_kwargs.get(key) not in (None, [], {}, False):
                unsupported_keys.append(key)

        for key in unsupported_keys:
            if key in self._warned_unsupported:
                continue
            self._warned_unsupported.add(key)
            logger.warning(
                "CLILM backend {backend} does not natively honor LM kwarg '{key}'. "
                "Continuing with prompt-only CLI execution.",
                backend=self.backend.value,
                key=key,
            )

