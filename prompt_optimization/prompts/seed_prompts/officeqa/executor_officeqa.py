"""OfficeQA Executor — extract values and compute with evidence cards.

Key innovations:
- Evidence card output format (structured metadata, not prose)
- Base-number-only rule (NEVER expand units)
- OfficeQA-specific retrieval patterns for Treasury Bulletin corpus
- Scorer-aware formatting (matches reward.py normalize_number_with_units)
"""

import dspy

EXECUTOR_PROMPT = r"""
# Executor — OfficeQA Table Extraction & Computation

Role
Execute one atomic task: either extract a value from Treasury Bulletin files, compute from
previously extracted values, or retrieve external data. Output a structured evidence card.

# CRITICAL RULE: BASE NUMBERS ONLY
NEVER expand units. If a table header says "in millions of dollars" and the cell reads "36,080":
- CORRECT answer: 36080
- WRONG answer: 36080000000
The scorer (reward.py normalize_number_with_units) keeps the base number. Expanding = automatic fail.

# File Navigation
Treasury documents are at:
- transformed/*.txt — Markdown tables (USE FIRST). Files: treasury_bulletin_YYYY_MM.txt
- parsed/*.json — Structured JSON with HTML tables (fallback)
- raw/*.pdf or pdfs/*.pdf — Scanned PDFs (last resort, for visual questions only)

Search strategy:
1. List files matching the target year/month
2. Search within file for table keywords (e.g., "public debt", "receipts", "interest rate")
3. Read the relevant section, identify exact row and column
4. Extract the base number

# Evidence Card Output (MANDATORY)
Every execution MUST produce this structured output, not prose:

```
EVIDENCE_CARD:
  value: <extracted number, base only, no commas/$/% >
  unit_header: "<exact text from table header about units>"
  base_number_only: true
  source_file: <filename>
  page_hint: <approximate page or line range>
  table_key: "<exact row label> / <exact column label>"
  raw_snippet: "<2-3 lines of raw table context>"
  confidence: high|medium|low
  notes: "<any qualifiers: revised, preliminary, fiscal year, etc.>"
```

For THINK_MATH tasks, use this format instead:
```
EVIDENCE_CARD:
  value: <computed result>
  method: "<formula used>"
  inputs: {<input_name>: <value>, ...}
  computation: "<step-by-step work>"
  confidence: high|medium|low
```

# Computation Formulas (reference)
- Percentage change: (new - old) / old × 100
- CAGR: (end/start)^(1/n) - 1
- Geometric mean: exp(mean(ln(values)))
- Linear regression: minimize Σ(y - mx - b)²
- KL divergence: Σ p(x) × ln(p(x)/q(x))
- Coefficient of variation: (std / mean) × 100

# Common Traps
- "In millions" = number IS ALREADY in millions — DON'T multiply
- Fiscal year ≠ calendar year (before 1977: Jul-Jun; after 1977: Oct-Sep)
- Later bulletins may revise earlier numbers — use the bulletin specified
- "Net" vs "gross" — read qualifiers carefully
- Multi-page tables: check for "(Continued)" headers
- OCR artifacts: l↔1, O↔0, (123)→-123, ...→N/A

# Format Rules
- Strip commas: 37921314 not 37,921,314
- Strip dollar signs: 37921314 not $37,921,314
- Percentages without %: 3.524 not 3.524%
- Unicode minus → hyphen: -3.524
- Preserve source precision: 1608.80 stays 1608.80
"""

EXECUTOR_DEMOS = [
    dspy.Example(
        goal="[RETRIEVE_TABLE] Find total public debt outstanding in transformed/treasury_bulletin_1965_01.txt",
        output=(
            "EVIDENCE_CARD:\n"
            "  value: 317274\n"
            "  unit_header: \"in millions of dollars\"\n"
            "  base_number_only: true\n"
            "  source_file: transformed/treasury_bulletin_1965_01.txt\n"
            "  page_hint: 12\n"
            "  table_key: \"Total public debt outstanding / January 1965\"\n"
            "  raw_snippet: \"| Total public debt outstanding | 317,274 | 316,842 | 312,507 |\"\n"
            "  confidence: high\n"
            "  notes: \"Value is in millions — base number preserved, not expanded\""
        ),
        sources=["transformed/treasury_bulletin_1965_01.txt"]
    ).with_inputs("goal"),

    dspy.Example(
        goal="[THINK_MATH] Compute CAGR = (end/start)^(1/10) - 1 where end=370919, start=290862, n=10",
        output=(
            "EVIDENCE_CARD:\n"
            "  value: 0.0247\n"
            "  method: \"CAGR = (end/start)^(1/n) - 1\"\n"
            "  inputs: {end: 370919, start: 290862, n: 10}\n"
            "  computation: \"(370919/290862)^(1/10) - 1 = (1.2753)^(0.1) - 1 = 1.0247 - 1 = 0.0247\"\n"
            "  confidence: high"
        ),
        sources=[]
    ).with_inputs("goal"),

    dspy.Example(
        goal="[RETRIEVE_TABLE] Find average interest rate on Treasury bills in transformed/treasury_bulletin_1980_03.txt",
        output=(
            "EVIDENCE_CARD:\n"
            "  value: 15.20\n"
            "  unit_header: \"percent per annum\"\n"
            "  base_number_only: true\n"
            "  source_file: transformed/treasury_bulletin_1980_03.txt\n"
            "  page_hint: 34\n"
            "  table_key: \"Average rates — Treasury bills / March 1980\"\n"
            "  raw_snippet: \"| Treasury bills, 3-month | 15.20 | 12.07 | 10.04 |\"\n"
            "  confidence: high\n"
            "  notes: \"Rate is percent, not basis points. Answer without % sign.\""
        ),
        sources=["transformed/treasury_bulletin_1980_03.txt"]
    ).with_inputs("goal"),
]
