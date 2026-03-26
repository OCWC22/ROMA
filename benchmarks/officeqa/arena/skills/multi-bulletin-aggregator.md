---
name: multi-bulletin-aggregator
description: Handles OfficeQA questions that span multiple Treasury Bulletins (11% of questions). Aggregates data across time periods, handles series discontinuities, and manages data revisions across bulletins.
---

# Multi-Bulletin Aggregator Skill

## Scope
~11% of OfficeQA questions require data from 3+ bulletins. This skill handles:
- Time series aggregation across months/years
- Annual totals from monthly data
- Cross-bulletin data consistency
- Handling data revisions in later bulletins

## Core Challenges

### Challenge 1: Data Revisions
Later bulletins often revise earlier data. The rule: **use the bulletin specified in the question**.

### Challenge 2: Series Continuity  
Some tables have breaks, changes in methodology, or missing months.

### Challenge 3: Unit Consistency
Different bulletins might use different units or formatting.

### Challenge 4: Annual vs Calendar
Fiscal year data needs special handling (see fiscal-year-expert skill).

## Implementation Logic

```python
class MultiBulletinAggregator:
    def __init__(self):
        self.cache = {}
        self.revision_tracker = {}
    
    def aggregate_across_bulletins(self, 
                                 evidence_cards, 
                                 aggregation_type="sum",
                                 time_period=None):
        """
        Aggregate data from multiple bulletin evidence cards.
        
        Args:
            evidence_cards: List of evidence cards from different bulletins
            aggregation_type: "sum", "average", "mean", "max", "min", "cagr"
            time_period: Optional time period description for validation
        
        Returns:
            Dict with aggregated_value, method, confidence, issues
        """
        
        # Step 1: Validate and clean cards
        clean_cards = self._validate_cards(evidence_cards)
        if not clean_cards:
            return {"error": "No valid evidence cards provided"}
        
        # Step 2: Sort chronologically
        sorted_cards = self._sort_chronologically(clean_cards)
        
        # Step 3: Check for data issues
        issues = self._detect_data_issues(sorted_cards)
        
        # Step 4: Perform aggregation
        if aggregation_type == "sum":
            result = self._aggregate_sum(sorted_cards)
        elif aggregation_type == "average" or aggregation_type == "mean":
            result = self._aggregate_average(sorted_cards)
        elif aggregation_type == "cagr":
            result = self._aggregate_cagr(sorted_cards, time_period)
        elif aggregation_type in ["max", "min"]:
            result = self._aggregate_extreme(sorted_cards, aggregation_type)
        else:
            result = {"error": f"Unsupported aggregation: {aggregation_type}"}
        
        result["issues"] = issues
        result["input_cards"] = len(evidence_cards)
        result["valid_cards"] = len(clean_cards)
        
        return result
    
    def _validate_cards(self, cards):
        """Validate and filter evidence cards"""
        valid_cards = []
        
        for card in cards:
            # Check required fields
            if not all(key in card for key in ["value", "source_file", "table_key"]):
                continue
            
            # Validate numeric value
            try:
                card["numeric_value"] = float(card["value"])
            except (ValueError, TypeError):
                continue
            
            # Extract date from filename
            year, month = self._extract_date_from_filename(card["source_file"])
            if year and month:
                card["year"] = year
                card["month"] = month
                card["date_sort"] = f"{year}-{month:02d}"
                valid_cards.append(card)
        
        return valid_cards
    
    def _sort_chronologically(self, cards):
        """Sort cards by date"""
        return sorted(cards, key=lambda x: x.get("date_sort", ""))
    
    def _detect_data_issues(self, cards):
        """Detect potential data issues across cards"""
        issues = []
        
        # Check for gaps in time series
        if len(cards) > 2:
            dates = [card["date_sort"] for card in cards]
            gaps = self._find_time_gaps(dates)
            if gaps:
                issues.append(f"Time gaps detected: {gaps}")
        
        # Check for unit inconsistencies
        units = [card.get("unit_header", "") for card in cards]
        unique_units = set(units)
        if len(unique_units) > 1:
            issues.append(f"Unit inconsistencies: {unique_units}")
        
        # Check for value outliers
        values = [card["numeric_value"] for card in cards]
        outliers = self._detect_outliers(values)
        if outliers:
            issues.append(f"Potential outliers: {outliers}")
        
        # Check for data revisions
        revisions = self._detect_revisions(cards)
        if revisions:
            issues.append(f"Data revisions detected: {revisions}")
        
        return issues
    
    def _aggregate_sum(self, cards):
        """Sum values across cards"""
        total = sum(card["numeric_value"] for card in cards)
        
        return {
            "aggregated_value": round(total, 2),
            "method": "sum",
            "confidence": self._calculate_confidence(cards),
            "detail": f"Summed {len(cards)} values from {cards[0]['date_sort']} to {cards[-1]['date_sort']}"
        }
    
    def _aggregate_average(self, cards):
        """Calculate average across cards"""
        values = [card["numeric_value"] for card in cards]
        avg = sum(values) / len(values)
        
        return {
            "aggregated_value": round(avg, 2),
            "method": "average", 
            "confidence": self._calculate_confidence(cards),
            "detail": f"Average of {len(cards)} values"
        }
    
    def _aggregate_cagr(self, cards, time_period):
        """Calculate Compound Annual Growth Rate"""
        if len(cards) < 2:
            return {"error": "CAGR requires at least 2 data points"}
        
        start_value = cards[0]["numeric_value"]
        end_value = cards[-1]["numeric_value"]
        
        # Calculate years between first and last data point
        start_year = int(cards[0]["year"])
        end_year = int(cards[-1]["year"])
        start_month = int(cards[0]["month"])
        end_month = int(cards[-1]["month"])
        
        years = (end_year - start_year) + (end_month - start_month) / 12
        
        if years <= 0:
            return {"error": "Invalid time period for CAGR"}
        
        if start_value <= 0:
            return {"error": "Start value must be positive for CAGR"}
        
        cagr = (end_value / start_value) ** (1/years) - 1
        
        return {
            "aggregated_value": round(cagr, 4),
            "method": "CAGR",
            "confidence": self._calculate_confidence(cards),
            "detail": f"CAGR over {years:.1f} years from {start_value} to {end_value}",
            "calculation": f"({end_value}/{start_value})^(1/{years}) - 1 = {cagr:.4f}"
        }
    
    def _aggregate_extreme(self, cards, extreme_type):
        """Find max or min value"""
        values = [(card["numeric_value"], card) for card in cards]
        
        if extreme_type == "max":
            result_card = max(values, key=lambda x: x[0])
        else:  # min
            result_card = min(values, key=lambda x: x[0])
        
        value, card = result_card
        
        return {
            "aggregated_value": round(value, 2),
            "method": extreme_type,
            "confidence": card.get("confidence", "medium"),
            "detail": f"{extreme_type.capitalize()} value from {card['date_sort']} ({card['source_file']})"
        }
    
    def _extract_date_from_filename(self, filename):
        """Extract year and month from Treasury Bulletin filename"""
        import re
        
        # Pattern: treasury_bulletin_YYYY_MM.txt
        match = re.search(r"treasury_bulletin_(\d{4})_(\d{2})", filename)
        if match:
            return match.group(1), match.group(2)
        
        return None, None
    
    def _find_time_gaps(self, dates):
        """Find gaps in time series"""
        gaps = []
        
        for i in range(len(dates) - 1):
            current = dates[i]
            next_date = dates[i + 1]
            
            # Simple gap detection - could be more sophisticated
            if not self._are_consecutive_months(current, next_date):
                gaps.append(f"{current} → {next_date}")
        
        return gaps
    
    def _are_consecutive_months(self, date1, date2):
        """Check if two dates are consecutive months"""
        try:
            year1, month1 = map(int, date1.split('-'))
            year2, month2 = map(int, date2.split('-'))
            
            if year2 == year1 and month2 == month1 + 1:
                return True
            elif year2 == year1 + 1 and month1 == 12 and month2 == 1:
                return True
            
            return False
        except:
            return False
    
    def _detect_outliers(self, values):
        """Detect outliers using IQR method"""
        if len(values) < 4:
            return []
        
        sorted_values = sorted(values)
        n = len(sorted_values)
        
        q1 = sorted_values[n // 4]
        q3 = sorted_values[3 * n // 4]
        iqr = q3 - q1
        
        outliers = []
        for i, val in enumerate(values):
            if val < q1 - 1.5 * iqr or val > q3 + 1.5 * iqr:
                outliers.append(f"Index {i}: {val}")
        
        return outliers
    
    def _detect_revisions(self, cards):
        """Detect potential data revisions"""
        revisions = []
        
        # Look for same metric in close time periods with different values
        for i, card1 in enumerate(cards):
            for card2 in cards[i+1:]:
                if (card1["table_key"] == card2["table_key"] and 
                    abs(int(card1["year"]) - int(card2["year"])) <= 1):
                    
                    val1 = card1["numeric_value"]
                    val2 = card2["numeric_value"]
                    
                    # If values differ by more than 5%, flag as potential revision
                    if abs(val1 - val2) / max(val1, val2) > 0.05:
                        revisions.append(
                            f"{card1['table_key']}: {val1} ({card1['date_sort']}) vs {val2} ({card2['date_sort']})"
                        )
        
        return revisions
    
    def _calculate_confidence(self, cards):
        """Calculate overall confidence based on input cards"""
        confidences = [card.get("confidence", "medium") for card in cards]
        
        if all(c == "high" for c in confidences):
            return "high"
        elif any(c == "low" for c in confidences):
            return "low"
        else:
            return "medium"

# Usage Examples
def aggregate_annual_total(monthly_cards):
    """Aggregate monthly cards to annual total"""
    aggregator = MultiBulletinAggregator()
    result = aggregator.aggregate_across_bulletins(
        monthly_cards, 
        aggregation_type="sum"
    )
    return result

def calculate_decade_cagr(decade_cards):
    """Calculate CAGR over a decade"""
    aggregator = MultiBulletinAggregator()
    result = aggregator.aggregate_across_bulletins(
        decade_cards,
        aggregation_type="cagr",
        time_period="decade"
    )
    return result
```

