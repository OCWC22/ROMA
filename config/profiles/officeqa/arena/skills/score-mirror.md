---
name: score-mirror
description: How the OfficeQA scorer (reward.py) works — base number rules, tolerance, year filtering
---

# Score Mirror — How reward.py Evaluates Your Answer

## normalize_number_with_units()
1. Strips: $, commas, %, whitespace, Unicode characters
2. Converts Unicode minus (−) to hyphen-minus (-)
3. KEEPS the base number — does NOT expand "millions" → ×1000000
4. Returns cleaned numeric string

## score_answer()
1. Extracts ALL numbers from your ENTIRE response (greedy scan)
2. Filters out years (1900-2100) from predictions when ground truth is non-year-like
3. Compares each extracted number against ground truth
4. Default tolerance: 0.00 (exact match). May use 0.01 in private scorer — verify.
5. For multi-number ground truth: ALL GT numbers must be matched somewhere in response

## The #1 Rule
**NEVER expand units.** Table says "36,080" with header "in millions" → answer `36080`.
If you answer `36080000000`, you get a 999999× mismatch = automatic zero.

## Format Checklist
- No commas: `37921314` not `37,921,314`
- No dollar signs: `37921314` not `$37,921,314`
- No percent signs: `3.524` not `3.524%`
- Preserve source precision: `1608.80` stays `1608.80`
- Negatives with hyphen: `-3.524`
- Years are safe in reasoning text (auto-filtered)

## Tolerance Tiers (if applicable)
- Tier 1: 0% (exact match)
- Tier 2: 0.1% (within 0.001 × GT)
- Tier 3: 1% (within 0.01 × GT)
- Tier 4: 5% (within 0.05 × GT)
