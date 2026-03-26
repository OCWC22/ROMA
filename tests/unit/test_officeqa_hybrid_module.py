"""Focused tests for the OfficeQA hybrid executor module."""

from __future__ import annotations

import asyncio
import json

import dspy
import pytest

from roma_dspy.config.schemas.agents import AgentConfig
from roma_dspy.config.schemas.base import LLMConfig
from roma_dspy.officeqa.modules import OfficeQARLMExecutor


class DummyPredictor:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def acall(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("No more dummy predictor responses configured")
        return dspy.Prediction(**self.responses.pop(0))


def _build_executor(**agent_config) -> OfficeQARLMExecutor:
    return OfficeQARLMExecutor(
        config=AgentConfig(
            llm=LLMConfig(model="openai/gpt-4o-mini"),
            agent_config=agent_config or {"max_reasoning_steps": 4},
        )
    )


def test_hybrid_executor_uses_tool_loop_and_merges_sources():
    executor = _build_executor(max_reasoning_steps=3)
    tool_calls = []

    async def get_tools():
        def search_file_content(file_path: str, query: str):
            tool_calls.append((file_path, query))
            return json.dumps(
                {
                    "success": True,
                    "file_path": file_path,
                    "query": query,
                    "returned_matches": 1,
                    "total_matches": 1,
                    "matches": [
                        {
                            "line_number": 151,
                            "line": "Total public debt outstanding 317,274",
                        }
                    ],
                }
            )

        return {"search_file_content": search_file_content}

    executor._get_execution_tools = get_tools  # type: ignore[method-assign]
    executor._controller = DummyPredictor(
        [
            {
                "action": "tool",
                "tool_name": "search_file_content",
                "tool_args_json": json.dumps(
                    {
                        "file_path": "transformed/treasury_bulletin_1965_01.txt",
                        "query": "total public debt outstanding",
                    }
                ),
                "draft_output": "",
            },
            {
                "action": "finish",
                "tool_name": "",
                "tool_args_json": "{}",
                "draft_output": "EVIDENCE_CARD:\n  value: 317274",
            },
        ]
    )
    executor._finalizer = DummyPredictor(
        [{"output": "EVIDENCE_CARD:\n  value: 317274", "sources": []}]
    )

    result = asyncio.run(
        executor.aforward("[RETRIEVE_TABLE] Find total public debt outstanding")
    )

    assert "317274" in result.output
    assert result.sources == ["transformed/treasury_bulletin_1965_01.txt"]
    assert tool_calls == [
        (
            "transformed/treasury_bulletin_1965_01.txt",
            "total public debt outstanding",
        )
    ]


def test_hybrid_executor_dedupes_identical_tool_calls():
    executor = _build_executor(max_reasoning_steps=4, dedupe_tool_calls=True)
    call_count = {"count": 0}

    async def get_tools():
        def search_file_content(file_path: str, query: str):
            call_count["count"] += 1
            return json.dumps(
                {
                    "success": True,
                    "file_path": file_path,
                    "query": query,
                    "returned_matches": 1,
                    "total_matches": 1,
                    "matches": [{"line_number": 7, "line": "Receipts 2602"}],
                }
            )

        return {"search_file_content": search_file_content}

    repeated_args = json.dumps(
        {
            "file_path": "transformed/treasury_bulletin_1941_01.txt",
            "query": "receipts",
        }
    )
    executor._get_execution_tools = get_tools  # type: ignore[method-assign]
    executor._controller = DummyPredictor(
        [
            {
                "action": "tool",
                "tool_name": "search_file_content",
                "tool_args_json": repeated_args,
                "draft_output": "",
            },
            {
                "action": "tool",
                "tool_name": "search_file_content",
                "tool_args_json": repeated_args,
                "draft_output": "",
            },
            {
                "action": "finish",
                "tool_name": "",
                "tool_args_json": "{}",
                "draft_output": "EVIDENCE_CARD:\n  value: 2602",
            },
        ]
    )
    executor._finalizer = DummyPredictor(
        [{"output": "EVIDENCE_CARD:\n  value: 2602", "sources": []}]
    )

    result = asyncio.run(executor.aforward("[RETRIEVE_TABLE] Find total receipts"))

    assert "2602" in result.output
    assert call_count["count"] == 1


def test_hybrid_executor_requires_tools_for_retrieval_tasks():
    executor = _build_executor(max_reasoning_steps=2)

    async def get_tools():
        return {}

    executor._get_execution_tools = get_tools  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="requires runtime tools"):
        asyncio.run(executor.aforward("[RETRIEVE_TABLE] Find total receipts"))
