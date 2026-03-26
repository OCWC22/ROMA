"""OfficeQA-specific custom DSPy modules."""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from typing import Any, Optional

import dspy

from roma_dspy.core.modules.executor import Executor


CONTROLLER_INSTRUCTIONS = """
You are the controller for an OfficeQA executor node.

Decide the next best action using short, incremental steps.

Rules:
- Do NOT ask to read an entire Treasury bulletin when search tools are available.
- Prefer this pattern for document retrieval:
  1. search_files or list_files to identify likely files
  2. search_file_content to locate exact rows/headers
  3. read_file_lines around the returned line numbers
- Use calculator tools only for explicit arithmetic.
- Reuse prior observations; do not repeat identical tool calls unless the args change.
- Finish as soon as you have enough evidence for the final evidence card / answer.

Output:
- action: "tool" or "finish"
- tool_name: required when action="tool"
- tool_args_json: a JSON object string for the tool call, or "{}"
- draft_output: required when action="finish"
""".strip()


class OfficeQARLMControllerSignature(dspy.Signature):
    """Choose the next tool call or finish the current OfficeQA task."""

    goal: str = dspy.InputField(description="Current executor goal")
    context: str = dspy.InputField(description="Condensed dependency context")
    tool_catalog: str = dspy.InputField(description="Available tool descriptions")
    history: str = dspy.InputField(description="Recent reasoning history and observations")
    action: str = dspy.OutputField(description="Either 'tool' or 'finish'")
    tool_name: str = dspy.OutputField(description="Tool name when action='tool'")
    tool_args_json: str = dspy.OutputField(
        description='JSON object string of tool kwargs, e.g. {"file_path":"..."}'
    )
    draft_output: str = dspy.OutputField(
        description="Best current evidence-card/final answer when action='finish'"
    )


@dataclass
class _Observation:
    summary: str
    raw_text: str
    sources: set[str]