## Common Multi-Bulletin Patterns

### Pattern 1: Annual Totals
**Question**: "What were total receipts in 1965?"  
**Approach**: Sum all 12 months of 1965 data  
**Pitfall**: Some bulletins have annual summaries, don't double-count

### Pattern 2: Decade Comparisons  
**Question**: "Compare debt in 1950 vs 1960"  
**Approach**: Extract year-end values and compare  
**Pitfall**: Ensure consistent methodology across years

### Pattern 3: Growth Rates
**Question**: "CAGR of public debt 1960-1970"  
**Approach**: Use CAGR aggregation with start/end values  
**Pitfall**: Handle missing years correctly

### Pattern 4: Multi-Year Aggregates
**Question**: "Total interest payments 1955-1965"  
**Approach**: Sum across all months in the period  
**Pitfall**: Watch for data revisions in later bulletins

## Integration with Evidence Cards

This skill creates aggregate evidence cards:
```
EVIDENCE_CARD:
  value: <aggregated_result>
  method: "<aggregation_type>"
  inputs: {count: N, sources: [file1, file2, ...]}
  computation: "<step-by-step aggregation>"
  confidence: high|medium|low
  notes: "Aggregated from N bulletins spanning X years"
```

## Error Recovery

- **Missing data**: Interpolate with confidence reduction
- **Unit conflicts**: Normalize to common unit before aggregation  
- **Outlier detection**: Flag for manual review
- **Revision conflicts**: Use question-specified bulletin version

## Success Metrics

- **Multi-bulletin questions**: Improve accuracy from ~30% to >70%
- **Aggregation errors**: Reduce computational mistakes by 80%
- **Data consistency**: Detect 95%+ of revision conflicts
- **Time series gaps**: Identify and handle appropriately