"""Custom DSPy Language Model client for Alibaba Model Studio without LiteLLM."""

import json
import time
import asyncio
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Optional

from dspy.clients.base_lm import BaseLM
from loguru import logger

@dataclass
class _APIContent:
    """Minimal message format for DSPy LMs."""
    content: str
    tool_calls: Optional[list[dict[str, Any]]] = None

@dataclass
class _APIChoice:
    """Minimal choice format for DSPy LMs."""
    message: _APIContent
    logprobs: Optional[Any] = None

@dataclass
class APICompletionResponse:
    """Response format conforming to DSPy's internal expectations."""
    model: str
    choices: list[_APIChoice]
    usage: dict[str, int] = field(default_factory=dict)
    cache_hit: bool = False
    _hidden_params: dict[str, Any] = field(default_factory=dict)


class AlibabaLM(BaseLM):
    """A direct REST client for Alibaba Model Studio compatible with DSPy."""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: str = "https://coding-intl.dashscope.aliyuncs.com/v1",
        model_type: str = "chat",
        temperature: float = 0.0,
        max_tokens: int = 4000,
        cache: bool = True,
        timeout: int = 120,
        num_retries: int = 3,
        **kwargs,
    ) -> None:
        import os
        api_key = api_key or os.environ.get("DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError("AlibabaLM requires a valid api_key.")

        super().__init__(
            model=model,
            model_type=model_type,
            temperature=temperature,
            max_tokens=max_tokens,
            cache=cache,
            timeout=timeout,
            **kwargs,
        )
        self.api_key = api_key
        
        # Ensure URL correctly mounts the OpenAI-compatible completion schema
        if not base_url.endswith("/chat/completions"):
            self.api_endpoint = f"{base_url.rstrip('/')}/chat/completions"
        else:
            self.api_endpoint = base_url
            
        self.timeout = timeout
        self.num_retries = num_retries
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _prepare_payload(self, prompt: Optional[str], messages: Optional[list[dict]], kwargs: dict) -> dict[str, Any]:
        msgs = messages
        if msgs is None:
            msgs = [{"role": "user", "content": prompt}]
            
        payload = {
            "model": self.model,
            "messages": msgs,
            "temperature": kwargs.get("temperature", self.kwargs.get("temperature", 0.0)),
        }
        
        max_tokens = kwargs.get("max_tokens", self.kwargs.get("max_tokens", 4000))
        if max_tokens is not None:
            if max_tokens > 98304:
                max_tokens = 98304
            payload["max_tokens"] = max_tokens
            
        # Support stop sequences gracefully if DSPy engines inject them
        if "stop" in kwargs:
            payload["stop"] = kwargs["stop"]
            
        return payload

    def _parse_response(self, response_data: dict[str, Any]) -> APICompletionResponse:
        choices = response_data.get("choices", [])
        if not choices:
            raise ValueError(f"Empty choices or API Failure: {response_data}")
        
        choice = choices[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        
        return APICompletionResponse(
            model=self.model,
            choices=[_APIChoice(message=_APIContent(content=content))],
            usage=response_data.get("usage", {}),
            cache_hit=False,
            _hidden_params={"backend": "alibaba_custom"},
        )

    def forward(self, prompt: Optional[str] = None, messages: Optional[list[dict]] = None, **kwargs):
        """Synchronous REST forward using urllib to survive macOS fork constraints."""
        payload = self._prepare_payload(prompt, messages, kwargs)
        
        last_error = None
        for attempt in range(self.num_retries + 1):
            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(self.api_endpoint, data=data, headers=self.headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    res_body = response.read()
                    return self._parse_response(json.loads(res_body))
            except urllib.error.HTTPError as e:
                import traceback
                traceback.print_exc()
                last_error = f"HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}"
                if attempt < self.num_retries:
                    logger.warning(
                        "AlibabaLM Sync API failed on attempt {}/{} for model {}: {}",
                        attempt + 1, self.num_retries + 1, self.model, last_error
                    )
                    time.sleep(2 ** attempt)
            except Exception as e:
                import traceback
                traceback.print_exc()
                last_error = str(e)
                if attempt < self.num_retries:
                    logger.warning(
                        "AlibabaLM Sync API failed on attempt {}/{} for model {}: {}",
                        attempt + 1, self.num_retries + 1, self.model, e
                    )
                    time.sleep(2 ** attempt)
                
        raise RuntimeError(f"Alibaba API Backend Error: {str(last_error)}")

    async def aforward(self, prompt: Optional[str] = None, messages: Optional[list[dict]] = None, **kwargs):
        """Asynchronous REST forward using thread pooling to bypass OS fork poisoning."""
        # Use asyncio.to_thread to run the synchronous urllib logic without blocking the main event loop
        return await asyncio.to_thread(self.forward, prompt=prompt, messages=messages, **kwargs)
