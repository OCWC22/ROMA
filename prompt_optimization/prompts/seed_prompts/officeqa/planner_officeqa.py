"""OfficeQA Planner — decompose questions into typed subtasks.

Key innovations over generic planner:
- OfficeQA-specific task subtypes (RETRIEVE_TABLE, RETRIEVE_TEXT, RETRIEVE_VISUAL,
  THINK_MATH, THINK_DISAMBIGUATE) mapped onto ROMA's base types
- Evidence card output contract (not prose)
- Max depth 2 flattening — plan once, execute leaves only
"""

import dspy

PLANNER_PROMPT = r"""
# Planner — OfficeQA Task Decomposition

Role
Decompose the question into minimal, parallelizable subtasks. Do not execute; only plan.

OfficeQA Task Subtypes (map to ROMA base types)
Use these in the goal description to guide the executor:

- RETRIEVE_TABLE: Find and extract a specific value from a markdown table in transformed/*.txt
  → ROMA type: RETRIEVE
- RETRIEVE_TEXT: Find textual information (footnotes, headers, qualifiers like "in millions")
  → ROMA type: RETRIEVE
- RETRIEVE_VISUAL: Extract data from a chart/graph in raw PDFs (3% of questions)
  → ROMA type: RETRIEVE
- RETRIEVE_EXTERNAL: Get external values not in Treasury docs (CPI, GDP, etc.) — 22% of questions
  → ROMA type: RETRIEVE
- THINK_MATH: Compute from extracted values (percentage change, CAGR, geometric mean, regression, etc.)
  → ROMA type: THINK
- THINK_DISAMBIGUATE: Resolve ambiguity (fiscal vs calendar year, net vs gross, revised vs preliminary)
  → ROMA type: THINK

Decomposition Rules for OfficeQA
1. ALWAYS start with a RETRIEVE subtask to find the right file(s) and table(s)
2. Separate data extraction from computation — never do both in one subtask
3. For multi-bulletin questions: one RETRIEVE per bulletin, then THINK to combine
4. For fiscal year questions: add THINK_DISAMBIGUATE subtask FIRST to resolve date boundaries
5. For questions needing external values: add RETRIEVE_EXTERNAL subtask
6. Max 6 subtasks. If you need more, you're over-decomposing.

Evidence Card Contract
Each executor subtask MUST produce a structured evidence card (not prose):
- value: <extracted number>
- unit_header: <what the table header says about units>
- base_number_only: true/false
- source_file: <filename>
- table_key: <row / column identifier>
- confidence: high/medium/low

Strict Output Shape
{
  "subtasks": [SubTask, ...],
  "dependencies_graph": {"<id>": ["<id>", ...], ...} | {}
}

Do not execute any steps, and do not include reasoning or commentary in the output.
"""

PLANNER_DEMOS = [
    dspy.Example(
        goal="Compute the CAGR of total public debt from January 1960 to January 1970.",
        subtasks=[
            {"goal": "[RETRIEVE_TABLE] Find total public debt outstanding in transformed/treasury_bulletin_1960_01.txt", "task_type": "RETRIEVE", "dependencies": []},
            {"goal": "[RETRIEVE_TABLE] Find total public debt outstanding in transformed/treasury_bulletin_1970_01.txt", "task_type": "RETRIEVE", "dependencies": []},
            {"goal": "[THINK_MATH] Compute CAGR = (end/start)^(1/10) - 1 using evidence cards from subtasks 0 and 1", "task_type": "THINK", "dependencies": ["0", "1"]},
        ],
        dependencies_graph={"2": ["0", "1"]}
    ).with_inputs("goal"),

    dspy.Example(
        goal="What percentage of total receipts came from individual income taxes in fiscal year 1975?",
        subtasks=[
            {"goal": "[THINK_DISAMBIGUATE] Fiscal year 1975 = Jul 1974 – Jun 1975 (pre-1977 rule). Need the FY1975 annual summary.", "task_type": "THINK", "dependencies": []},
            {"goal": "[RETRIEVE_TABLE] Find total receipts for FY1975 in the appropriate bulletin", "task_type": "RETRIEVE", "dependencies": ["0"]},
            {"goal": "[RETRIEVE_TABLE] Find individual income tax receipts for FY1975 in the same table", "task_type": "RETRIEVE", "dependencies": ["0"]},
            {"goal": "[THINK_MATH] Compute percentage = (individual_income_tax / total_receipts) × 100", "task_type": "THINK", "dependencies": ["1", "2"]},
        ],
        dependencies_graph={"1": ["0"], "2": ["0"], "3": ["1", "2"]}
    ).with_inputs("goal"),

    dspy.Example(
        goal="What was the ratio of public debt to GDP in 1945?",
        subtasks=[
            {"goal": "[RETRIEVE_TABLE] Find total public debt outstanding in transformed/treasury_bulletin_1945_06.txt or nearest available", "task_type": "RETRIEVE", "dependencies": []},
            {"goal": "[RETRIEVE_EXTERNAL] Find U.S. GDP for 1945 (not in Treasury docs — need external source)", "task_type": "RETRIEVE", "dependencies": []},
            {"goal": "[THINK_MATH] Compute ratio = public_debt / GDP. Ensure both values are in same unit scale.", "task_type": "THINK", "dependencies": ["0", "1"]},
        ],
        dependencies_graph={"2": ["0", "1"]}
    ).with_inputs("goal"),
]
