---
name: treasury-navigation
description: How to find files and tables in the Treasury Bulletin corpus — file layout, common table locations, search strategy
---

# Treasury Bulletin Navigation

## File Layout
```
transformed/treasury_bulletin_YYYY_MM.txt  — Markdown tables (PRIMARY)
parsed/treasury_bulletin_YYYY_MM.json      — JSON with HTML tables (FALLBACK)
raw/ or pdfs/                              — Scanned PDFs (LAST RESORT)
```

## File Naming
- `treasury_bulletin_1965_01.txt` = January 1965 bulletin
- Not all months have bulletins — some are quarterly or annual
- Bulletins may contain data for prior months/years in summary tables

## Common Table Locations

### Public Debt
- "Statement of the Public Debt" — early pages
- Rows: "Total public debt outstanding", "Debt held by the public", "Intragovernmental"
- Units header: typically "in millions of dollars"

### Revenue / Receipts
- "Monthly Statement of Receipts and Outlays"
- Rows: "Total receipts", "Individual income taxes", "Corporation income taxes"
- May be in separate "Monthly Treasury Statement" section

### Interest Rates
- "Average Interest Rates on U.S. Treasury Securities"
- Rows by security type: bills, notes, bonds
- Units: "percent per annum"

### International / TIC Data
- "Treasury International Capital" — later pages
- Foreign holdings of U.S. securities

## Search Strategy
1. List files: `ls transformed/treasury_bulletin_196*` to find available bulletins
2. Search within file: look for table title keywords
3. Read relevant section (typically 50-100 lines around the match)
4. Identify exact row and column intersection
5. Check for "(Continued)" headers — tables may span pages

## Fiscal Year Boundaries
- Before 1977: Jul 1 – Jun 30 (FY1975 = Jul 1974 – Jun 1975)
- After 1977: Oct 1 – Sep 30 (FY1978 = Oct 1977 – Sep 1978)
- Transition Quarter (TQ): Jul 1 – Sep 30, 1976
