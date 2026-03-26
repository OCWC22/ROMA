"""Language-model backend selection for ROMA/DSPy."""

from __future__ import annotations

from enum import Enum
from typing import Literal


class LMBackend(str, Enum):
    """Supported LM execution backends."""

    API = "api"
    CLAUDE = "claude"
    CODEX = "codex"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_string(cls, value: str | "LMBackend") -> "LMBackend":
        """Parse a backend enum from string input."""
        if isinstance(value, cls):
            return value

        normalized = str(value or "").strip().lower()
        aliases = {
            "api": cls.API,
            "litellm": cls.API,
            "openrouter": cls.API,
            "openai": cls.API,
            "claude": cls.CLAUDE,
            "claude_code": cls.CLAUDE,
            "claude-code": cls.CLAUDE,
            "codex": cls.CODEX,
            "codex_cli": cls.CODEX,
            "codex-cli": cls.CODEX,
        }
        try:
            return aliases[normalized]
        except KeyError as exc:
            raise ValueError(
                f"Unsupported LM backend '{value}'. Expected one of: "
                "api, claude, codex."
            ) from exc

    @property
    def is_cli(self) -> bool:
        """Whether the backend is a subscription CLI rather than an API LM."""
        return self in {LMBackend.CLAUDE, LMBackend.CODEX}

    @property
    def cli_command(self) -> str | None:
        """Command name for CLI-backed models."""
        if self == LMBackend.CLAUDE:
            return "claude"
        if self == LMBackend.CODEX:
            return "codex"
        return None


LMBackendLiteral = Literal["api", "claude", "codex"]

