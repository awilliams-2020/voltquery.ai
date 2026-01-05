# GlobalSettings Refactor: Policy Rules and Financial Constants

## Overview

Refactored `GlobalSettings` to centralize financial assumptions with policy-based tax credit rules and updated inflation constants. All financial parameters are now consistently applied across `reopt_service` and optimization bundle.

## Key Changes

### 1. Policy Rules for Federal Tax Credit

**Logic Gate Implementation:**
- **Residential + Purchase**: `fed_itc = 0.0` (expired in 2025, 2026 rules)
- **Residential + Lease**: `fed_itc = 0.30` (30% tax credit still applies)
- **Commercial/Industrial**: Defaults to `0.30` (may vary by program)

**Implementation:**
```python
@property
def federal_tax_credit_rate(self) -> float:
    if self.property_type == "residential":
        if self.ownership_type == "purchase":
            return 0.0  # Expired in 2025
        elif self.ownership_type == "lease":
            return 0.30  # Still eligible
    return 0.30  # Commercial/Industrial default
```

### 2. Updated Inflation Constants

- **Electricity Escalation Rate**: `0.0166` → `0.04` (1.66% → 4%)
- **Discount Rate**: `0.0624` → `0.07` (6.24% → 7%)

### 3. Analysis Period Defaults

- **Residential**: 25 years (unchanged)
- **Commercial**: 20 years (was 25, now 20)

### 4. Policy Notice for User Transparency

Added `policy_notice` computed field that generates user-friendly explanations:

```python
@property
def policy_notice(self) -> str:
    if self.property_type == "residential":
        if self.ownership_type == "purchase":
            return (
                "The 30% Residential Tax Credit expired in 2025; "
                "this calculation uses 2026 rules (0% for purchase, 30% for lease)."
            )
        elif self.ownership_type == "lease":
            return (
                "This calculation uses the 2026 Residential Tax Credit rules: "
                "30% federal tax credit applies to leased residential solar systems."
            )
```

## Integration Points

### REoptService (`app/services/reopt_service.py`)

**Changes:**
1. Imports `get_global_settings` from `src.global_settings`
2. `_build_payload()` now accepts `property_type` and `ownership_type` parameters
3. Financial section pulls all values from `GlobalSettings.get_financial_params()`
4. PV and Storage sections use `global_settings.solar_installed_cost_per_kw`, etc.
5. `run_reopt_optimization()` accepts `property_type` and `ownership_type` parameters
6. Returns `policy_notice` in the result dictionary

**Example Usage:**
```python
result = await reopt_service.run_reopt_optimization(
    lat=lat,
    lon=lon,
    load_profile_type="residential",
    property_type="residential",
    ownership_type="purchase",  # Will result in 0% tax credit
    ...
)
# result["policy_notice"] contains explanation
```

### Optimization Bundle (`src/bundles/optimization/__init__.py`)

**Changes:**
1. Extracts `property_type` and `ownership_type` from query strings
2. Passes these parameters to `reopt_service.run_reopt_optimization()`
3. Includes `policy_notice` in formatted response output
4. Uses `get_financial_params()` for consistent parameter display

**Query Extraction:**
- Detects "commercial", "industrial" → sets `property_type`
- Detects "lease", "leasing", "leased" → sets `ownership_type = "lease"`
- Detects "purchase", "buy", "buying" → sets `ownership_type = "purchase"`

## API Changes

### GlobalSettings Methods

**New Method: `get_financial_params()`**
```python
financial_params = settings.get_financial_params(
    property_type="residential",
    ownership_type="purchase"
)
# Returns dict with all financial parameters including policy_notice
```

**Computed Properties:**
- `federal_tax_credit_rate` - Calculated based on policy rules
- `analysis_years` - Based on property_type (25 residential, 20 commercial)
- `policy_notice` - User-friendly explanation of tax credit rules

### REoptService Method Signature

**Updated: `run_reopt_optimization()`**
```python
async def run_reopt_optimization(
    self,
    lat: float,
    lon: float,
    load_profile_type: str = "residential",
    urdb_label: Optional[str] = None,
    zip_code: Optional[str] = None,
    additional_load_kw: float = 0.0,
    property_type: Optional[Literal["residential", "commercial", "industrial"]] = None,
    ownership_type: Optional[Literal["purchase", "lease"]] = None
) -> Dict[str, Any]:
```

**Return Value:**
```python
{
    "npv": float,
    "optimal_system_sizes": dict,
    "policy_notice": str  # NEW: Policy explanation
}
```

## Example Output

### Residential Purchase (0% Tax Credit)
```
REOPT OPTIMIZATION RESULTS (from NREL REopt v3 API):
Location: 80202
Load Profile Type: residential
Analysis Period: 25 years
Federal Tax Credit: 0%

Policy Notice: The 30% Residential Tax Credit expired in 2025; 
this calculation uses 2026 rules (0% for purchase, 30% for lease).

Net Present Value (NPV): $15,234.56
...
```

### Residential Lease (30% Tax Credit)
```
REOPT OPTIMIZATION RESULTS (from NREL REopt v3 API):
Location: 80202
Load Profile Type: residential
Analysis Period: 25 years
Federal Tax Credit: 30%

Policy Notice: This calculation uses the 2026 Residential Tax Credit rules: 
30% federal tax credit applies to leased residential solar systems.

Net Present Value (NPV): $45,678.90
...
```

## Benefits

1. **Centralized Configuration**: All financial assumptions in one place
2. **Policy Compliance**: Automatically applies 2026 tax credit rules
3. **User Transparency**: Policy notices explain tax credit calculations
4. **Consistency**: Same financial parameters used across all tools
5. **Maintainability**: Easy to update policy rules as tax laws change
6. **Flexibility**: Supports different property types and ownership models

## Migration Notes

- Existing code that doesn't specify `property_type`/`ownership_type` will use defaults
- Default behavior: `property_type="residential"`, `ownership_type="purchase"` → 0% tax credit
- To get 30% tax credit for residential, explicitly set `ownership_type="lease"`
- Commercial/Industrial defaults to 30% tax credit (may need adjustment based on specific programs)

## Testing Recommendations

1. Test residential purchase → should return 0% tax credit
2. Test residential lease → should return 30% tax credit
3. Test commercial → should return 30% tax credit
4. Verify policy_notice appears in optimization results
5. Verify analysis_years: 25 for residential, 20 for commercial
6. Verify discount_rate = 0.07 and elec_escalation_rate = 0.04

