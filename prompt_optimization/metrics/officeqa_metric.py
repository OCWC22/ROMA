"""Benchmark-accurate OfficeQA metric."""

from __future__ import annotations

from typing import Optional

import dspy

from roma_dspy.officeqa import extract_officeqa_answer, score_answer


class OfficeQAMetric(dspy.Module):
    """Deterministic OfficeQA scorer for DSPy programs."""

    def __init__(self) -> None:
        super().__init__()

    @staticmethod
    def _prediction_text(prediction):
        return (
            getattr(prediction, "result_text", None)
            or getattr(prediction, "text", None)
            or prediction
        )

    def forward(
        self,
        example,
        prediction,
        trace=None,
        pred_name: Optional[str] = None,
        pred_trace: Optional[dict] = None,
    ) -> float:
        gold = example.get("answer") or example.get("gold") or ""
        predicted = extract_officeqa_answer(self._prediction_text(prediction))
        return score_answer(str(gold), predicted)

    async def aforward(
        self,
        example,
        prediction,
        trace=None,
        pred_name: Optional[str] = None,
        pred_trace: Optional[dict] = None,
    ) -> float:
        return self.forward(
            example=example,
            prediction=prediction,
            trace=trace,
            pred_name=pred_name,
            pred_trace=pred_trace,
        )
