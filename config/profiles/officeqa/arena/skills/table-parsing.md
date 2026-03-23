---
name: table-parsing
description: How to extract values from Treasury Bulletin markdown tables — OCR artifacts, multi-page tables, formatting
---

# Table Parsing for Treasury Bulletins

## Markdown Table Format (transformed/*.txt)
```
| Category | Jan 1965 | Feb 1965 | Mar 1965 |
|----------|----------|----------|----------|
| Total public debt | 317,274 | 316,842 | 312,507 |
| Held by public | 256,843 | 255,912 | 253,102 |
```

## Extraction Steps
1. Find the table by searching for keywords in the question
2. Identify the header row (first row with `|` separators)
3. Match the target column by header text
4. Match the target row by leftmost cell text
5. Extract the value at the row/column intersection
6. Clean: strip commas, $, whitespace → base number

## Multi-Page Tables
- Look for "(Continued)" or "(Cont'd)" in headers
- The continuation shares the same column structure
- Search beyond the initial match for continuation headers

## OCR Artifacts (Common in Older Bulletins)
| Artifact | Correct | How to Tell |
|----------|---------|-------------|
| `l,234` | `1,234` | Context: in a number column |
| `O` | `0` | Context: in a number column |
| `S` | `5` | Less common, check context |
| `—` or `–` | `-` | Unicode dash variants |
| `..` or `…` | N/A or 0 | Means "not applicable" |
| `(123)` | `-123` | Parentheses = negative |
| `r` suffix | revised | `r1,234` = revised value 1234 |
| `p` suffix | preliminary | `p1,234` = preliminary value 1234 |
| `e` suffix | estimated | `e1,234` = estimated value 1234 |

## Merged/Spanning Cells
Some tables have merged headers spanning multiple columns.
Read the PARENT header to understand the unit context (e.g., "in millions of dollars").

## Footnotes
- Footnote markers: ¹, ², ³, *, †, ‡
- Check bottom of table for footnote text
- "r" = revised, "p" = preliminary, "e" = estimated
- Some footnotes change the meaning of the number!
