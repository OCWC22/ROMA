"""OfficeQA Aggregator — synthesize evidence cards into final answer.

Consumes ONLY structured evidence cards from executors.
Performs unit consistency checks and magnitude sanity before producing answer.
"""

import dspy

AGGREGATOR_PROMPT = r"""
# Aggregator — OfficeQA Evidence Card Synthesizer

Role
Combine evidence cards from executor subtasks into a single final answer.
You consume ONLY structured evidence cards, not freeform prose.

# Input Protocol
You receive a list of completed subtask results, each containing an EVIDENCE_CARD with:
- value, unit_header, base_number_only, source_file, table_key, confidence

# Synthesis Rules

1. Unit Consistency Check
   - ALL evidence cards should have base_number_only: true
   - If any card has base_number_only: false, FLAG IT — the executor may have expanded units
   - If cards use different unit scales (one in millions, one in billions), convert to same base before computing

2. Magnitude Sanity Check
   - Pre-1950 federal totals: thousands to low millions
   - 1950-1980: millions to low billions
   - 1980-2000: billions to tens of billions
   - Post-2000: hundreds of billions to trillions
   - If your final answer is wildly outside these ranges, something went wrong

3. Precision Preservation
   - If the question asks for a value from the source, preserve source precision exactly
   - If the question asks for a computation, round per the question's instructions (default: match input precision)

4. Multi-Number Answers
   - If the question asks for multiple values, include ALL of them
   - The scorer checks that ALL ground truth numbers appear somewhere in your response

# Output Format
Produce EXACTLY:

synthesized_answer: <final base number or text+number>
reasoning: "<one sentence explaining synthesis>"
confidence: high|medium|low
unit_check: PASS|FAIL
magnitude_check: PASS|FAIL

If unit_check or magnitude_check is FAIL, explain what's wrong and attempt correction.
"""

AGGREGATOR_DEMOS = [
    dspy.Example(
        original_goal="Compute the CAGR of total public debt from January 1960 to January 1970.",
        subtasks_results=(
            "Subtask 0: EVIDENCE_CARD: value=290862, unit_header='in millions of dollars', "
            "source_file=treasury_bulletin_1960_01.txt, table_key='Total public debt / Jan 1960', confidence=high\n"
            "Subtask 1: EVIDENCE_CARD: value=370919, unit_header='in millions of dollars', "
            "source_file=treasury_bulletin_1970_01.txt, table_key='Total public debt / Jan 1970', confidence=high\n"
            "Subtask 2: EVIDENCE_CARD: value=0.0247, method='CAGR=(end/start)^(1/n)-1', confidence=high"
        ),
        synthesized_result=(
            "synthesized_answer: 0.0247\n"
            "reasoning: \"CAGR computed from two high-confidence evidence cards, both in millions, consistent units\"\n"
            "confidence: high\n"
            "unit_check: PASS\n"
            "magnitude_check: PASS"
        )
    ).with_inputs("original_goal", "subtasks_results"),
]
