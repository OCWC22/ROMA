"""OfficeQA Verifier — scorer-mirror verification.

NOT a generic "think harder" verifier. This mirrors the actual reward.py scoring logic:
- normalize_number_with_units(): keeps base number, strips formatting
- score_answer(): compares normalized numbers at tolerance (default 0.00)
- Year filtering: numbers 1900-2100 stripped from predictions when GT is non-year
- Greedy extraction: scanner finds ALL numbers in response

Key insight: a vague LLM verifier will rationalize wrong numbers.
Use DETERMINISTIC checks first; only call LLM judgment for genuine ambiguity.
"""

import dspy

VERIFIER_PROMPT = r"""
# Verifier — OfficeQA Scorer-Mirror

Role
Validate the candidate answer against the scoring function logic BEFORE submission.
This is a deterministic verification pass, not creative reasoning.

# Scorer Logic (from reward.py)
The scorer does:
1. normalize_number_with_units(answer):
   - Strips $, commas, %, whitespace
   - Converts Unicode minus to hyphen
   - Keeps the BASE NUMBER (does NOT expand "millions" → *1000000)
   - Returns cleaned float/int string
2. Extract ALL numbers from the full response text (greedy scan)
3. Filter out years (1900-2100) from predictions when ground truth is non-year
4. Compare each extracted number to ground truth at tolerance (default 0.00, may be 0.01)
5. For multi-number GT: ALL ground truth numbers must be matched

# Verification Checklist (run ALL, every time)

□ UNIT_EXPANSION: Did the answer expand units?
  - If source says "36,080" with "in millions" header, answer must be 36080, NOT 36080000000
  - Quick test: does the answer have MORE digits than the source value? → likely expanded
  - FAIL if digit count of answer >> digit count of source raw value

□ CORRECT_CELL: Was the right cell extracted?
  - Does the row label EXACTLY match what the question asks?
  - Does the column label EXACTLY match the date/period the question asks?
  - Watch: "Total" vs "Subtotal", "Gross" vs "Net", "Outstanding" vs "Issued"

□ CORRECT_FILE: Was the right bulletin used?
  - Does the year/month in the filename match the question?
  - If fiscal year: was the correct FY boundary applied?

□ FISCAL_CALENDAR: Fiscal year correctly interpreted?
  - Before 1977: FY = Jul 1 – Jun 30 (FY1975 = Jul 1974 – Jun 1975)
  - After 1977: FY = Oct 1 – Sep 30 (FY1978 = Oct 1977 – Sep 1978)
  - Transition quarter (TQ): Jul 1 – Sep 30, 1976

□ FORMAT: Is the answer in scorer-compatible format?
  - No commas (37921314 not 37,921,314)
  - No dollar signs
  - No percent signs (3.524 not 3.524%)
  - Correct sign (negatives as hyphen-minus)
  - Source precision preserved

□ COMPLETENESS: For multi-number answers, are ALL required numbers present?
  - Count how many distinct values the question asks for
  - Count how many you're providing
  - All GT numbers must appear somewhere in the response

□ MAGNITUDE: Does the number make sense for its era and category?
  - Cross-check against era-specific ranges
  - If off by 1000x, you probably expanded/compressed units

# Verdict
- If ALL checks PASS → verdict: true, output the answer
- If ANY check FAILS → verdict: false, specify which check failed and what to fix
  - Allow ONE targeted retry on the failing step only
  - After retry, re-verify. If still failing, output best available answer with low confidence.

# Output Contract
{
  "verdict": true|false,
  "feedback": "<specific failure description and fix instruction, or 'All checks passed'>"
}
"""

VERIFIER_DEMOS = [
    # Demo 1: PASS — correct base number
    dspy.Example(
        goal="What was the total public debt outstanding in January 1965?",
        candidate_output="317274",
        verdict=True,
        feedback="All checks passed. Value 317274 matches source (317,274 in millions), base number preserved, correct file (1965_01), correct row (Total public debt outstanding)."
    ).with_inputs("goal", "candidate_output"),

    # Demo 2: FAIL — unit expansion
    dspy.Example(
        goal="What was the total public debt outstanding in January 1965?",
        candidate_output="317274000000",
        verdict=False,
        feedback="UNIT_EXPANSION FAIL: Answer has 12 digits but source value has 6 digits (317,274). The table header says 'in millions' — the number is ALREADY in millions. Correct answer: 317274. Fix: remove the ×1000000 expansion."
    ).with_inputs("goal", "candidate_output"),

    # Demo 3: FAIL — wrong cell
    dspy.Example(
        goal="What was the total public debt outstanding in January 1965?",
        candidate_output="256843",
        verdict=False,
        feedback="CORRECT_CELL FAIL: 256843 appears to be 'Debt held by the public' rather than 'Total public debt outstanding'. The question asks for TOTAL. Fix: re-read the table and extract the 'Total public debt outstanding' row."
    ).with_inputs("goal", "candidate_output"),

    # Demo 4: FAIL — fiscal year confusion
    dspy.Example(
        goal="What were total federal receipts in fiscal year 1975?",
        candidate_output="279090",
        verdict=False,
        feedback="FISCAL_CALENDAR FAIL: 279090 appears to be calendar year 1975 total. FY1975 (pre-1977 rule) = Jul 1974 – Jun 1975, which gives a different total. Fix: look for the FY1975 row or sum Jul 1974 through Jun 1975."
    ).with_inputs("goal", "candidate_output"),
]
