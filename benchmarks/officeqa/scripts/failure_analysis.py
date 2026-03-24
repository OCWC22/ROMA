"""
Failure taxonomy for OfficeQA benchmark results.

Labels every wrong answer so we know what to optimize next.
"""

import re
from typing import Optional


FAILURE_TYPES = [
    "no_answer",
    "format_violation",
    "wrong_unit_scaling",
    "wrong_fiscal_year_logic",
    "wrong_extraction",
    "wrong_arithmetic",
    "wrong_decomposition",
    "wrong_aggregation",
    "hallucination",
    "close_but_scorer_miss",
    "other",
]


def classify_failure(
    question: str,
    predicted: str,
    expected: str,
    raw_output: str,
    score: float,
) -> Optional[str]:
    """
    Classify why a prediction was wrong. Returns None if correct (score > 0).
    """
    if score > 0:
        return None

    pred = (predicted or "").strip()
    exp = (expected or "").strip()
    raw = (raw_output or "").strip()
    q = question.lower()

    # No answer produced
    if not pred or pred.startswith("ERROR"):
        return "no_answer"

    # Format violation: answer contains full sentences instead of just a value
    if len(pred) > 100 and not any(c.isdigit() for c in pred[:50]):
        return "format_violation"

    # Check for unit scaling errors (off by factor of 1000, 1e6, 1e9)
    try:
        pred_num = _extract_first_number(pred)
        exp_num = _extract_first_number(exp)
        if pred_num is not None and exp_num is not None and exp_num != 0:
            ratio = pred_num / exp_num
            for factor in [1e3, 1e6, 1e9, 1e-3, 1e-6, 1e-9]:
                if 0.9 < ratio / factor < 1.1:
                    return "wrong_unit_scaling"
    except (ValueError, ZeroDivisionError):
        pass

    # Fiscal year reasoning errors
    if re.search(r'\b(fiscal|fy|transition quarter|tq)\b', q, re.IGNORECASE):
        return "wrong_fiscal_year_logic"

    # Arithmetic errors (question asks for sum, difference, mean, etc.)
    if re.search(r'\b(sum|total|add|difference|ratio|geometric mean|average|mean)\b', q, re.IGNORECASE):
        return "wrong_arithmetic"

    # Aggregation errors (multiple values needed)
    if re.search(r'\b(combined|aggregate|altogether|each|all)\b', q, re.IGNORECASE):
        return "wrong_aggregation"

    # Decomposition errors (multi-step reasoning failed)
    if "decompos" in raw.lower() or "subtask" in raw.lower():
        return "wrong_decomposition"

    # Close but scorer missed — predicted contains expected or vice versa partially
    if pred_num is not None and exp_num is not None and exp_num != 0:
        diff = abs(pred_num - exp_num) / abs(exp_num)
        if diff < 0.15:
            return "close_but_scorer_miss"

    # Hallucination: answer has numbers but they don't relate to expected at all
    if pred_num is not None and exp_num is not None:
        return "wrong_extraction"

    # Check for hallucinated text
    if pred and exp and pred.lower() not in exp.lower() and exp.lower() not in pred.lower():
        return "hallucination"

    return "other"


def _extract_first_number(text: str) -> Optional[float]:
    """Extract the first number from text."""
    text = text.replace(',', '')
    match = re.search(r'-?\d+\.?\d*', text)
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


def generate_failure_notes(
    question: str,
    predicted: str,
    expected: str,
    raw_output: str,
    failure_type: str,
) -> str:
    """Generate human-readable notes about why the answer was wrong."""
    notes = []

    if failure_type == "no_answer":
        if "TIMEOUT" in (predicted or ""):
            notes.append("LLM call timed out")
        elif "ERROR" in (predicted or ""):
            notes.append(f"Error: {predicted}")
        else:
            notes.append("No answer produced")

    elif failure_type == "format_violation":
        notes.append("Returned explanation instead of value")

    elif failure_type == "wrong_unit_scaling":
        pred_num = _extract_first_number(predicted)
        exp_num = _extract_first_number(expected)
        if pred_num and exp_num and exp_num != 0:
            ratio = pred_num / exp_num
            notes.append(f"Off by factor ~{ratio:.0f} — likely expanded or collapsed units incorrectly")

    elif failure_type == "wrong_fiscal_year_logic":
        notes.append("Fiscal year convention likely misapplied")

    elif failure_type == "wrong_arithmetic":
        notes.append("Calculation error on sum/difference/mean")

    elif failure_type == "wrong_extraction":
        notes.append("Extracted wrong value from table")

    elif failure_type == "close_but_scorer_miss":
        notes.append("Answer semantically close but formatted wrong for scorer")

    elif failure_type == "hallucination":
        notes.append("Generated plausible but incorrect value")

    if not notes:
        notes.append(f"Expected '{expected}', got '{predicted}'")

    return "; ".join(notes)
