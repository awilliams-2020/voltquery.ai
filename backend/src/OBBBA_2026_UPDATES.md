# 2026 OBBBA Tax Credit Updates

## Overview

Updated GlobalSettings to reflect 2026 OBBBA (Omnibus Budget Reconciliation Act) tax credit changes, including explicit ITC rates and construction start date requirements for commercial projects.

## Changes Made

### 1. Explicit ITC Rate Fields

Added explicit fields for each property/ownership type:
- `residential_purchase_itc: float = 0.0` - 0% (expired in 2025)
- `residential_lease_itc: float = 0.30` - 30% (still eligible)
- `commercial_itc: float = 0.30` - 30% if construction_start_date < '2026-07-04'

### 2. Construction Start Date Support

Added `construction_start_date: Optional[str]` field:
- Format: 'YYYY-MM-DD'
- Used to determine commercial ITC eligibility
- Projects starting before July 4, 2026: Eligible for 30% ITC
- Projects starting on/after July 4, 2026: Subject to phaseout (currently defaults to 30% but can be adjusted)

### 3. Updated federal_tax_credit_rate Logic

The computed property now:
- Uses explicit ITC fields (`residential_purchase_itc`, `residential_lease_itc`, `commercial_itc`)
- Checks `construction_start_date` for commercial projects
- Applies July 4, 2026 cutoff date for commercial ITC eligibility

### 4. Enhanced Policy Notice

Updated `policy_notice` to include:
- OBBBA 2026 references
- Construction start date information for commercial projects
- Clear explanation of purchase vs lease differences for residential

### 5. LLM Prompt Updates

Updated prompts in both `orchestrator.py` and `rag_service.py`:
- Added rule: "If the year is 2026 and the question involves residential solar financing, explicitly compare the 0% purchase credit vs the 30% lease credit for homeowners"
- Added TAX CREDIT CONTEXT section explaining 2026 OBBBA rules
- Added example question showing purchase vs lease comparison

### 6. REoptService Integration

Updated `reopt_service.py`:
- Added `construction_start_date` parameter to `_build_payload()` and `run_reopt_optimization()`
- Passes `construction_start_date` to `get_financial_params()`
- Updated docstrings to document construction start date requirement

## Usage Examples

### Residential Purchase (0% ITC)
```python
settings = GlobalSettings(
    property_type="residential",
    ownership_type="purchase"
)
# settings.federal_tax_credit_rate == 0.0
# settings.policy_notice includes explanation of 0% vs 30% lease
```

### Residential Lease (30% ITC)
```python
settings = GlobalSettings(
    property_type="residential",
    ownership_type="lease"
)
# settings.federal_tax_credit_rate == 0.30
```

### Commercial Before Cutoff (30% ITC)
```python
settings = GlobalSettings(
    property_type="commercial",
    construction_start_date="2026-06-01"
)
# settings.federal_tax_credit_rate == 0.30
# settings.policy_notice mentions before July 4, 2026 cutoff
```

### Commercial After Cutoff (Subject to Phaseout)
```python
settings = GlobalSettings(
    property_type="commercial",
    construction_start_date="2026-08-01"
)
# settings.federal_tax_credit_rate == 0.30 (default, can be adjusted for phaseout)
# settings.policy_notice mentions after July 4, 2026 - subject to phaseout
```

## LLM Behavior

When users ask about residential solar financing in 2026, the LLM will now:
1. Recognize the year is 2026
2. Explicitly compare purchase (0%) vs lease (30%) tax credits
3. Provide clear financial analysis showing the difference
4. Reference OBBBA 2026 rules in responses

## Testing Recommendations

1. Test residential purchase → should return 0% ITC
2. Test residential lease → should return 30% ITC
3. Test commercial with construction_start_date < '2026-07-04' → should return 30% ITC
4. Test commercial with construction_start_date >= '2026-07-04' → should return 30% ITC (with phaseout notice)
5. Test LLM prompt with "Should I buy or lease solar in 2026?" → should explicitly compare 0% vs 30%
6. Verify policy_notice includes OBBBA references

## Files Modified

1. `backend/src/global_settings.py`
   - Added explicit ITC fields
   - Added construction_start_date field and validation
   - Updated federal_tax_credit_rate logic
   - Enhanced policy_notice

2. `backend/src/orchestrator.py`
   - Updated prompt template with 2026 OBBBA context
   - Added explicit comparison instruction for residential financing

3. `backend/app/services/rag_service.py`
   - Updated prompt template (same as orchestrator)

4. `backend/app/services/reopt_service.py`
   - Added construction_start_date parameter
   - Updated to pass construction_start_date to GlobalSettings

## Notes

- The commercial ITC phaseout after July 4, 2026 is currently set to 30% but can be adjusted based on actual phaseout schedule
- Construction start date validation ensures 'YYYY-MM-DD' format
- All changes maintain backward compatibility (defaults preserve existing behavior)

