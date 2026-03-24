"""
Method E: DSPy Baseline — structured two-stage program.

Stage 1: Evidence extraction
Stage 2: Final answer generation
"""

import time
from pathlib import Path
from typing import Optional

from .base import (
    BaseSolver, LLMClient, OfficeQAQuestion, SolverResult,
    OFFICEQA_SEED_PROMPT, extract_final_answer, score_answer,
)


EVIDENCE_SYSTEM = """You are an evidence extraction agent for U.S. Treasury Bulletin questions.
Your job is to find and extract ALL relevant evidence from the provided context.

Output format:
EVIDENCE:
- <fact 1>
- <fact 2>
- ...

If no context is provided, use your knowledge of U.S. Treasury data.
Extract exact numbers, table values, dates, and units. Be precise."""

ANSWER_SYSTEM = """You are a final answer agent for U.S. Treasury Bulletin questions.
Given extracted evidence, produce the final answer.

RULES:
1. If a table says "in millions of dollars", report the base number (e.g., 2,602 not 2,602,000,000).
2. Fiscal year conventions:
   - Before FY1977: Jul-Jun
   - FY1977 onward: Oct-Sep
   - Transition Quarter (TQ/1976): Jul 1 - Sep 30, 1976
3. Match the format of the original table.
4. Answer with ONLY the value. No explanation."""


class DSPyBaselineSolver(BaseSolver):
    """Two-stage: evidence extraction -> final answer generation."""
    name = "dspy_baseline"

    def __init__(self, model: str = "claude-haiku-4-5", cli: str = "claude"):
        self.llm = LLMClient(model=model, cli=cli)

    def solve(self, question: OfficeQAQuestion, context: str = "") -> SolverResult:
        start = time.time()
        trace = {"steps": []}

        try:
            # Stage 1: Evidence extraction
            evidence_prompt = f"QUESTION: {question.question}\n\n"
            if context:
                evidence_prompt += f"DOCUMENT CONTEXT:\n{context[:35000]}\n\n"
            evidence_prompt += "Extract all relevant evidence for answering this question."

            evidence_result = self.llm.call(evidence_prompt, system=EVIDENCE_SYSTEM)
            evidence = evidence_result.output if evidence_result.success else ""
            trace["steps"].append({"evidence_extraction": evidence[:500]})

            # Stage 2: Final answer generation
            answer_prompt = (
                f"QUESTION: {question.question}\n\n"
                f"EXTRACTED EVIDENCE:\n{evidence[:5000]}\n\n"
                f"Based on the evidence above, what is the final answer?\n"
                f"Answer with ONLY the value."
            )

            answer_result = self.llm.call(answer_prompt, system=ANSWER_SYSTEM)
            raw_output = answer_result.output if answer_result.success else f"ERROR: {answer_result.error}"
            final = extract_final_answer(raw_output) if answer_result.success else ""

            trace["steps"].append({"answer_generation": raw_output[:300]})
            error = None

            if not answer_result.success:
                error = answer_result.error

        except Exception as e:
            final = ""
            raw_output = f"ERROR: {e}"
            error = str(e)

        return SolverResult(
            method=self.name,
            predicted=final,
            expected=question.answer,
            score=score_answer(question.answer, final),
            duration=time.time() - start,
            used_context=bool(context),
            raw_output=raw_output,
            final_answer=final,
            trace=trace,
            error=error,
        )
