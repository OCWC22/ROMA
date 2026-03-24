"""
Method A: Prompt Baseline — fixed strong prompt, single LLM call.
Anchor for all comparisons.
"""

import time
from .base import (
    BaseSolver, LLMClient, OfficeQAQuestion, SolverResult,
    OFFICEQA_SEED_PROMPT, extract_final_answer, score_answer,
)


class PromptBaselineSolver(BaseSolver):
    name = "prompt_baseline"

    def __init__(self, model: str = "claude-haiku-4-5", cli: str = "claude"):
        self.llm = LLMClient(model=model, cli=cli)
        self.prompt = OFFICEQA_SEED_PROMPT

    def solve(self, question: OfficeQAQuestion, context: str = "") -> SolverResult:
        start = time.time()

        user_msg = ""
        if context:
            user_msg = f"DOCUMENT CONTEXT:\n{context[:40000]}\n\n"
        user_msg += f"QUESTION: {question.question}\n\nAnswer with ONLY the value."

        result = self.llm.call(user_msg, system=self.prompt)
        raw_output = result.output if result.success else f"ERROR: {result.error}"
        final = extract_final_answer(raw_output) if result.success else ""

        return SolverResult(
            method=self.name,
            predicted=final,
            expected=question.answer,
            score=score_answer(question.answer, final),
            duration=time.time() - start,
            used_context=bool(context),
            raw_output=raw_output,
            final_answer=final,
            trace={"system_prompt": self.prompt[:200]},
            error=result.error if not result.success else None,
        )
