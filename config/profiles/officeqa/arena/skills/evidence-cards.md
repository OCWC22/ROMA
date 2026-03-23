---
name: evidence-cards
description: Structured output protocol for extracted values — preserves metadata that prose compression destroys
---

# Evidence Card Protocol

## Why Evidence Cards (Not Prose)
Prose compression ("the value was about 36K in millions") destroys the exact bits needed downstream:
- Header unit text (was it "millions" or "thousands"?)
- Exact row/column intersection
- Source file path
- Whether the value is already a base number
- Raw snippet for verification

Evidence cards preserve ALL of this in a typed, machine-readable format.

## RETRIEVE Evidence Card
```
EVIDENCE_CARD:
  value: <extracted number, base only, no commas/$/%>
  unit_header: "<exact text from table header about units>"
  base_number_only: true
  source_file: <filename>
  page_hint: <line number or page>
  table_key: "<exact row label> / <exact column label>"
  raw_snippet: "<2-3 lines of raw table showing context>"
  confidence: high|medium|low
  notes: "<qualifiers: revised, preliminary, fiscal year, footnote refs>"
```

## THINK Evidence Card
```
EVIDENCE_CARD:
  value: <computed result>
  method: "<formula used>"
  inputs: {<param>: <value>, ...}
  computation: "<step-by-step work showing each intermediate result>"
  confidence: high|medium|low
```

## Rules
1. Every RETRIEVE executor output MUST be an evidence card
2. Every THINK executor output MUST be an evidence card
3. The aggregator consumes ONLY evidence cards
4. The verifier checks evidence card metadata (not just the value)
5. Never summarize an evidence card into prose — keep the structured format

## Confidence Levels
- **high**: Exact cell found, headers clear, value unambiguous
- **medium**: Cell found but headers slightly ambiguous, or OCR artifacts present
- **low**: Value inferred from context, or table structure unclear

## Anti-Patterns (DO NOT DO)
❌ "The total public debt was about 317 billion in Jan 1965"
✅ EVIDENCE_CARD with value: 317274, unit_header: "in millions of dollars", source_file: ...

❌ "I found the rate was around 15%"
✅ EVIDENCE_CARD with value: 15.20, unit_header: "percent per annum", table_key: "Treasury bills / March 1980"
