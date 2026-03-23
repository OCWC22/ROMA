"""OfficeQA-specific seed prompts for ROMA roles.

Optimized for U.S. Treasury Bulletin document QA with:
- Evidence card protocol (structured metadata, not prose)
- Scorer-mirror verifier (matches reward.py logic)
- OfficeQA-specific task subtypes (RETRIEVE_TABLE, THINK_MATH, etc.)
- Base-number-only formatting (never expand units)
"""
