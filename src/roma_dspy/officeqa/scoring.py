"""OfficeQA answer normalization and scoring helpers."""

from __future__ import annotations

import json
import re
from typing import Any


def normalize_text(text: str) -> str:
    if not text:
        return ""
    return text.replace("\u2212", "-")


def extract_numbers_with_context(text: str) -> list:
    if not text:
        return []

    text = normalize_text(text)
    text_no_commas = re.sub(
        r"\d{1,3}(?:,\d{3})+(?:\.\d+)?",
        lambda m: m.group().replace(",", ""),
        text,
    )

    results = []
    for match in re.finditer(r"-?\d+\.?\d*%?", text_no_commas):
        matched_text = match.group()
        if not matched_text or matched_text == "-":
            continue

        has_percent = matched_text.endswith("%")
        num_text = matched_text.rstrip("%")

        try:
            num = float(num_text)
        except ValueError:
            continue

        start = max(0, match.start() - 20)
        end = min(len(text_no_commas), match.end() + 20)
        context = text_no_commas[start:end].lower()
        results.append((num, context, has_percent, num_text.startswith("-")))

    return results


def detect_unit_in_context(context: str):
    ctx = context.lower()
    if re.search(r"\btrillions?\b", ctx):
        return ("trillion", 1e12)
    if re.search(r"\bbillions?\b", ctx):
        return ("billion", 1e9)
    if re.search(r"\bmillions?\b", ctx):
        return ("million", 1e6)
    if re.search(r"\bthousands?\b", ctx):
        return ("thousand", 1e3)
    return (None, 1.0)


def is_likely_year(num: float) -> bool:
    return 1900 <= num <= 2100 and num == int(num)


def has_significant_text(text: str):
    if not text:
        return False, ""

    cleaned = normalize_text(text).lower()
    cleaned = re.sub(r"-?\d+\.?\d*%?", "", cleaned)
    cleaned = re.sub(r"[,]", "", cleaned)
    for unit in [
        "trillion",
        "trillions",
        "billion",
        "billions",
        "million",
        "millions",
        "thousand",
        "thousands",
        "hundred",
        "hundreds",
        "percent",
        "percentage",
        "%",
    ]:
        cleaned = re.sub(r"\b" + unit + r"\b", "", cleaned)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return len(cleaned) >= 2, cleaned


def check_text_overlap(gt_text: str, pred_text: str):
    if not gt_text or not pred_text:
        return False, "Empty text"

    gt_has, gt_cleaned = has_significant_text(gt_text)
    pred_has, pred_cleaned = has_significant_text(pred_text)

    if not gt_has:
        return True, "GT is purely numeric"
    if not pred_has:
        return False, f"GT has text '{gt_cleaned}' but prediction is purely numeric"
    if gt_cleaned in pred_cleaned:
        return True, f"Text match: '{gt_cleaned}'"
    if pred_cleaned in gt_cleaned:
        return True, f"Text match: '{pred_cleaned}'"
    return False, f"Text mismatch: GT='{gt_cleaned}', Pred='{pred_cleaned}'"


def _stringify_answer(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple)):
        try:
            return json.dumps(value, indent=2, default=str)
        except TypeError:
            return str(value)
    return str(value)


def extract_final_answer(text: Any) -> str:
    text = _stringify_answer(text)
    if not text:
        return ""

    match = re.search(
        r"<FINAL_ANSWER>\s*(.*?)\s*</FINAL_ANSWER>",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()

    match = re.search(r"FINAL_ANSWER:\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    match = re.search(r"ANSWER:\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    return text.strip()


def extract_officeqa_answer(text: Any) -> str:
    """Extract the canonical OfficeQA answer from native or wrapped outputs."""
    text = _stringify_answer(text)
    if not text:
        return ""

    match = re.search(
        r"^\s*synthesized_answer:\s*(.+)$",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if match:
        return match.group(1).strip()

    return extract_final_answer(text)


def score_answer(ground_truth: str, predicted: Any, tolerance: float = 0.0) -> float:
    """OfficeQA fuzzy matching. Returns 1.0 if correct, 0.0 otherwise."""
    if not ground_truth or predicted is None:
        return 0.0

    predicted = extract_officeqa_answer(predicted)
    if not predicted:
        return 0.0

    gt_numbers = extract_numbers_with_context(ground_truth)
    pred_numbers = extract_numbers_with_context(predicted)

    gt_nums = [(n, c) for n, c, _, _ in gt_numbers]
    pred_nums = [(n, c) for n, c, _, _ in pred_numbers]

    if gt_nums and pred_nums:
        if len(gt_nums) == 1:
            gt_val, _gt_ctx = gt_nums[0]
            gt_base = gt_val
            gt_has_text, _ = has_significant_text(ground_truth)
            should_filter_years = not (is_likely_year(gt_val) or gt_has_text)

            for pred_val, _pred_ctx in pred_nums:
                if should_filter_years and is_likely_year(pred_val):
                    continue
                pred_base = pred_val

                if gt_base == 0:
                    if pred_base == 0:
                        tm, _ = check_text_overlap(ground_truth, predicted)
                        if tm:
                            return 1.0
                    continue

                diff = abs(gt_base - pred_base) / abs(gt_base)
                if diff <= tolerance:
                    tm, _ = check_text_overlap(ground_truth, predicted)
                    if tm:
                        return 1.0
            return 0.0

        pred_non_years = [
            (n, c)
            for n, c in pred_nums
            if not is_likely_year(n) or any(is_likely_year(g) for g, _ in gt_nums)
        ]
        matched = 0
        for gv, _gc in gt_nums:
            for pv, _pc in pred_non_years:
                if gv == 0 and pv == 0:
                    tm, _ = check_text_overlap(ground_truth, predicted)
                    if tm:
                        matched += 1
                        break
                elif gv != 0 and abs(gv - pv) / abs(gv) <= tolerance:
                    tm, _ = check_text_overlap(ground_truth, predicted)
                    if tm:
                        matched += 1
                        break
        return 1.0 if matched == len(gt_nums) else 0.0

    gt_clean = ground_truth.strip().lower().strip("\"'")
    pred_clean = predicted.strip().lower().strip("\"'")
    gt_clean = re.sub(r"\([^)]*\)", "", gt_clean).strip()
    pred_clean = re.sub(r"\([^)]*\)", "", pred_clean).strip()

    if gt_clean in pred_clean or gt_clean == pred_clean:
        return 1.0

    return 0.0