class OfficeQARLMExecutor(Executor):
    """OfficeQA executor with an internal recursive tool loop."""

    def __init__(self, *args, signature: Any = None, config: Optional[Any] = None, **kwargs):
        super().__init__(*args, signature=signature, config=config, **kwargs)
        agent_cfg = self.agent_config
        max_executions = int(agent_cfg.get("max_executions", 6) or 6)
        self._max_reasoning_steps = int(
            agent_cfg.get("max_reasoning_steps", max(3, max_executions))
        )
        self._max_observation_chars = int(
            agent_cfg.get("max_observation_chars", 1200) or 1200
        )
        self._max_history_items = int(agent_cfg.get("max_history_items", 6) or 6)
        self._dedupe_tool_calls = bool(agent_cfg.get("dedupe_tool_calls", True))

        controller_signature = type(
            "OfficeQARLMControllerSignatureInstance",
            (OfficeQARLMControllerSignature,),
            {"__module__": OfficeQARLMControllerSignature.__module__, "__doc__": CONTROLLER_INSTRUCTIONS},
        )
        self._controller = dspy.Predict(controller_signature)
        self._finalizer = dspy.Predict(self.signature)

    def named_predictors(self):
        return [
            ("controller", self._controller),
            ("finalizer", self._finalizer),
        ]

    def forward(
        self,
        goal: str,
        *,
        context: Optional[str] = None,
        tools=None,
        demos=None,
        config: Optional[dict[str, Any]] = None,
        dspy_context: Optional[dict[str, Any]] = None,
        call_params: Optional[dict[str, Any]] = None,
        **call_kwargs: Any,
    ):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            raise RuntimeError(
                "OfficeQARLMExecutor.forward() cannot be used from an active event loop; use aforward()."
            )
        return asyncio.run(
            self.aforward(
                goal,
                context=context,
                tools=tools,
                demos=demos,
                config=config,
                dspy_context=dspy_context,
                call_params=call_params,
                **call_kwargs,
            )
        )

    async def aforward(
        self,
        goal: str,
        *,
        context: Optional[str] = None,
        tools=None,
        demos=None,
        config: Optional[dict[str, Any]] = None,
        dspy_context: Optional[dict[str, Any]] = None,
        call_params: Optional[dict[str, Any]] = None,
        **call_kwargs: Any,
    ):
        execution_tools = await self._get_execution_tools()
        runtime_tools = self._merge_tools(execution_tools, tools)
        merged_demos = self._prepare_demos(demos)
        ctx = self._build_dspy_context(dspy_context)

        context_summary = self._truncate_text(context or "", self._max_observation_chars)
        if self._goal_requires_tools(goal) and not runtime_tools:
            raise RuntimeError("OfficeQA retrieval task requires runtime tools, but none were available.")

        history: list[dict[str, Any]] = []
        tool_cache: dict[str, _Observation] = {}
        sources: set[str] = set()
        draft_output = ""

        with dspy.context(**ctx):
            for step_index in range(self._max_reasoning_steps):
                controller_result = await self._invoke_predictor_async(
                    self._controller,
                    goal=goal,
                    context=context_summary,
                    tool_catalog=self._build_tool_catalog(runtime_tools),
                    history=self._format_history(history),
                    config=config,
                )
                try:
                    action = self._normalize_action(controller_result)
                except Exception as exc:  # noqa: BLE001
                    history.append(
                        {
                            "step": step_index + 1,
                            "action": "controller_parse_error",
                            "observation": self._truncate_text(str(exc), self._max_observation_chars),
                        }
                    )
                    continue

                if action["action"] == "finish":
                    draft_output = action["draft_output"]
                    history.append(
                        {
                            "step": step_index + 1,
                            "action": "finish",
                            "draft_output": self._truncate_text(draft_output, self._max_observation_chars),
                        }
                    )
                    break

                tool_name = action["tool_name"]
                if tool_name not in runtime_tools:
                    history.append(
                        {
                            "step": step_index + 1,
                            "action": "tool_error",
                            "tool_name": tool_name,
                            "observation": f"Unknown tool '{tool_name}'. Available tools: {', '.join(sorted(runtime_tools))}",
                        }
                    )
                    continue

                cache_key = self._build_tool_cache_key(tool_name, action["tool_args"])
                observation = tool_cache.get(cache_key) if self._dedupe_tool_calls else None
                if observation is None:
                    observation = await self._execute_tool(
                        runtime_tools[tool_name],
                        tool_name=tool_name,
                        tool_args=action["tool_args"],
                    )
                    if self._dedupe_tool_calls:
                        tool_cache[cache_key] = observation

                sources.update(observation.sources)
                history.append(
                    {
                        "step": step_index + 1,
                        "action": "tool",
                        "tool_name": tool_name,
                        "tool_args": action["tool_args"],
                        "observation": observation.summary,
                    }
                )

        final_prediction = await self._finalize_output(
            goal=goal,
            context=context or "",
            history=history,
            sources=sources,
            draft_output=draft_output,
            demos=merged_demos,
            config=config,
            call_params=call_params,
            **call_kwargs,
        )
        return final_prediction

    def _build_dspy_context(
        self, dspy_context: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        ctx = dict(getattr(self, "_context_defaults", {}))
        if dspy_context:
            ctx.update(dspy_context)
        ctx.setdefault("lm", self._lm)
        if getattr(self, "_adapter", None) is not None:
            ctx["adapter"] = self._adapter
        return ctx

    @staticmethod
    def _goal_requires_tools(goal: str) -> bool:
        normalized = (goal or "").strip().upper()
        return normalized.startswith("[RETRIEVE")

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return f"{text[:max_chars]}…"

    def _build_tool_catalog(self, runtime_tools: dict[str, Any]) -> str:
        lines = []
        for name, tool in sorted(runtime_tools.items()):
            callable_obj = getattr(tool, "func", tool)
            try:
                signature = str(inspect.signature(callable_obj))
            except (TypeError, ValueError):
                signature = "(...)"
            doc = inspect.getdoc(callable_obj) or "No description provided."
            lines.append(f"- {name}{signature}: {doc.splitlines()[0]}")
        return "\n".join(lines) if lines else "No tools available."

    def _format_history(self, history: list[dict[str, Any]]) -> str:
        if not history:
            return "No prior actions."
        formatted = []
        for item in history[-self._max_history_items :]:
            if item["action"] == "tool":
                formatted.append(
                    f"Step {item['step']}: TOOL {item['tool_name']} args={json.dumps(item['tool_args'], sort_keys=True)}\n"
                    f"Observation: {item['observation']}"
                )
            elif item["action"] == "finish":
                formatted.append(
                    f"Step {item['step']}: FINISH draft={item['draft_output']}"
                )
            else:
                formatted.append(
                    f"Step {item['step']}: {item['action']} {item.get('observation', '')}"
                )
        return "\n\n".join(formatted)

    def _normalize_action(self, controller_result: Any) -> dict[str, Any]:
        action = str(getattr(controller_result, "action", "") or "").strip().lower()
        tool_name = str(getattr(controller_result, "tool_name", "") or "").strip()
        draft_output = str(getattr(controller_result, "draft_output", "") or "").strip()
        raw_args = getattr(controller_result, "tool_args_json", "{}")
        tool_args = self._parse_tool_args(raw_args)

        if action not in {"tool", "finish"}:
            if draft_output:
                action = "finish"
            elif tool_name:
                action = "tool"
            else:
                raise RuntimeError(f"Controller returned invalid action: {action or '<empty>'}")

        if action == "tool" and not tool_name:
            raise RuntimeError("Controller chose tool action without a tool_name.")
        if action == "finish" and not draft_output:
            raise RuntimeError("Controller chose finish action without draft_output.")

        return {
            "action": action,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "draft_output": draft_output,
        }

    @staticmethod
    def _parse_tool_args(raw_args: Any) -> dict[str, Any]:
        if raw_args in (None, "", {}):
            return {}
        if isinstance(raw_args, dict):
            return raw_args
        try:
            parsed = json.loads(str(raw_args))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Controller returned invalid tool_args_json: {raw_args}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("Controller tool_args_json must decode to a JSON object.")
        return parsed

    @staticmethod
    def _build_tool_cache_key(tool_name: str, tool_args: dict[str, Any]) -> str:
        return f"{tool_name}:{json.dumps(tool_args, sort_keys=True, default=str)}"

    async def _execute_tool(
        self,
        tool: Any,
        *,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> _Observation:
        callable_obj = getattr(tool, "func", tool)
        try:
            if inspect.iscoroutinefunction(callable_obj):
                raw_output = await callable_obj(**tool_args)
            else:
                raw_output = await asyncio.to_thread(callable_obj, **tool_args)
        except Exception as exc:  # noqa: BLE001
            raw_output = json.dumps(
                {"success": False, "error": f"{tool_name} failed: {exc}"}
            )

        raw_text = self._coerce_raw_output(raw_output)
        parsed = self._maybe_parse_json(raw_text)
        return _Observation(
            summary=self._summarize_observation(parsed, raw_text),
            raw_text=raw_text,
            sources=self._collect_sources(parsed),
        )

    @staticmethod
    def _coerce_raw_output(raw_output: Any) -> str:
        if raw_output is None:
            return ""
        if isinstance(raw_output, str):
            return raw_output
        try:
            return json.dumps(raw_output, default=str)
        except TypeError:
            return str(raw_output)

    @staticmethod
    def _maybe_parse_json(raw_text: str) -> Any:
        try:
            return json.loads(raw_text)
        except Exception:  # noqa: BLE001
            return raw_text

    def _summarize_observation(self, parsed: Any, raw_text: str) -> str:
        if isinstance(parsed, dict):
            if parsed.get("success") is False:
                return self._truncate_text(
                    f"Tool error: {parsed.get('error', 'unknown error')}",
                    self._max_observation_chars,
                )
            if "matches" in parsed:
                snippets = []
                for match in (parsed.get("matches") or [])[:3]:
                    line_number = match.get("line_number")
                    line_text = match.get("line") or match.get("content") or ""
                    snippets.append(f"L{line_number}: {line_text}")
                prefix = (
                    f"query={parsed.get('query')} returned={parsed.get('returned_matches', 0)} "
                    f"total={parsed.get('total_matches', parsed.get('count', 0))}"
                )
                body = "\n".join(snippets)
                return self._truncate_text(
                    f"{prefix}\n{body}".strip(),
                    self._max_observation_chars,
                )
            if "content" in parsed:
                location = parsed.get("file_path") or parsed.get("path") or ""
                start = parsed.get("start_line")
                end = parsed.get("end_line")
                prefix = f"{location} lines {start}-{end}" if start and end else str(location)
                return self._truncate_text(
                    f"{prefix}\n{parsed.get('content', '')}".strip(),
                    self._max_observation_chars,
                )
            if "items" in parsed:
                items = parsed.get("items") or []
                rendered = ", ".join(item.get("name", "") for item in items[:8] if isinstance(item, dict))
                return self._truncate_text(rendered or raw_text, self._max_observation_chars)
        return self._truncate_text(raw_text, self._max_observation_chars)

    def _collect_sources(self, parsed: Any) -> set[str]:
        sources: set[str] = set()

        def _walk(value: Any) -> None:
            if isinstance(value, dict):
                for key, nested in value.items():
                    if key in {"file_path", "path", "source_file"} and isinstance(nested, str):
                        sources.add(nested)
                    else:
                        _walk(nested)
            elif isinstance(value, list):
                for item in value:
                    _walk(item)

        _walk(parsed)
        return sources

    async def _finalize_output(
        self,
        *,
        goal: str,
        context: str,
        history: list[dict[str, Any]],
        sources: set[str],
        draft_output: str,
        demos,
        config: Optional[dict[str, Any]] = None,
        call_params: Optional[dict[str, Any]] = None,
        **call_kwargs: Any,
    ) -> dspy.Prediction:
        final_context_parts = []
        if context:
            final_context_parts.append(f"DEPENDENCY CONTEXT:\n{context}")
        if history:
            final_context_parts.append(f"RLM TOOL HISTORY:\n{self._format_history(history)}")
        if draft_output:
            final_context_parts.append(f"DRAFT FINAL OUTPUT:\n{draft_output}")
        final_context = "\n\n".join(final_context_parts)

        finalizer_kwargs = dict(call_params or {})
        finalizer_kwargs.update(call_kwargs)
        if config is not None:
            finalizer_kwargs["config"] = config
        if demos:
            finalizer_kwargs["demos"] = demos
        if final_context:
            finalizer_kwargs["context"] = final_context

        result = await self._invoke_predictor_async(
            self._finalizer,
            goal=goal,
            **finalizer_kwargs,
        )

        output = str(getattr(result, "output", "") or "").strip()
        if not output and draft_output:
            output = draft_output
        if not output:
            raise RuntimeError("OfficeQARLMExecutor finalizer produced no output.")

        result_sources = {
            source
            for source in (getattr(result, "sources", None) or [])
            if isinstance(source, str) and source
        }
        result_sources.update(sources)

        return dspy.Prediction(
            output=output,
            sources=sorted(result_sources),
            rlm_steps=len(history),
            controller_trace=self._format_history(history),
        )

    async def _invoke_predictor_async(self, predictor: Any, **kwargs: Any):
        method_for_filter = getattr(predictor, "aforward", None) or getattr(
            predictor, "forward", None
        )
        filtered = self._filter_kwargs(method_for_filter, kwargs)
        acall = getattr(predictor, "acall", None)
        if acall is not None and self._predictor_supports_async(predictor):
            return await predictor.acall(**filtered)
        return await asyncio.to_thread(predictor, **filtered)
