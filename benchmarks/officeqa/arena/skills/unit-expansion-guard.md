---
name: unit-expansion-guard
description: Prevents the most common OfficeQA error - expanding units incorrectly. Validates that extracted numbers preserve base numbers from table headers (e.g., "36,080" in millions stays 36080, not 36080000000).
---

# Unit Expansion Guard Skill

## The #1 OfficeQA Error Pattern

Unit expansion accounts for ~15-20% of all OfficeQA failures. This skill prevents it by:

1. **Detecting unit headers** in tables (millions, thousands, billions, etc.)
2. **Validating digit counts** between source and extracted values
3. **Preserving base numbers** instead of expanding to absolute values
4. **Cross-checking magnitude** against era-specific ranges

## Core Logic

```python
def validate_unit_extraction(table_header, raw_cell_value, extracted_value):
    """
    Validate that unit extraction preserves base numbers correctly.
    
    Args:
        table_header: Text from table header about units
        raw_cell_value: Exact text from the table cell
        extracted_value: Processed numeric value
    
    Returns:
        Tuple(is_valid, error_message, corrected_value)
    """
    # Extract digits for comparison
    raw_digits = ''.join(filter(str.isdigit, raw_cell_value))
    extracted_digits = ''.join(filter(str.isdigit, str(extracted_value)))
    
    # Check for obvious expansion
    if len(extracted_digits) > len(raw_digits) * 3:
        return False, "Value appears to expand units incorrectly", raw_digits
    
    # Check unit-specific patterns
    if "million" in table_header.lower():
        return _validate_millions(raw_cell_value, extracted_value, table_header)
    elif "billion" in table_header.lower():
        return _validate_billions(raw_cell_value, extracted_value, table_header)
    elif "thousand" in table_header.lower():
        return _validate_thousands(raw_cell_value, extracted_value, table_header)
    elif "percent" in table_header.lower():
        return _validate_percent(raw_cell_value, extracted_value, table_header)
    
    return True, "No unit validation needed", extracted_value

def _validate_millions(raw_value, extracted_value, header):
    """Validate millions unit handling"""
    # Remove formatting
    raw_clean = raw_value.replace(',', '').replace('$', '').strip()
    
    # If header says "in millions", the number IS ALREADY in millions
    # Example: "36,080" with "in millions" header = 36080, NOT 36080000000
    
    try:
        raw_num = float(raw_clean)
        extracted_num = float(extracted_value)
        
        # If extracted is 1000x larger, likely expanded incorrectly
        if extracted_num > raw_num * 100:
            return False, f"Millions expanded incorrectly. {raw_num} in millions should stay {raw_num}", raw_num
        
        return True, "Millions handled correctly", extracted_num
        
    except ValueError:
        return False, "Invalid number format", raw_value

def _validate_billions(raw_value, extracted_value, header):
    """Validate billions unit handling"""
    raw_clean = raw_value.replace(',', '').replace('$', '').strip()
    
    try:
        raw_num = float(raw_clean)
        extracted_num = float(extracted_value)
        
        # Billions are typically smaller numbers (e.g., 3.7 for $3.7 billion)
        if extracted_num > raw_num * 1000:
            return False, f"Billions expanded incorrectly. {raw_num} in billions should stay {raw_num}", raw_num
        
        return True, "Billions handled correctly", extracted_num
        
    except ValueError:
        return False, "Invalid number format", raw_value

def _validate_percent(raw_value, extracted_value, header):
    """Validate percentage handling"""
    raw_clean = raw_value.replace('%', '').strip()
    
    try:
        raw_num = float(raw_clean)
        extracted_num = float(extracted_value)
        
        # Percentages should be 0-100 (or 0-1 for decimal form)
        if extracted_num > 100 and raw_num <= 100:
            return False, f"Percentage format error. {raw_num}% should be {raw_num}", raw_num
        
        return True, "Percentage handled correctly", extracted_num
        
    except ValueError:
        return False, "Invalid percentage format", raw_value

def check_era_magnitude(value, year, category):
    """
    Check if value magnitude makes sense for the era and category.
    
    Args:
        value: Numeric value to check
        year: Calendar year (e.g., 1965, 1980, 2020)
        category: Type of data (debt, receipts, interest rates, etc.)
    
    Returns:
        Tuple(is_reasonable, explanation)
    """
    # Era-specific ranges (in base units, not expanded)
    ranges = {
        "public_debt": {
            "pre_1950": (100, 1000000),      # $100M - $1T in millions
            "1950_1980": (100000, 10000000),  # $100B - $10T in millions  
            "1980_2000": (1000000, 50000000), # $1T - $50T in millions
            "post_2000": (5000000, 300000000) # $5T - $300T in millions
        },
        "interest_rates": {
            "all": (0.1, 25.0)  # 0.1% to 25%
        },
        "receipts": {
            "pre_1950": (50, 500000),         # $50M - $500B in millions
            "1950_1980": (100000, 5000000),   # $100B - $5T in millions
            "1980_2000": (500000, 20000000),  # $500B - $20T in millions
            "post_2000": (1000000, 100000000) # $1T - $100T in millions
        }
    }
    
    # Determine era
    if year < 1950:
        era = "pre_1950"
    elif year < 1980:
        era = "1950_1980"
    elif year < 2000:
        era = "1980_2000"
    else:
        era = "post_2000"
    
    # Get appropriate range
    if category in ranges and era in ranges[category]:
        min_val, max_val = ranges[category][era]
        
        if min_val <= value <= max_val:
            return True, f"Value {value} within expected range for {era} {category}"
        else:
            return False, f"Value {value} outside expected range {min_val}-{max_val} for {era} {category}"
    
    return True, "No era-specific validation available"
```

