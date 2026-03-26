---
name: table-math
description: Computation patterns for OfficeQA — CAGR, geometric mean, regression, percentage change, KL divergence
---

# Computation Patterns for OfficeQA

All computations produce EVIDENCE_CARD format output.

## 1. Table Lookup (most common)
```
Read file → find table → extract cell → base number only
```

## 2. Percentage Change
```
pct_change = (new - old) / old × 100
```
Example: old=290862, new=370919 → (370919-290862)/290862 × 100 = 27.53

## 3. CAGR (Compound Annual Growth Rate)
```
CAGR = (end/start)^(1/n) - 1
```
Example: start=290862, end=370919, n=10 → (370919/290862)^(0.1) - 1 = 0.0247

## 4. Geometric Mean
```
geo_mean = exp(mean(ln(values)))
```
Example: [2.1, 3.5, 4.2, 2.8] → exp(mean([0.742, 1.253, 1.435, 1.030])) = exp(1.115) = 3.05

## 5. Linear Regression
```
Minimize Σ(y - mx - b)²
m = (nΣxy - ΣxΣy) / (nΣx² - (Σx)²)
b = (Σy - mΣx) / n
```

## 6. KL Divergence
```
KL(P||Q) = Σ p(x) × ln(p(x)/q(x))
```

## 7. Coefficient of Variation
```
CV = (std / mean) × 100
```

## 8. Inflation Adjustment
```
adjusted = nominal × (CPI_target / CPI_base)
```
Note: CPI values are NOT in Treasury Bulletins — need external source.

## 9. Multi-Document Aggregation
```
For each document: extract value → evidence card
Then: combine via sum, average, or other operation
```

## 10. Zipf Exponent
```
Rank-frequency: f(r) = C × r^(-α)
ln(f) = ln(C) - α × ln(r)
Linear regression on log-log to find α
```

## Output Format
Always show step-by-step work in EVIDENCE_CARD:
```
EVIDENCE_CARD:
  value: <result>
  method: "<formula name>"
  inputs: {param: value, ...}
  computation: "<each step>"
  confidence: high|medium|low
```
