# Scenario Branching Implementation

## Overview

Implemented "Scenario Branching" for REopt service to handle 2026 OBBBA policy context. For residential queries, the service now runs two internal REopt simulations (Purchase vs Lease) and compares them side-by-side.

## Key Features

### 1. Input Detection
- **Residential Queries**: Automatically detected and trigger dual scenario analysis
- **Commercial Queries**: Single scenario with policy flag for July 4, 2026 deadline

### 2. Scenario Branching for Residential

**Scenario A (Purchase):**
- `fed_itc_fraction: 0.0` (0% - expired in 2025)
- `analysis_years: 25`
- Ownership Type: Purchase

**Scenario B (Lease):**
- `fed_itc_fraction: 0.30` (30% - PPA provider receives credit)
- `analysis_years: 25`
- Ownership Type: Lease/PPA

### 3. Commercial Logic

**Single Scenario:**
- `fed_itc_fraction: 0.30`
- `analysis_years: 25`
- `policy_flag`: "NOTE: You must commence construction by July 4, 2026, to lock in this 30% credit."

### 4. Global Constants from GlobalSettings

All financial parameters pulled from `GlobalSettings`:
- `electricity_rate_escalation`: 0.04 (4%) - from `elec_cost_escalation_rate_fraction`
- `discount_rate`: 0.07 (7%) - from `offtaker_discount_rate_fraction`
- `analysis_years`: 25 (forced for all scenarios)

### 5. Output Format

**Residential (Dual Scenarios):**
```json
{
  "scenario_type": "residential",
  "scenario_a": {
    "name": "Purchase",
    "ownership_type": "purchase",
    "fed_itc_fraction": 0.0,
    "analysis_years": 25,
    "npv": ...,
    "recommended_size_kw": ...,
    "optimal_system_sizes": {...},
    "policy_notice": "..."
  },
  "scenario_b": {
    "name": "Lease",
    "ownership_type": "lease",
    "fed_itc_fraction": 0.30,
    "analysis_years": 25,
    "npv": ...,
    "recommended_size_kw": ...,
    "optimal_system_sizes": {...},
    "policy_notice": "..."
  }
}
```

**Commercial (Single Scenario):**
```json
{
  "scenario_type": "commercial",
  "scenario": {
    "name": "Commercial",
    "property_type": "commercial",
    "fed_itc_fraction": 0.30,
    "analysis_years": 25,
    "policy_flag": "NOTE: You must commence construction by July 4, 2026...",
    "npv": ...,
    "recommended_size_kw": ...,
    "optimal_system_sizes": {...}
  }
}
```

### 6. LLM Prompt Updates

Updated prompts in both `orchestrator.py` and `rag_service.py`:

```
IMPORTANT: When the optimization_tool returns scenario branching results (Purchase vs Lease scenarios):
- Compare the Purchase vs. Lease scenarios side-by-side
- Explain that the 2026 OBBBA rules make the Lease more viable for homeowners because the provider still gets the 30% credit
- Highlight the NPV difference between scenarios
- Note that while homeowners lose the purchase tax credit in 2026, lease/PPA providers can still claim 30% and pass savings through lower rates
```

## Implementation Details

### REoptService (`app/services/reopt_service.py`)

**New Method: `run_reopt_scenario_branching()`**
- Detects property type (residential vs commercial)
- For residential: Runs two `run_reopt_optimization()` calls (Purchase and Lease)
- For commercial: Runs single optimization with policy flag
- Returns structured JSON with scenario comparison

**Updated `_build_payload()`:**
- Uses GlobalSettings constants for all financial parameters
- Forces `analysis_years = 25` for all scenarios
- Applies policy-aware ITC rates (0% for residential purchase, 30% for lease/commercial)

### Optimization Bundle (`src/bundles/optimization/__init__.py`)

**Updated `_aquery()`:**
- Detects residential queries and calls `run_reopt_scenario_branching()`
- Routes to appropriate response formatter based on scenario type

**New Method: `_format_scenario_branching_response()`**
- Formats dual scenario results with side-by-side comparison
- Includes:
  - Scenario A (Purchase) details
  - Scenario B (Lease) details
  - Comparison summary with NPV difference
  - 2026 OBBBA policy context explanation

## Example Output

### Residential Query Response

```
REOPT SCENARIO BRANCHING RESULTS (2026 OBBBA Policy Comparison):
Location: 80202
Load Profile Type: residential
Analysis Period: 25 years (both scenarios)

============================================================
SCENARIO A: PURCHASE (0% Federal Tax Credit)
============================================================
Federal Tax Credit: 0% (expired in 2025 per 2026 OBBBA rules)
Ownership Type: Purchase
Net Present Value (NPV): $8,250.00
Recommended Solar System Size: 8.5 kW

Optimal System Sizes:
  Solar PV: 8.5 kW

Policy Notice: The 30% Residential Tax Credit expired in 2025; 
this calculation uses 2026 OBBBA rules (0% for purchase, 30% for lease).

============================================================
SCENARIO B: LEASE (30% Federal Tax Credit)
============================================================
Federal Tax Credit: 30% (PPA provider receives credit)
Ownership Type: Lease/PPA
Net Present Value (NPV): $42,180.00
Recommended Solar System Size: 8.5 kW

Optimal System Sizes:
  Solar PV: 8.5 kW

Policy Notice: This calculation uses the 2026 OBBBA Residential Tax Credit rules: 
30% federal tax credit applies to leased residential solar systems.

============================================================
COMPARISON SUMMARY
============================================================
NPV Difference (Lease - Purchase): $33,930.00
✓ Lease scenario shows $33,930.00 higher NPV due to 30% tax credit

2026 OBBBA POLICY CONTEXT:
The 30% Residential Tax Credit expired in 2025 for homeowner purchases.
However, leased/PPA systems remain eligible because the provider (not the homeowner)
receives the 30% federal tax credit. This makes lease scenarios more viable for
homeowners in 2026, as the provider can pass savings through lower lease rates.
```

## Benefits

1. **Policy-Aware Analysis**: Automatically compares Purchase vs Lease for residential queries
2. **2026 OBBBA Compliance**: Correctly applies 0% ITC for residential purchase, 30% for lease
3. **User Education**: Explains why lease is more viable in 2026 (provider gets credit)
4. **Side-by-Side Comparison**: Easy to see NPV difference between scenarios
5. **Commercial Policy Flags**: Warns about July 4, 2026 construction deadline

## Testing Recommendations

1. Test residential query → should return dual scenarios (Purchase vs Lease)
2. Test commercial query → should return single scenario with policy flag
3. Verify NPV difference calculation
4. Verify GlobalSettings constants are used (0.04 escalation, 0.07 discount)
5. Verify analysis_years = 25 for all scenarios
6. Test LLM prompt with scenario branching results → should compare scenarios

## Files Modified

1. `backend/app/services/reopt_service.py`
   - Added `run_reopt_scenario_branching()` method
   - Updated `_build_payload()` to use GlobalSettings constants

2. `backend/src/bundles/optimization/__init__.py`
   - Updated `_aquery()` to use scenario branching
   - Added `_format_scenario_branching_response()` method

3. `backend/src/orchestrator.py`
   - Updated LLM prompt with scenario comparison instructions

4. `backend/app/services/rag_service.py`
   - Updated LLM prompt with scenario comparison instructions

## Notes

- Both scenarios run sequentially (not in parallel) to avoid API rate limits
- Commercial queries use single scenario (no branching needed)
- Policy flag only appears for commercial projects before July 4, 2026
- All financial constants come from GlobalSettings for consistency

