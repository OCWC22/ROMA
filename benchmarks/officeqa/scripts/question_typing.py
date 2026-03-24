"""
Heuristic question-type classifier for OfficeQA.

Tags each question so we can report per-type accuracy.
"""

import re


QUESTION_TYPES = [
    "direct_lookup",
    "unit_sensitive_lookup",
    "sum_or_aggregation",
    "difference_or_ratio",
    "geometric_mean",
    "fiscal_year_reasoning",
    "multi_number_matching",
    "other",
]


def classify_question(question_text: str) -> str:
    """Classify an OfficeQA question into one of the standard types."""
    q = question_text.lower()

    if re.search(r'geometric\s+mean', q):
        return "geometric_mean"

    if re.search(r'\b(sum|total|add|combined|aggregate|altogether)\b', q):
        return "sum_or_aggregation"

    if re.search(r'\b(difference|ratio|percent(age)?\s+(change|increase|decrease)|compared\s+to|relative\s+to|minus|subtract)\b', q):
        return "difference_or_ratio"

    if re.search(r'\b(fiscal\s+year|fy\s*\d|transition\s+quarter|TQ)\b', q, re.IGNORECASE):
        return "fiscal_year_reasoning"

    if re.search(r'\b(in\s+millions|in\s+billions|in\s+thousands|millions\s+of\s+dollars)\b', q):
        return "unit_sensitive_lookup"

    # Multiple numbers expected in answer — questions asking for several values
    if re.search(r'\b(list|enumerate|name\s+all|all\s+the|each\s+of)\b', q):
        return "multi_number_matching"

    # Default: if it's a what/how much/when type, it's a direct lookup
    if re.search(r'\b(what\s+(is|was|were|are)|how\s+much|how\s+many|when\s+did|which)\b', q):
        return "direct_lookup"

    return "other"
