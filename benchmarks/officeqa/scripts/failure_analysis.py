"""
Failure taxonomy for OfficeQA benchmark results.

Labels every wrong answer so we know what to optimize next.
"""

import re
from typing import Optional


FAILURE_TYPES = [
    "timeout",
    "interrupted",
    "solver_error",
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
    *,
    error: Optional[str] = None,
    trace: Optional[dict] = None,
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
    trace = dict(trace or {})
    error_type = trace.get("error_type")

    if error_type == "timeout":
        return "timeout"
    if error_type == "interrupted":
        return "interrupted"
    if error_type == "solver_error" or error:
        return "solver_error"

    # No answer produced
    if not pred or pred.startswith("ERROR"):
        return "no_answer"

    # Format violation: answer contains full sentences instead of just a value
    if len(pred) > 100 and not any(c.isdigit() for c in pred[:50]):
        return "format_violation"

    pred_num = None
    exp_num = None
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
    *,
    error: Optional[str] = None,
    trace: Optional[dict] = None,
) -> str:
    """Generate human-readable notes about why the answer was wrong."""
    notes = []
    trace = dict(trace or {})
    error_stage = trace.get("error_stage")

    if failure_type == "timeout":
        timeout_seconds = trace.get("timeout_seconds")
        if error_stage == "optimization":
            if timeout_seconds:
                notes.append(
                    f"Optimization timed out after {timeout_seconds} seconds; method skipped before evaluation"
                )
            else:
                notes.append("Optimization timed out; method skipped before evaluation")
        elif timeout_seconds:
            notes.append(f"Solve timed out after {timeout_seconds} seconds")
        else:
            notes.append("Solve timed out")

    elif failure_type == "interrupted":
        if error_stage == "optimization":
            notes.append("Benchmark interrupted during optimization before evaluation")
        else:
            notes.append("Benchmark run interrupted during solve")

    elif failure_type == "solver_error":
        worker_exception_type = trace.get("worker_exception_type")
        if error_stage == "optimization" and error:
            notes.append(f"Optimization failed before evaluation: {error}")
        elif worker_exception_type and error:
            notes.append(f"{worker_exception_type}: {error}")
        elif error:
            notes.append(f"Solver error: {error}")
        else:
            notes.append("Solver raised an error")

    elif failure_type == "no_answer":
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
