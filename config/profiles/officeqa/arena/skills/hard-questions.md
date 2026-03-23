---
name: hard-questions
description: Strategy for OfficeQA hard questions — decomposition playbook, time budgets, common traps, failure patterns
---

# Hard Question Strategy

133 of 246 questions are "hard". They score low because of these patterns:

## Question Decomposition
Before doing ANYTHING, parse the question for:
1. **Date/period**: Specific month? Fiscal year? Date range? Calendar vs fiscal?
2. **Metric**: What exactly is being asked for? (total, net, gross, average, rate)
3. **Computation**: Simple lookup? Percentage? CAGR? Comparison? Regression?
4. **Rounding**: Does the question specify rounding? If not, preserve source precision.

## Time Budget
- Easy (single lookup): 1-2 minutes
- Hard (multi-step): 4-6 minutes
- NEVER exceed 8 minutes on one question — move on

## Top 8 Failure Patterns

### 1. Unit Expansion (~15-20% of errors)
"36,080 in millions" → answered 36080000000 instead of 36080
**Fix**: NEVER multiply by the unit. Answer the base number.

### 2. Wrong Cell
Read adjacent row/column instead of the target.
**Fix**: Verify BOTH row label AND column label match the question exactly.

### 3. Wrong Bulletin
Used a different year/month than the question asks.
**Fix**: Re-read the question. Match filename to question date.

### 4. Fiscal Year Confusion
Used calendar year (Jan-Dec) instead of fiscal year.
**Fix**: Before 1977: Jul-Jun. After 1977: Oct-Sep. Always check.

### 5. Missing Multi-Numbers
Question asks for 4 values, you provide 2.
**Fix**: Count expected outputs. Provide ALL of them.

### 6. Precision Errors
Source says "1608.80", you answer "1609" or "1608.8".
**Fix**: Preserve EXACT precision from source.

### 7. Table Continuation
Table has 50 rows across 2 pages, you only read page 1.
**Fix**: Search for "(Continued)" or "(Cont'd)" headers.

### 8. External Values Needed (22% of questions)
Question requires CPI, GDP, or other non-Treasury data.
**Fix**: Recognize when you need external data and state it. Don't guess.

## Visual Questions (3%)
Some questions reference charts/graphs in PDFs.
If transformed/*.txt doesn't have the data, check raw PDFs.

## Multi-Bulletin Questions (11%)
Some questions span 3+ bulletins (e.g., "annual totals from 1960-1970").
Plan: one RETRIEVE per bulletin, then THINK to combine.
