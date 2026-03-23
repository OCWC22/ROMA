"""OfficeQA Atomizer — classify questions by complexity and retrieval pattern.

OfficeQA-specific: accounts for multi-bulletin spans, external value needs,
visual reasoning, and fiscal year complexity.
"""

import dspy

ATOMIZER_PROMPT = r"""
# Atomizer — OfficeQA Question Classifier

Role
Classify the question as ATOMIC or NON-ATOMIC. Do not solve it.

OfficeQA Question Taxonomy
- ATOMIC (→ EXECUTE): Single table lookup, one file, one cell. ~38% of questions.
  Examples: "What was total public debt in Jan 1965?" → one file, one row, one column.
- NON-ATOMIC (→ PLAN): Any of these triggers:
  1. Multiple bulletins needed (11% span 3+ bulletins)
  2. Computation required beyond reading a value (62% need analysis)
  3. External values needed (22% — CPI, GDP, interest rates not in Treasury docs)
  4. Visual reasoning needed (3% — charts, graphs in PDFs)
  5. Temporal comparison (comparing values across different months/years)
  6. Fiscal year interpretation (requires Oct-Sep boundary logic)

Decision Rules
- If the question names ONE specific bulletin, ONE table, ONE value → EXECUTE
- If ANY non-atomic trigger above applies → PLAN
- Tie-breaker: if unsure, choose PLAN (it's safer to over-decompose than miss steps)

Strict Output Contract
Return ONLY:
{
  "is_atomic": true|false,
  "node_type": "EXECUTE"|"PLAN"
}
"""

ATOMIZER_DEMOS = [
    dspy.Example(
        goal="What was the total public debt outstanding in January 1965?",
        is_atomic=True,
        node_type="EXECUTE"
    ).with_inputs("goal"),

    dspy.Example(
        goal="Compute the CAGR of total public debt from 1960 to 1970.",
        is_atomic=False,
        node_type="PLAN"
    ).with_inputs("goal"),

    dspy.Example(
        goal="What percentage of total receipts came from individual income taxes in fiscal year 1975?",
        is_atomic=False,
        node_type="PLAN"
    ).with_inputs("goal"),

    dspy.Example(
        goal="What was the average interest rate on Treasury bills in March 1980?",
        is_atomic=True,
        node_type="EXECUTE"
    ).with_inputs("goal"),

    dspy.Example(
        goal="Compare the ratio of public debt to GDP in 1945 vs 2020, adjusting for inflation.",
        is_atomic=False,
        node_type="PLAN"
    ).with_inputs("goal"),
]
