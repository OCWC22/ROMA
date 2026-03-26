---
name: external-values
description: When and how to handle the 22% of OfficeQA questions that need external data not in Treasury docs
---

# External Values — Data Not in Treasury Bulletins

## When You Need External Data (22% of Questions)
Treasury Bulletins contain federal fiscal data: debt, receipts, outlays, interest rates.
They do NOT contain:
- GDP / GNP
- CPI / Inflation rates
- Population data
- State/local government data
- Private sector metrics
- Foreign country data (except TIC holdings)

## Recognition Patterns
If the question asks about:
- "as a percentage of GDP" → need GDP externally
- "in real/constant dollars" → need CPI externally
- "per capita" → need population externally
- "compared to [non-Treasury metric]" → need external source
- "inflation-adjusted" → need CPI

## What To Do
1. Recognize you need external data
2. If you have web search capability, use it
3. If not, state clearly: "This question requires [GDP/CPI/etc.] which is not in Treasury Bulletins"
4. Common reference values (approximate, for sanity checking only):
   - US GDP 1945: ~$228B | 1960: ~$543B | 1980: ~$2.86T | 2000: ~$10.3T | 2020: ~$21.1T
   - CPI base 1967=100: 1945≈53.9 | 1960≈88.7 | 1980≈248.8 | 2000≈515.8 | 2020≈791.8
   - US Population: 1945≈140M | 1960≈180M | 1980≈227M | 2000≈282M | 2020≈331M

## Warning
Do NOT guess external values. If you can't retrieve them, say so.
A wrong GDP figure will produce a wrong ratio that fails the scorer.

## Visual Questions (3%)
Some questions reference charts/graphs in scanned PDFs.
If the answer isn't in transformed/*.txt markdown tables:
1. Check parsed/*.json for extracted chart data
2. As last resort, note that visual reasoning from PDFs is needed
3. If you can read PDFs, look in raw/ or pdfs/ directories
