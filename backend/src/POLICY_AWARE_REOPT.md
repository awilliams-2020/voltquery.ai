# Policy-Aware REopt Service Refactor

## Overview

Refactored REopt service to be "Policy-Aware" with 2026 OBBBA tax credit rules, ensuring correct ITC application and preventing zero NPV results due to overly strict financial assumptions.

## Key Changes

### 1. Policy-Aware Financial Strategy

**Logic Block Implementation:**
- Detects "lease" keywords: lease, leasing, leased, rent, PPA, third-party
- Detects "business" keywords: business, commercial, industrial, company, corporation, LLC, enterprise, facility, warehouse, office, retail, store, shop, restaurant

**2026 OBBBA Rules Applied:**
- **Rule 1**: If `ownership == 'purchase'` AND `type == 'residential'`: `fed_itc_fraction = 0.0`
- **Rule 2**: If `ownership == 'lease'` OR `type == 'commercial'`: `fed_itc_fraction = 0.30`

### 2. Forced Analysis Period

**All runs use 25-year analysis period:**
- Overrides property-type-specific defaults
- Ensures ROI has time to manifest
- Prevents premature zero NPV results

### 3. July 4th Safe Harbor Policy Warning

**For commercial queries:**
- Checks if current date is before 2026-07-04
- Adds `policy_warning` field to response: "NOTE: You must commence construction by July 4, 2026, to lock in this 30% credit."
- LLM explicitly uses this warning in final answers

### 4. Enhanced Output Format

**Response dictionary now includes:**
- `npv`: Net Present Value
- `recommended_size_kw`: Primary solar system size recommendation (from pv_kw)
- `optimal_system_sizes`: Detailed system sizes (pv_kw, storage_kw, storage_kwh)
- `policy_warning`: July 4th Safe Harbor warning (for commercial projects)
- `policy_notice`: General policy explanation

### 5. Updated Response Formatting

**Optimization bundle response includes:**
- Policy warning prominently displayed with ⚠️ emoji
- Recommended size as primary recommendation
- Policy notice for transparency
- All formatted for LLM consumption

## Implementation Details

### REoptService (`app/services/reopt_service.py`)

**Policy-Aware Logic:**
```python
# Apply 2026 OBBBA Rules for ITC
if property_type == "residential" and ownership_type == "purchase":
    fed_itc_fraction = 0.0
elif ownership_type == "lease" or property_type in ["commercial", "industrial"]:
    fed_itc_fraction = 0.30
else:
    fed_itc_fraction = 0.0  # Default fallback

# Force analysis_years = 25 for all runs
financial_params["analysis_years"] = 25
financial_params["federal_tax_credit_rate"] = fed_itc_fraction
```

**Policy Warning Generation:**
```python
def _extract_results(self, results, property_type=None):
    # ... extract npv, sizes, recommended_size_kw ...
    
    # Generate policy_warning for commercial projects
    if property_type in ["commercial", "industrial"]:
        current_date = date.today()
        cutoff_date = date(2026, 7, 4)
        if current_date < cutoff_date:
            policy_warning = (
                "NOTE: You must commence construction by July 4, 2026, "
                "to lock in this 30% credit."
            )
    
    return {
        "npv": npv,
        "recommended_size_kw": recommended_size_kw,
        "optimal_system_sizes": optimal_system_sizes,
        "policy_warning": policy_warning
    }
```

### Optimization Bundle (`src/bundles/optimization/__init__.py`)

**Enhanced Keyword Detection:**
- Business keywords: business, commercial, industrial, company, corporation, corp, llc, enterprise, facility, warehouse, office, retail, store, shop, restaurant
- Lease keywords: lease, leasing, leased, rent, renting, rented, ppa, power purchase agreement, third-party, third party

**Response Formatting:**
- Policy warning displayed with ⚠️ emoji for visibility
- Recommended size shown as primary recommendation
- Policy notice included for context

## Example Output

### Commercial Project (Before July 4, 2026)
```
REOPT OPTIMIZATION RESULTS (from NREL REopt v3 API):
Location: 80202
Load Profile Type: commercial
Analysis Period: 25 years
Federal Tax Credit: 30%

⚠️ POLICY WARNING: NOTE: You must commence construction by July 4, 2026, to lock in this 30% credit.

Net Present Value (NPV): $125,450.00

Recommended Solar System Size: 45.2 kW

Optimal System Sizes:
  Solar PV: 45.2 kW
  Storage Power: 10.5 kW
  Storage Capacity: 25.0 kWh
```

### Residential Purchase (0% ITC)
```
REOPT OPTIMIZATION RESULTS (from NREL REopt v3 API):
Location: 80202
Load Profile Type: residential
Analysis Period: 25 years
Federal Tax Credit: 0%

Policy Notice: The 30% Residential Tax Credit expired in 2025; 
this calculation uses 2026 OBBBA rules (0% for purchase, 30% for lease).

Net Present Value (NPV): $8,250.00

Recommended Solar System Size: 8.5 kW
```

### Residential Lease (30% ITC)
```
REOPT OPTIMIZATION RESULTS (from NREL REopt v3 API):
Location: 80202
Load Profile Type: residential
Analysis Period: 25 years
Federal Tax Credit: 30%

Policy Notice: This calculation uses the 2026 OBBBA Residential Tax Credit rules: 
30% federal tax credit applies to leased residential solar systems.

Net Present Value (NPV): $42,180.00

Recommended Solar System Size: 8.5 kW
```

## Benefits

1. **Prevents Zero NPV**: 25-year analysis period gives ROI time to manifest
2. **Correct ITC Application**: Policy-aware logic ensures correct tax credit rates
3. **User Transparency**: Policy warnings inform users of critical deadlines
4. **LLM Integration**: Policy warnings formatted for LLM to use in responses
5. **Business-Friendly**: Commercial projects automatically get 30% ITC

## Testing Recommendations

1. Test residential purchase query → should return 0% ITC, 25-year analysis
2. Test residential lease query → should return 30% ITC, 25-year analysis
3. Test commercial query (before July 4, 2026) → should return 30% ITC + policy_warning
4. Test business query → should return 30% ITC
5. Verify recommended_size_kw appears in all responses
6. Verify policy_warning appears for commercial projects
7. Verify analysis_years = 25 for all runs

## Files Modified

1. `backend/app/services/reopt_service.py`
   - Policy-aware ITC logic
   - Forced 25-year analysis period
   - Policy warning generation
   - Enhanced result extraction

2. `backend/src/bundles/optimization/__init__.py`
   - Enhanced keyword detection (lease/business)
   - Policy warning in response formatting
   - Recommended size display

## Notes

- REopt API calculates ITC internally based on PV cost
- The ITC rate affects NPV calculation through financial parameters
- Policy-aware logic ensures correct ITC rates are applied
- 25-year analysis period helps prevent zero NPV results
- Policy warnings are critical for commercial project planning