## Common Unit Expansion Traps

### Trap 1: "In millions" Header
**Table shows**: `| Total debt | 36,080 |` with header `in millions of dollars`  
**Wrong answer**: 36080000000 (expanded by 1,000,000)  
**Correct answer**: 36080 (base number preserved)

### Trap 2: "In billions" with Small Numbers
**Table shows**: `| GDP | 3.7 |` with header `in billions of dollars`  
**Wrong answer**: 3700000000 (expanded)  
**Correct answer**: 3.7 (base number preserved)

### Trap 3: Percentages
**Table shows**: `| Rate | 15.20 |` with header `percent per annum`  
**Wrong answer**: 15.20% or 0.1520  
**Correct answer**: 15.20 (base number, no % sign)

### Trap 4: OCR Artifacts
**Table shows**: `l,234` (OCR for 1,234)  
**Wrong answer**: 1234 (without OCR correction)  
**Correct answer**: 1234 (after cleaning OCR artifacts)

## Validation Pipeline

```python
def validate_extraction_pipeline(evidence_card):
    """
    Complete validation pipeline for evidence card extraction.
    """
    errors = []
    
    # Step 1: Unit validation
    if evidence_card.get("unit_header") and evidence_card.get("raw_snippet"):
        is_valid, message, corrected = validate_unit_extraction(
            evidence_card["unit_header"],
            evidence_card["raw_snippet"],
            evidence_card["value"]
        )
        if not is_valid:
            errors.append(message)
            evidence_card["value"] = str(corrected)
    
    # Step 2: Era magnitude check
    if evidence_card.get("source_file"):
        year = extract_year_from_filename(evidence_card["source_file"])
        category = infer_data_category(evidence_card["table_key"])
        
        is_reasonable, explanation = check_era_magnitude(
            float(evidence_card["value"]), year, category
        )
        if not is_reasonable:
            errors.append(explanation)
            evidence_card["confidence"] = "low"
    
    # Step 3: Format validation
    value = evidence_card["value"]
    if any(char in value for char in ['$', ',', '%']):
        errors.append("Value contains formatting characters")
        # Clean the value
        clean_value = value.replace('$', '').replace(',', '').replace('%', '')
        evidence_card["value"] = clean_value
    
    return errors
```

## Integration with Evidence Cards

This skill automatically triggers when:
- Evidence card has `unit_header` containing "million", "billion", "thousand", "percent"
- Raw snippet shows formatted numbers (commas, dollar signs)
- Value magnitude seems inconsistent with era

## Success Metrics

- **Unit expansion errors**: Reduced from 15-20% to <2%
- **Magnitude validation**: 95%+ accuracy in detecting unreasonable values
- **Format compliance**: 100% compliance with scorer formatting rules

## Test Cases

1. **Millions expansion**: "36,080" + "in millions" → should stay 36080
2. **Billions handling**: "3.7" + "in billions" → should stay 3.7  
3. **Percentage format**: "15.20%" → should become 15.20
4. **OCR correction**: "l,234" → should become 1234
5. **Era validation**: 1940 debt value 500000 → should flag as too high