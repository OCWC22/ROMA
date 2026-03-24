"""
Method C: ROMA-lite — decomposition pipeline with verifier.

Pipeline: Atomizer -> Planner -> Executor -> Aggregator -> Verifier
"""

import json
import time
from pathlib import Path
from typing import Optional

from .base import (
    BaseSolver, LLMClient, OfficeQAQuestion, SolverResult,
    OFFICEQA_SEED_PROMPT, extract_final_answer, score_answer,
)


class ROMALiteSolver(BaseSolver):
    name = "roma_lite"

    def __init__(self, model: str = "claude-haiku-4-5", cli: str = "claude"):
        self.llm = LLMClient(model=model, cli=cli)

    def solve(self, question: OfficeQAQuestion, context: str = "") -> SolverResult:
        start = time.time()
        trace = {"steps": []}
        ctx_block = f"\nDOCUMENT CONTEXT:\n{context[:30000]}\n" if context else ""

        try:
            # Step 1: Atomizer — decide if atomic or decompose
            atom_result = self.llm.call(
                f"Decide if this question can be answered directly (ATOMIC) or needs "
                f"decomposition into subtasks (DECOMPOSE).\n\n"
                f"Question: {question.question}\n\n"
                f"Respond with ONLY 'ATOMIC' or 'DECOMPOSE: <subtask1>; <subtask2>; ...'"
            )
            atom_output = atom_result.output
            trace["steps"].append({"atomizer": atom_output[:300]})

            if "DECOMPOSE" in atom_output.upper():
                # Step 2: Parse subtasks
                subtask_text = atom_output.split(":", 1)[-1] if ":" in atom_output else atom_output
                subtasks = [s.strip() for s in subtask_text.split(";") if s.strip()][:4]
                trace["path"] = "decomposed"
                trace["subtasks"] = subtasks

                # Step 3: Execute each subtask
                subtask_results = []
                for st in subtasks:
                    st_result = self.llm.call(
                        f"{ctx_block}\nSubtask: {st}\nAnswer with ONLY the value.",
                        system=OFFICEQA_SEED_PROMPT,
                    )
                    subtask_results.append({"subtask": st, "result": st_result.output})
                trace["steps"].append({"executor": subtask_results})

                # Step 4: Aggregator
                agg_result = self.llm.call(
                    f"Original question: {question.question}\n\n"
                    f"Subtask results:\n{json.dumps(subtask_results, indent=2)}\n\n"
                    f"Synthesize the final answer. Respond with ONLY the answer value."
                )
                raw_answer = agg_result.output
                trace["steps"].append({"aggregator": raw_answer[:300]})
            else:
                # Atomic path: answer directly
                trace["path"] = "atomic"
                exec_result = self.llm.call(
                    f"{ctx_block}\nQuestion: {question.question}\n\nAnswer with ONLY the value.",
                    system=OFFICEQA_SEED_PROMPT,
                )
                raw_answer = exec_result.output
                trace["steps"].append({"executor": raw_answer[:300]})

            # Step 5: Verifier — check units, format, consistency
            pre_verify = extract_final_answer(raw_answer)
            verify_result = self.llm.call(
                f"You are a verification agent. Check this answer for correctness.\n\n"
                f"Question: {question.question}\n"
                f"Proposed answer: {pre_verify}\n\n"
                f"Check:\n"
                f"1. Does the answer directly address the question?\n"
                f"2. Are units correct? (If table says 'in millions', answer should be the base number)\n"
                f"3. Is the format clean? (Just a value, no extra text)\n"
                f"4. If subtasks were used, does the final answer properly combine them?\n\n"
                f"If the answer is correct, respond: VERIFIED: <answer>\n"
                f"If it needs correction, respond: CORRECTED: <fixed_answer>\n"
                f"Respond with ONLY one of those two formats."
            )
            verify_output = verify_result.output
            trace["steps"].append({"verifier": verify_output[:300]})

            # Parse verifier output
            if "CORRECTED:" in verify_output.upper():
                final = verify_output.split(":", 1)[-1].strip()
                trace["verified"] = "corrected"
            elif "VERIFIED:" in verify_output.upper():
                final = verify_output.split(":", 1)[-1].strip()
                trace["verified"] = "confirmed"
            else:
                final = pre_verify
                trace["verified"] = "unparseable"

            final = extract_final_answer(final)
            raw_output = raw_answer
            error = None

        except Exception as e:
            final = ""
            raw_output = f"ERROR: {e}"
            error = str(e)
            trace["path"] = "error"

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
