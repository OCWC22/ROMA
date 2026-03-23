"""
Codex/Claude CLI Auth Integration for ROMA

This module provides authentication via Codex CLI and Claude Code CLI
instead of direct API keys, allowing use of subscriptions.

Usage:
    from scripts.codex_cli_auth import get_codex_client, get_claude_client
    
    # Uses CLI auth (subscription) instead of API key
    client = get_codex_client()
    response = client.chat("Hello")
"""

import subprocess
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any


class CodexCLIAuth:
    """
    Authenticate and make calls via Codex CLI
    
    This uses the OpenAI subscription via CLI instead of direct API keys.
    """
    
    def __init__(self):
        self._check_codex_installed()
        self._session_token = None
    
    def _check_codex_installed(self):
        """Check if Codex CLI is installed"""
        try:
            result = subprocess.run(
                ["codex", "--version"],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise RuntimeError("Codex CLI not installed. Run: npm install -g @openai/codex")
        except FileNotFoundError:
            raise RuntimeError("Codex CLI not found. Run: npm install -g @openai/codex")
    
    def login_with_api_key(self, api_key: str):
        """Login with API key (one-time setup)"""
        result = subprocess.run(
            f'echo "{api_key}" | codex login --with-api-key',
            shell=True,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"Codex login failed: {result.stderr}")
        print("Codex CLI authenticated successfully")
    
    def chat(self, prompt: str, model: str = "gpt-4o") -> str:
        """
        Send a chat message via Codex CLI
        
        Args:
            prompt: The message to send
            model: Model to use (gpt-4o, gpt-4o-mini, o1, etc.)
        
        Returns:
            Model response
        """
        # Use codex CLI to send the message
        result = subprocess.run(
            ["codex", "chat", "--model", model, "--prompt", prompt],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Codex chat failed: {result.stderr}")
        
        return result.stdout.strip()
    
    def run_agent(self, task: str, model: str = "gpt-4o") -> Dict[str, Any]:
        """
        Run an agentic task via Codex CLI
        
        Args:
            task: The task description
            model: Model to use
        
        Returns:
            Result with answer and trace
        """
        result = subprocess.run(
            ["codex", "run", "--model", model, "--task", task, "--json"],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Codex run failed: {result.stderr}")
        
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"answer": result.stdout.strip(), "raw": True}


class ClaudeCLIAuth:
    """
    Authenticate and make calls via Claude Code CLI
    
    This uses the Anthropic subscription via CLI instead of direct API keys.
    """
    
    def __init__(self):
        self._check_claude_installed()
    
    def _check_claude_installed(self):
        """Check if Claude Code CLI is installed"""
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise RuntimeError("Claude Code CLI not installed. Run: npm install -g @anthropic-ai/claude-code")
        except FileNotFoundError:
            raise RuntimeError("Claude Code CLI not found. Run: npm install -g @anthropic-ai/claude-code")
    
    def login(self):
        """Interactive login (opens browser)"""
        result = subprocess.run(
            ["claude", "login"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"Claude login failed: {result.stderr}")
        print("Claude Code CLI authenticated successfully")
    
    def chat(self, prompt: str, model: str = "claude-sonnet-4-5-20250929") -> str:
        """
        Send a chat message via Claude CLI
        
        Args:
            prompt: The message to send
            model: Model to use
        
        Returns:
            Model response
        """
        result = subprocess.run(
            ["claude", "chat", "--model", model, "--prompt", prompt],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Claude chat failed: {result.stderr}")
        
        return result.stdout.strip()
    
    def run_agent(self, task: str, model: str = "claude-sonnet-4-5-20250929") -> Dict[str, Any]:
        """
        Run an agentic task via Claude CLI
        
        Args:
            task: The task description
            model: Model to use
        
        Returns:
            Result with answer and trace
        """
        result = subprocess.run(
            ["claude", "run", "--model", model, "--task", task, "--json"],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Claude run failed: {result.stderr}")
        
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"answer": result.stdout.strip(), "raw": True}


class DSPyCLIAuthAdapter:
    """
    Adapter to use CLI auth with DSPy
    
    This allows DSPy to use Codex/Claude CLI instead of direct API keys.
    """
    
    def __init__(self, provider: str = "openai"):
        """
        Initialize adapter
        
        Args:
            provider: "openai" for Codex CLI, "anthropic" for Claude CLI
        """
        self.provider = provider
        
        if provider == "openai":
            self.client = CodexCLIAuth()
        elif provider == "anthropic":
            self.client = ClaudeCLIAuth()
        else:
            raise ValueError(f"Unknown provider: {provider}")
    
    def __call__(self, prompt: str, **kwargs) -> str:
        """Make a call via CLI auth"""
        model = kwargs.get("model", "gpt-4o" if self.provider == "openai" else "claude-sonnet-4-5-20250929")
        return self.client.chat(prompt, model=model)


def get_codex_client() -> CodexCLIAuth:
    """Get authenticated Codex CLI client"""
    return CodexCLIAuth()


def get_claude_client() -> ClaudeCLIAuth:
    """Get authenticated Claude CLI client"""
    return ClaudeCLIAuth()


def get_dspy_adapter(provider: str = "openai") -> DSPyCLIAuthAdapter:
    """
    Get DSPy adapter that uses CLI auth
    
    Usage with DSPy:
        import dspy
        from scripts.codex_cli_auth import get_dspy_adapter
        
        # Use CLI auth instead of API key
        adapter = get_dspy_adapter("openai")
        dspy.configure(lm=adapter)
    """
    return DSPyCLIAuthAdapter(provider)


def setup_dspy_with_cli_auth(default_provider: str = "openai"):
    """
    Configure DSPy to use CLI auth by default
    
    This replaces the need for OPENAI_API_KEY or ANTHROPIC_API_KEY
    environment variables.
    """
    import dspy
    
    adapter = get_dspy_adapter(default_provider)
    
    # Monkey-patch DSPy's LM to use our adapter
    class CLIAuthLM(dspy.LM):
        def __init__(self, model, **kwargs):
            super().__init__(model, **kwargs)
            self.adapter = get_dspy_adapter(
                "openai" if "gpt" in model or "o1" in model else "anthropic"
            )
        
        def __call__(self, prompt, **kwargs):
            return self.adapter(prompt, model=self.model, **kwargs)
    
    # Set as default
    dspy.configure(lm=CLIAuthLM("gpt-4o"))
    
    print(f"DSPy configured to use CLI auth (provider: {default_provider})")


# Auto-setup when imported (optional)
def auto_setup():
    """Auto-setup CLI auth if no API keys are set"""
    if not os.environ.get("OPENAI_API_KEY") and not os.environ.get("ANTHROPIC_API_KEY"):
        print("No API keys found, attempting CLI auth setup...")
        try:
            setup_dspy_with_cli_auth()
        except Exception as e:
            print(f"CLI auth setup failed: {e}")
            print("Falling back to API key auth")


if __name__ == "__main__":
    # Test the CLI auth
    print("Testing Codex CLI auth...")
    try:
        codex = get_codex_client()
        response = codex.chat("Say 'Hello from Codex CLI!'")
        print(f"Codex response: {response}")
    except Exception as e:
        print(f"Codex test failed: {e}")
    
    print("\nTesting Claude CLI auth...")
    try:
        claude = get_claude_client()
        response = claude.chat("Say 'Hello from Claude CLI!'")
        print(f"Claude response: {response}")
    except Exception as e:
        print(f"Claude test failed: {e}")