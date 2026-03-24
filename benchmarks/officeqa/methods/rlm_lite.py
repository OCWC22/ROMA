"""
Method D: RLM-lite — explicit recursive reasoning pipeline.

Pipeline: Root Analyze -> Identify Gaps -> Targeted Subqueries -> Synthesize -> Verify Format
"""

import re
import time
from pathlib import Path
from typing import Optional

from .base import (
    BaseSolver, LLMClient, OfficeQAQuestion, SolverResult,
    OFFICEQA_SEED_PROMPT, extract_final_answer, score_answer,
)


RLM_SYSTEM = """You are an RLM (Recursive Language Model) solving Treasury Bulletin questions.
Think step by step. ALWAYS provide a numerical or factual answer. Never refuse.

RULES:
- If a table header says 'in millions', report the BASE number (e.g., 2602, NOT 2602000000)
- Fiscal years before 1977: Jul-Jun; FY1977 onward: Oct-Sep
- Transition Quarter (TQ/1976): Jul 1 - Sep 30, 1976
- ALWAYS provide your best answer."""


class RLMLiteSolver(BaseSolver):
    name = "rlm_lite"

    def __init__(self, model: str = "claude-haiku-4-5", cli: str = "claude"):
        self.llm = LLMClient(model=model, cli=cli)

    def solve(self, question: OfficeQAQuestion, context: str = "") -> SolverResult:
        start = time.time()
        trace = {"steps": [], "depth": 0}
        ctx_block = f"\nDOCUMENT CONTEXT:\n{context[:30000]}\n" if context else ""

        try:
            # Step 1: Root Analyze — understand the question and plan
            root_result = self.llm.call(
                f"{ctx_block}\n"
                f"QUESTION: {question.question}\n\n"
                f"Analyze this question. Identify:\n"
                f"1. What specific data points are needed?\n"
                f"2. What are you confident about?\n"
                f"3. What gaps remain that need targeted search?\n\n"
                f"Format:\n"
                f"KNOWN: <what you can answer directly>\n"
                f"GAPS: <gap1>; <gap2>; ... (or NONE if you can answer directly)\n"
                f"PRELIMINARY_ANSWER: <your best answer so far, or INCOMPLETE>",
                system=RLM_SYSTEM,
            )
            root_output = root_result.output
            trace["steps"].append({"root_analyze": root_output[:500]})

            # Step 2: Identify gaps and decide if subqueries are needed
            has_gaps = "GAPS:" in root_output.upper() and "NONE" not in root_output.upper().split("GAPS:")[-1].split("\n")[0]

            # Extract preliminary answer
            prelim_match = re.search(r'PRELIMINARY_ANSWER:\s*(.+?)(?:\n|$)', root_output, re.IGNORECASE)
            prelim = prelim_match.group(1).strip() if prelim_match else ""

            if has_gaps and "INCOMPLETE" in prelim.upper():
                # Step 3: Targeted subqueries for each gap
                gaps_text = root_output.upper().split("GAPS:")[-1].split("\n")[0]
                gaps = [g.strip() for g in gaps_text.split(";") if g.strip() and g.strip() != "NONE"][:3]
                trace["gaps"] = gaps
                trace["depth"] = len(gaps)

                subquery_results = []
                for gap in gaps:
                    sq_result = self.llm.call(
                        f"{ctx_block}\n"
                        f"Original question: {question.question}\n"
                        f"Specific information needed: {gap}\n\n"
                        f"Search the document context carefully for this specific information.\n"
                        f"Return ONLY the relevant data point or value.",
                        system=RLM_SYSTEM,
                    )
                    subquery_results.append({"gap": gap, "result": sq_result.output[:500]})
                trace["steps"].append({"subqueries": subquery_results})

                # Step 4: Synthesize — combine root analysis with subquery results
                synth_result = self.llm.call(
                    f"Original question: {question.question}\n\n"
                    f"Root analysis:\n{root_output[:1500]}\n\n"
                    f"Targeted search results:\n"
                    + "\n".join(f"- {sr['gap']}: {sr['result'][:300]}" for sr in subquery_results)
                    + f"\n\nSynthesize the final answer from all gathered information.\n"
                    f"Return ONLY the answer value.",
                    system=RLM_SYSTEM,
                )
                raw_answer = synth_result.output
                trace["steps"].append({"synthesis": raw_answer[:300]})
            else:
                # Direct answer from root analysis
                trace["depth"] = 0
                if prelim and "INCOMPLETE" not in prelim.upper():
                    raw_answer = prelim
                else:
                    # Fallback: direct answer call
                    direct_result = self.llm.call(
                        f"{ctx_block}\n"
                        f"QUESTION: {question.question}\n\n"
                        f"Answer with ONLY the value.",
                        system=RLM_SYSTEM,
                    )
                    raw_answer = direct_result.output
                trace["steps"].append({"direct_answer": raw_answer[:300]})

            # Step 5: Verify format — ensure clean output
            final = extract_final_answer(raw_answer)

            # Quick format check: if answer is too long, extract just the value
            if len(final) > 100:
                format_result = self.llm.call(
                    f"Extract ONLY the final answer value from this text:\n{final[:500]}\n\n"
                    f"Return ONLY the value, nothing else.",
                )
                final = format_result.output.strip()
                trace["steps"].append({"format_verify": final[:100]})

            raw_output = raw_answer
            error = None

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
