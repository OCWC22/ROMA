"""Shared subprocess transport for Claude Code / Codex subscription CLIs."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from roma_dspy.types import LMBackend

_CLI_CACHE: dict[str, "CLIRunResult"] = {}
_CLI_CACHE_LOCK = threading.Lock()
_CLI_AUTH_CACHE: dict[LMBackend, bool] = {}
_CLI_AUTH_LOCK = threading.Lock()
_CLI_WORKDIR = Path(tempfile.gettempdir()) / "roma_cli_lm_workspace"
_CLI_WORKDIR.mkdir(parents=True, exist_ok=True)
_PREFERRED_BIN_DIRS = (
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
)


def _stringify_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                item_type = item.get("type")
                if item_type in {"text", "input_text"}:
                    parts.append(str(item.get("text", "")))
                elif "text" in item:
                    parts.append(str(item["text"]))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False, sort_keys=True))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        if "text" in value and isinstance(value["text"], str):
            return value["text"]
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def render_cli_prompt(
    *,
    prompt: Optional[str] = None,
    messages: Optional[list[dict[str, Any]]] = None,
) -> tuple[str, str]:
    """Render DSPy/OpenAI-style prompt inputs into CLI-friendly text."""
    if not messages:
        return "", str(prompt or "")

    system_parts: list[str] = []
    transcript_parts: list[str] = []
    non_system_messages = [msg for msg in messages if msg.get("role") != "system"]

    for message in messages:
        role = str(message.get("role", "user")).strip().lower() or "user"
        content = _stringify_content(message.get("content"))
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
            continue
        if len(non_system_messages) == 1 and role == "user":
            transcript_parts.append(content)
        else:
            transcript_parts.append(f"{role.upper()}:\n{content}")

    if not transcript_parts and prompt:
        transcript_parts.append(str(prompt))

    return "\n\n".join(system_parts).strip(), "\n\n".join(transcript_parts).strip()


def estimate_token_count(text: str) -> int:
    """Cheap token estimate for CLI models that do not expose usage data."""
    if not text:
        return 0
    return max(1, round(len(text) / 4))


@dataclass(frozen=True)
class CLIRunResult:
    """Normalized result from a CLI completion call."""

    text: str
    backend: str
    model: str
    duration: float
    stdout: str = ""
    stderr: str = ""
    cache_hit: bool = False
    usage: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class CLIRunner:
    """Thin runner around authenticated Claude Code / Codex subscriptions."""

    def __init__(
        self,
        *,
        backend: LMBackend | str,
        timeout: int = 120,
        cwd: Optional[str | Path] = None,
    ) -> None:
        self.backend = LMBackend.from_string(backend)
        self.timeout = timeout
        self.cwd = Path(cwd).expanduser().resolve() if cwd else _CLI_WORKDIR

    def ensure_authenticated(self) -> None:
        """Verify that the configured subscription CLI is installed and logged in."""
        with _CLI_AUTH_LOCK:
            cached = _CLI_AUTH_CACHE.get(self.backend)
            if cached:
                return

            if self.backend == LMBackend.CLAUDE:
                status_cmd = ["claude", "auth", "status"]
            elif self.backend == LMBackend.CODEX:
                status_cmd = ["codex", "login", "status"]
            else:
                raise ValueError(f"CLI auth check requested for non-CLI backend {self.backend}")

            try:
                result = subprocess.run(
                    status_cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    cwd=str(self.cwd),
                    env=self._build_subprocess_env(),
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    f"{self.backend.cli_command} CLI is not installed or not on PATH."
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"{self.backend.cli_command} CLI auth status timed out."
                ) from exc

            if result.returncode != 0:
                stderr = (result.stderr or result.stdout or "").strip()
                raise RuntimeError(
                    f"{self.backend.cli_command} CLI is not authenticated. "
                    f"Status output: {stderr or 'unknown error'}"
                )

            _CLI_AUTH_CACHE[self.backend] = True

    def run(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str = "",
        cache: bool = True,
        timeout: Optional[int] = None,
    ) -> CLIRunResult:
        """Execute a non-interactive CLI completion."""
        self.ensure_authenticated()

        effective_timeout = timeout or self.timeout
        cache_key = self._build_cache_key(
            backend=self.backend,
            model=model,
            prompt=prompt,
            system_prompt=system_prompt,
        )

        if cache:
            with _CLI_CACHE_LOCK:
                cached = _CLI_CACHE.get(cache_key)
            if cached is not None:
                return CLIRunResult(
                    text=cached.text,
                    backend=cached.backend,
                    model=cached.model,
                    duration=0.0,
                    stdout=cached.stdout,
                    stderr=cached.stderr,
                    cache_hit=True,
                    usage=dict(cached.usage),
                    metadata=dict(cached.metadata),
                )

        started = time.time()
        if self.backend == LMBackend.CLAUDE:
            result = self._run_claude(
                model=model,
                prompt=prompt,
                system_prompt=system_prompt,
                timeout=effective_timeout,
            )
        elif self.backend == LMBackend.CODEX:
            result = self._run_codex(
                model=model,
                prompt=prompt,
                system_prompt=system_prompt,
                timeout=effective_timeout,
            )
        else:
            raise ValueError(f"Unsupported CLI backend: {self.backend}")

        duration = time.time() - started
        usage = {
            "prompt_tokens": estimate_token_count(f"{system_prompt}\n\n{prompt}"),
            "completion_tokens": estimate_token_count(result.text),
            "total_tokens": estimate_token_count(f"{system_prompt}\n\n{prompt}")
            + estimate_token_count(result.text),
        }
        normalized = CLIRunResult(
            text=result.text,
            backend=self.backend.value,
            model=model,
            duration=duration,
            stdout=result.stdout,
            stderr=result.stderr,
            cache_hit=False,
            usage=usage,
            metadata=dict(result.metadata),
        )

        if cache:
            with _CLI_CACHE_LOCK:
                _CLI_CACHE[cache_key] = normalized

        return normalized

    def _run_claude(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str,
        timeout: int,
    ) -> CLIRunResult:
        cmd = [
            "claude",
            "--print",
            "--output-format",
            "text",
            "--no-session-persistence",
            "--permission-mode",
            "dontAsk",
            "--tools",
            "",
            "--model",
            model,
        ]
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])
        cmd.append(prompt)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(self.cwd),
            env=self._build_subprocess_env(),
        )
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        if result.returncode != 0:
            raise RuntimeError(
                f"claude CLI call failed (exit {result.returncode}): {stderr or stdout or 'no output'}"
            )
        if not stdout:
            raise RuntimeError("claude CLI returned empty output.")

        return CLIRunResult(
            text=stdout,
            backend=self.backend.value,
            model=model,
            duration=0.0,
            stdout=stdout,
            stderr=stderr,
            metadata={"command": "claude --print"},
        )

    def _run_codex(
        self,
        *,
        model: str,
        prompt: str,
        system_prompt: str,
        timeout: int,
    ) -> CLIRunResult:
        rendered_prompt = prompt
        if system_prompt:
            rendered_prompt = (
                "SYSTEM INSTRUCTIONS:\n"
                f"{system_prompt}\n\n"
                "USER REQUEST:\n"
                f"{prompt}"
            )

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
            output_path = Path(handle.name)

        cmd = [
            "codex",
            "exec",
            "-C",
            str(self.cwd),
            "-c",
            'mcp_servers={}',
            "-c",
            'model_reasoning_effort="low"',
            "-c",
            "features.multi_agent=false",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "-m",
            model,
            "-o",
            str(output_path),
            "-",
        ]

        try:
            result = subprocess.run(
                cmd,
                input=rendered_prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.cwd),
                env=self._build_subprocess_env(),
            )
            stdout = (result.stdout or "").strip()
            stderr = (result.stderr or "").strip()
            output_text = output_path.read_text().strip() if output_path.exists() else ""

            if result.returncode != 0:
                raise RuntimeError(
                    f"codex exec failed (exit {result.returncode}): "
                    f"{stderr or stdout or output_text or 'no output'}"
                )
            if not output_text:
                output_text = stdout
            if not output_text:
                raise RuntimeError("codex exec returned empty output.")

            return CLIRunResult(
                text=output_text,
                backend=self.backend.value,
                model=model,
                duration=0.0,
                stdout=stdout,
                stderr=stderr,
                metadata={"command": "codex exec"},
            )
        finally:
            output_path.unlink(missing_ok=True)

    @staticmethod
    def _build_cache_key(
        *,
        backend: LMBackend,
        model: str,
        prompt: str,
        system_prompt: str,
    ) -> str:
        payload = json.dumps(
            {
                "backend": backend.value,
                "model": model,
                "system_prompt": system_prompt,
                "prompt": prompt,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _build_subprocess_env() -> dict[str, str]:
        """Build a stable subprocess environment for CLI tools.

        Detached shells (e.g. tmux/background jobs) can inherit an older PATH ordering
        that resolves `node` differently than the interactive shell. Claude Code's npm
        wrapper relies on a modern Node runtime, so we explicitly prioritize common
        Homebrew/local bin directories before the inherited PATH.
        """
        env = os.environ.copy()
        inherited = env.get("PATH", "")
        path_entries = [entry for entry in inherited.split(os.pathsep) if entry]

        ordered: list[str] = []
        seen: set[str] = set()

        for preferred in _PREFERRED_BIN_DIRS:
            preferred_str = str(preferred)
            if not preferred.exists() or preferred_str in seen:
                continue
            ordered.append(preferred_str)
            seen.add(preferred_str)

        for entry in path_entries:
            if entry in seen:
                continue
            ordered.append(entry)
            seen.add(entry)

        if ordered:
            env["PATH"] = os.pathsep.join(ordered)
        env.setdefault("TERM", "xterm-256color")
        return env
