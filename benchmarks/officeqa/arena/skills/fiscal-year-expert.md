---
name: fiscal-year-expert
description: Expert system for fiscal year disambiguation in Treasury Bulletin data. Handles pre-1977 (Jul-Jun) and post-1977 (Oct-Sep) fiscal year boundaries, plus the transition quarter (TQ) July-Sep 1976.
---

# Fiscal Year Expert Skill

## Core Challenge
OfficeQA frequently asks about "fiscal year X" but Treasury Bulletins use calendar month reporting. This skill maps fiscal years to the correct calendar date ranges and bulletin sources.

## Fiscal Year Rules

### Pre-1977 Rule (Old Federal Fiscal Year)
- **Fiscal Year**: July 1 → June 30
- **FY1975**: July 1, 1974 → June 30, 1975
- **Source bulletins**: Jul 1974 through Jun 1975
- **Annual summary**: Usually in Jun 1975 bulletin

### Post-1977 Rule (Current Federal Fiscal Year)  
- **Fiscal Year**: October 1 → September 30
- **FY1978**: October 1, 1977 → September 30, 1978
- **Source bulletins**: Oct 1977 through Sep 1978
- **Annual summary**: Usually in Sep 1978 bulletin

### Transition Quarter (TQ)
- **TQ1976**: July 1, 1976 → September 30, 1976
- **Special case**: Only 3 months to bridge the calendar change
- **Source**: Jul, Aug, Sep 1976 bulletins

## Implementation Logic

```python
def resolve_fiscal_year(fiscal_year_str):
    """
    Convert fiscal year to calendar date ranges and bulletin sources.
    
    Args:
        fiscal_year_str: String like "FY1975", "fiscal year 1975", "1975"
    
    Returns:
        Dict with date_range, bulletin_months, annual_summary_location
    """
    # Extract year
    year = int(re.search(r'\d{4}', fiscal_year_str).group())
    
    if year < 1977:
        # Pre-1977: Jul-Jun
        return {
            "date_range": f"Jul {year-1} - Jun {year}",
            "bulletin_months": [f"{month:02d}_{year-1}" for month in [7,8,9,10,11,12]] + 
                            [f"{month:02d}_{year}" for month in [1,2,3,4,5,6]],
            "annual_summary": f"06_{year}",  # June bulletin typically has FY summary
            "rule": "pre_1977"
        }
    elif year == 1976:
        # Transition quarter special case
        return {
            "date_range": f"Jul {year} - Sep {year}",
            "bulletin_months": [f"07_{year}", f"08_{year}", f"09_{year}"],
            "annual_summary": f"09_{year}",
            "rule": "transition_quarter"
        }
    else:
        # Post-1977: Oct-Sep
        return {
            "date_range": f"Oct {year-1} - Sep {year}",
            "bulletin_months": [f"{month:02d}_{year-1}" for month in [10,11,12]] + 
                            [f"{month:02d}_{year}" for month in [1,2,3,4,5,6,7,8,9]],
            "annual_summary": f"09_{year}",  # September bulletin typically has FY summary
            "rule": "post_1977"
        }

def find_fiscal_data(bulletin_data, fiscal_year_info, target_metric):
    """
    Find fiscal year data in bulletin content.
    
    Args:
        bulletin_data: List of bulletin contents indexed by month
        fiscal_year_info: Output from resolve_fiscal_year()
        target_metric: What to find (e.g., "total receipts", "public debt")
    
    Returns:
        Dict with value, source, confidence
    """
    # Strategy 1: Look for annual summary first
    summary_month = fiscal_year_info["annual_summary"]
    if summary_month in bulletin_data:
        summary_value = extract_annual_summary(bulletin_data[summary_month], target_metric)
        if summary_value:
            return {
                "value": summary_value,
                "source": f"treasury_bulletin_{summary_month}.txt",
                "method": "annual_summary",
                "confidence": "high"
            }
    
    # Strategy 2: Sum monthly data
    monthly_values = []
    for month in fiscal_year_info["bulletin_months"]:
        if month in bulletin_data:
            monthly_val = extract_monthly_value(bulletin_data[month], target_metric)
            if monthly_val:
                monthly_values.append(monthly_val)
    
    if len(monthly_values) >= 6:  # At least half the months
        total = sum(monthly_values)
        return {
            "value": total,
            "source": f"summed_{len(monthly_values)}_months",
            "method": "monthly_sum",
            "confidence": "medium"
        }
    
    # Strategy 3: Interpolate from available data
    if len(monthly_values) >= 2:
        avg_monthly = sum(monthly_values) / len(monthly_values)
        estimated_total = avg_monthly * 12
        return {
            "value": estimated_total,
            "source": f"estimated_from_{len(monthly_values)}_months",
            "method": "interpolation",
            "confidence": "low"
        }
    
    return None
```

## Common Traps & Solutions

### Trap 1: Using Calendar Year Data
**Wrong**: Using Jan-Dec 1975 data for FY1975 questions  
**Fix**: Use Jul 1974-Jun 1975 data for pre-1977 fiscal years

### Trap 2: Missing the Transition Quarter  
**Wrong**: Assuming FY1976 follows either old or new rule  
**Fix**: Handle TQ1976 as special 3-month case

### Trap 3: Annual Summary Location
**Wrong**: Looking for FY summary in December bulletin  
**Fix**: Pre-1977 summaries in June, post-1977 in September

### Trap 4: Partial Year Data
**Wrong**: Using only available months without noting incompleteness  
**Fix**: Explicitly track data completeness and confidence

## Verification Checklist

- [ ] Correct fiscal year rule applied (pre/post-1977)
- [ ] TQ1976 handled as special case if relevant
- [ ] Bulletin months match fiscal year definition
- [ ] Annual summary location correct for era
- [ ] Data completeness noted in confidence
- [ ] Source bulletin years match fiscal year range

## Examples

**Question**: "What were total federal receipts in fiscal year 1975?"  
**Resolution**: FY1975 = Jul 1974 - Jun 1975, look in Jun 1975 bulletin for annual summary

**Question**: "What was the public debt in fiscal year 1978?"  
**Resolution**: FY1978 = Oct 1977 - Sep 1978, look in Sep 1978 bulletin for annual summary

**Question**: "Compare fiscal year 1975 vs 1976 receipts"  
**Resolution**: FY1975 = Jul 1974-Jun 1975, TQ1976 = Jul-Sep 1976 (special case)