"""
Method B: GEPA Prompt-Optimized — evolve only the system prompt via gepa.optimize().

Isolates what prompt optimization buys you, without confounding agent architecture.
"""

import json
import time
from pathlib import Path
from typing import List, Optional

from .base import (
    BaseSolver, LLMClient, OfficeQAQuestion, SolverResult,
    OFFICEQA_SEED_PROMPT, extract_final_answer, load_source_documents,
    resolve_litellm_model, score_answer,
)

# Import GEPA
try:
    from gepa import optimize as gepa_optimize, EvaluationBatch
    GEPA_AVAILABLE = True
except ImportError:
    GEPA_AVAILABLE = False


class GEPAPromptSolver(BaseSolver):
    """
    Optimizes {"system": prompt} using gepa.optimize() on train set.
    Candidate selection uses val set. Final evaluation on test only.
    """
    name = "gepa_prompt"

    def __init__(
        self,
        model: str = "claude-haiku-4-5",
        cli: str = "claude",
        corpus_dir: Optional[Path] = None,
    ):
        self.model = model
        self.llm = LLMClient(model=model, cli=cli)
        self.corpus_dir = corpus_dir
        self.prompt = OFFICEQA_SEED_PROMPT
        self.seed_prompt = OFFICEQA_SEED_PROMPT
        self.optimized = False
        self.optimization_trace = []

    def optimize(
        self,
        trainset: List[OfficeQAQuestion],
        valset: List[OfficeQAQuestion],
        max_metric_calls: int = 30,
    ):
        """
        Run GEPA evolutionary optimization.
        Train: used for reflective updates.
        Val: used for candidate selection / Pareto tracking.
        """
        if not GEPA_AVAILABLE:
            print("  GEPA not installed. Skipping optimization.")
            return

        adapter = self._build_adapter()

        print(f"  GEPA optimize: train={len(trainset)}, val={len(valset)}, budget={max_metric_calls}")
        print(f"  reflection_lm: {resolve_litellm_model(self.model)}")

        result = gepa_optimize(
            seed_candidate={"system": self.prompt},
            trainset=trainset,
            valset=valset,
            adapter=adapter,
            reflection_lm=resolve_litellm_model(self.model),
            max_metric_calls=max_metric_calls,
            candidate_selection_strategy="pareto",
            reflection_minibatch_size=3,
        )

        if result and result.best_candidate:
            self.prompt = result.best_candidate.get("system", self.prompt)
            self.optimized = True
            best_score = result.val_aggregate_scores[result.best_idx]
            self.optimization_trace = {
                "num_candidates": result.num_candidates,
                "best_idx": result.best_idx,
                "best_val_score": best_score,
                "all_val_scores": result.val_aggregate_scores,
                "total_metric_calls": result.total_metric_calls,
            }
            print(f"  GEPA optimization complete. Best val score: {best_score:.3f}")
            print(f"  Candidates explored: {result.num_candidates}")
        else:
            print("  GEPA optimization did not improve prompt. Using seed.")

    def _build_adapter(self):
        """Build a GEPAAdapter for OfficeQA prompt optimization."""
        outer = self

        class OfficeQAPromptAdapter:
            """
            GEPAAdapter implementation for OfficeQA.
            evaluate() runs the candidate prompt on a batch.
            make_reflective_dataset() builds rich reflection data.
            """

            def evaluate(self, batch, candidate, capture_traces=False):
                scores = []
                outputs = []
                trajectories = [] if capture_traces else None

                for q in batch:
                    context = load_source_documents(q.source_files, outer.corpus_dir)
                    user_msg = ""
                    if context:
                        user_msg = f"DOCUMENT CONTEXT:\n{context[:30000]}\n\n"
                    user_msg += f"QUESTION: {q.question}\n\nAnswer with ONLY the value."

                    result = outer.llm.call(user_msg, system=candidate["system"])
                    raw = result.output if result.success else f"ERROR: {result.error}"
                    final = extract_final_answer(raw) if result.success else ""
                    sc = score_answer(q.answer, final)

                    scores.append(sc)
                    outputs.append({"predicted": final, "expected": q.answer})

                    if capture_traces:
                        # Import here to avoid circular dep at module level
                        from benchmarks.officeqa.scripts.question_typing import classify_question
                        from benchmarks.officeqa.scripts.failure_analysis import classify_failure, generate_failure_notes

                        q_type = classify_question(q.question)
                        f_type = classify_failure(q.question, final, q.answer, raw, sc)
                        notes = generate_failure_notes(q.question, final, q.answer, raw, f_type) if f_type else "Correct"

                        trajectories.append({
                            "question": q.question,
                            "expected": q.answer,
                            "predicted": final,
                            "raw_output": raw[:2000],
                            "score": sc,
                            "question_type": q_type,
                            "failure_type": f_type,
                            "context_available": bool(context),
                            "notes": notes,
                        })

                return EvaluationBatch(
                    outputs=outputs,
                    scores=scores,
                    trajectories=trajectories,
                )

            def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
                """
                Build structured reflection data following GEPA's recommended schema:
                Inputs / Generated Outputs / Feedback
                """
                dataset = {}
                if not eval_batch.trajectories:
                    return dataset

                for comp in components_to_update:
                    items = []
                    for traj in eval_batch.trajectories:
                        items.append({
                            "Inputs": {
                                "question": traj["question"],
                                "context_available": traj["context_available"],
                                "question_type": traj["question_type"],
                            },
                            "Generated Outputs": {
                                "raw_output": traj["raw_output"][:500],
                                "final_answer": traj["predicted"],
                            },
                            "Feedback": {
                                "expected_answer": traj["expected"],
                                "score": traj["score"],
                                "failure_type": traj["failure_type"],
                                "notes": traj["notes"],
                            },
                        })
                    dataset[comp] = items

                return dataset

        return OfficeQAPromptAdapter()

    def solve(self, question: OfficeQAQuestion, context: str = "") -> SolverResult:
        """Solve using the (possibly optimized) prompt."""
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
            trace={
                "optimized": self.optimized,
                "prompt_length": len(self.prompt),
            },
            error=result.error if not result.success else None,
        )

    def save_prompts(self, output_dir: Path):
        """Save seed and optimized prompts for reproducibility."""
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "officeqa_seed_prompt.txt").write_text(self.seed_prompt)
        (output_dir / "officeqa_gepa_best_prompt.txt").write_text(self.prompt)
        if self.optimization_trace:
            with open(output_dir / "gepa_optimization_trace.json", "w") as f:
                json.dump(self.optimization_trace, f, indent=2, default=str)
