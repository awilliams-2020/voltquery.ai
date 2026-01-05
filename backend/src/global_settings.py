"""
GlobalSettings: Centralized financial and analysis parameters for all bundles.

This class provides consistent financial context across all tools:
- Federal Tax Credit with policy rules (2026 rules: 0% for residential purchase, 30% for lease)
- Analysis period (25 years residential, 20 years commercial)
- Inflation rates (4% electricity escalation, 7% discount rate)
- Other financial parameters
"""

from typing import Optional, Literal
from datetime import date
from pydantic import BaseModel, computed_field, field_validator


class GlobalSettings(BaseModel):
    """
    Global settings for financial analysis and calculations.
    These values are applied consistently across all bundles.
    
    Policy Rules (2026 OBBBA):
    - Residential Purchase ITC: 0% (expired in 2025)
    - Residential Lease ITC: 30%
    - Commercial ITC: 30% if construction_start_date < '2026-07-04', otherwise subject to phaseout
    """
    
    # Policy parameters (used to determine tax credit)
    property_type: Literal["residential", "commercial", "industrial"] = "residential"
    ownership_type: Literal["purchase", "lease"] = "purchase"
    tax_year: int = 2026  # Tax year for policy rules
    construction_start_date: Optional[str] = None  # Format: 'YYYY-MM-DD' for commercial ITC calculation
    
    # Explicit ITC rates (2026 OBBBA)
    residential_purchase_itc: float = 0.0  # 0% - expired in 2025
    residential_lease_itc: float = 0.30  # 30% - still eligible
    commercial_itc: float = 0.30  # 30% if construction_start_date < '2026-07-04'
    
    @field_validator('construction_start_date')
    @classmethod
    def validate_construction_start_date(cls, v):
        """Validate construction_start_date format."""
        if v is None:
            return v
        try:
            date.fromisoformat(v)
            return v
        except ValueError:
            raise ValueError(f"construction_start_date must be in 'YYYY-MM-DD' format, got: {v}")
    
    # Analysis period defaults (years)
    residential_analysis_years: int = 25
    commercial_analysis_years: int = 20
    
    # Discount rates (fraction) - Updated to 7%
    offtaker_discount_rate_fraction: float = 0.07  # 7%
    owner_discount_rate_fraction: float = 0.07
    
    # Tax rates (fraction)
    offtaker_tax_rate_fraction: float = 0.26  # 26%
    owner_tax_rate_fraction: float = 0.26
    
    # Escalation rates (fraction)
    om_cost_escalation_rate_fraction: float = 0.025  # 2.5% O&M escalation
    elec_cost_escalation_rate_fraction: float = 0.04  # 4% electricity cost escalation (updated)
    
    # Third-party ownership
    third_party_ownership: bool = False
    
    # Solar system defaults
    default_solar_system_capacity_kw: float = 5.0
    solar_installed_cost_per_kw: float = 2783.0  # $/kW
    solar_om_cost_per_kw: float = 32.0  # $/kW/year
    
    # Storage system defaults
    storage_max_kw: float = 500.0
    storage_max_kwh: float = 2000.0
    
    @computed_field
    @property
    def federal_tax_credit_rate(self) -> float:
        """
        Calculate federal tax credit rate based on 2026 OBBBA policy rules.
        
        Policy Rules (2026 OBBBA):
        - Residential Purchase: 0% (expired in 2025)
        - Residential Lease: 30%
        - Commercial: 30% if construction_start_date < '2026-07-04', otherwise subject to phaseout
        
        Returns:
            Federal tax credit rate as a fraction (0.0 to 0.30)
        """
        if self.property_type == "residential":
            if self.ownership_type == "purchase":
                # Residential purchase: Tax credit expired in 2025, 0% for 2026+
                return self.residential_purchase_itc
            elif self.ownership_type == "lease":
                # Residential lease: Still eligible for 30% tax credit
                return self.residential_lease_itc
        # Commercial/Industrial: Check construction start date
        elif self.property_type in ["commercial", "industrial"]:
            if self.construction_start_date:
                try:
                    start_date = date.fromisoformat(self.construction_start_date)
                    cutoff_date = date(2026, 7, 4)
                    if start_date < cutoff_date:
                        # Construction started before July 4, 2026 - eligible for 30% ITC
                        return self.commercial_itc
                    else:
                        # Construction started on or after July 4, 2026 - subject to phaseout
                        # For now, return 30% but this could be adjusted based on phaseout schedule
                        return self.commercial_itc
                except (ValueError, TypeError):
                    # Invalid date format, default to commercial ITC
                    return self.commercial_itc
            # No construction date provided, default to commercial ITC
            return self.commercial_itc
        # Default fallback
        return 0.30
    
    @computed_field
    @property
    def analysis_years(self) -> int:
        """
        Get analysis period based on property type.
        
        Returns:
            Analysis period in years (25 for residential, 20 for commercial)
        """
        if self.property_type == "residential":
            return self.residential_analysis_years
        else:
            return self.commercial_analysis_years
    
    @computed_field
    @property
    def policy_notice(self) -> str:
        """
        Generate policy notice for user transparency.
        
        Returns:
            Policy notice string explaining tax credit rules
        """
        if self.property_type == "residential":
            if self.ownership_type == "purchase":
                return (
                    "The 30% Residential Tax Credit expired in 2025; "
                    "this calculation uses 2026 OBBBA rules (0% for purchase, 30% for lease)."
                )
            elif self.ownership_type == "lease":
                return (
                    "This calculation uses the 2026 OBBBA Residential Tax Credit rules: "
                    "30% federal tax credit applies to leased residential solar systems."
                )
        # Commercial/Industrial
        if self.construction_start_date:
            try:
                start_date = date.fromisoformat(self.construction_start_date)
                cutoff_date = date(2026, 7, 4)
                if start_date < cutoff_date:
                    return (
                        f"This calculation uses 2026 OBBBA tax credit rules: "
                        f"{self.federal_tax_credit_rate*100:.0f}% federal tax credit applies to {self.property_type} systems "
                        f"with construction start date {self.construction_start_date} (before July 4, 2026 cutoff)."
                    )
                else:
                    return (
                        f"This calculation uses 2026 OBBBA tax credit rules: "
                        f"{self.federal_tax_credit_rate*100:.0f}% federal tax credit applies to {self.property_type} systems "
                        f"with construction start date {self.construction_start_date} (on or after July 4, 2026 - subject to phaseout)."
                    )
            except (ValueError, TypeError):
                pass
        return (
            f"This calculation uses {self.tax_year} OBBBA tax credit rules: "
            f"{self.federal_tax_credit_rate*100:.0f}% federal tax credit applies to {self.property_type} systems."
        )
    
    def get_financial_params(
        self,
        property_type: Optional[Literal["residential", "commercial", "industrial"]] = None,
        ownership_type: Optional[Literal["purchase", "lease"]] = None,
        construction_start_date: Optional[str] = None
    ) -> dict:
        """
        Get financial parameters for a specific property/ownership type.
        
        Args:
            property_type: Override property type (uses instance default if None)
            ownership_type: Override ownership type (uses instance default if None)
            construction_start_date: Override construction start date (uses instance default if None)
            
        Returns:
            Dictionary with financial parameters
        """
        # Create temporary settings with overrides
        temp_settings = self.model_copy()
        if property_type:
            temp_settings.property_type = property_type
        if ownership_type:
            temp_settings.ownership_type = ownership_type
        if construction_start_date:
            temp_settings.construction_start_date = construction_start_date
        
        return {
            "analysis_years": temp_settings.analysis_years,
            "federal_tax_credit_rate": temp_settings.federal_tax_credit_rate,
            "offtaker_discount_rate_fraction": temp_settings.offtaker_discount_rate_fraction,
            "owner_discount_rate_fraction": temp_settings.owner_discount_rate_fraction,
            "offtaker_tax_rate_fraction": temp_settings.offtaker_tax_rate_fraction,
            "owner_tax_rate_fraction": temp_settings.owner_tax_rate_fraction,
            "om_cost_escalation_rate_fraction": temp_settings.om_cost_escalation_rate_fraction,
            "elec_cost_escalation_rate_fraction": temp_settings.elec_cost_escalation_rate_fraction,
            "third_party_ownership": temp_settings.third_party_ownership,
            "policy_notice": temp_settings.policy_notice,
        }
    
    class Config:
        """Pydantic config."""
        frozen = False  # Allow updates for property_type/ownership_type


# Global singleton instance
_global_settings: Optional[GlobalSettings] = None


def get_global_settings() -> GlobalSettings:
    """
    Get the global settings instance (singleton pattern).
    
    Returns:
        GlobalSettings instance
    """
    global _global_settings
    if _global_settings is None:
        _global_settings = GlobalSettings()
    return _global_settings


def set_global_settings(settings: GlobalSettings) -> None:
    """
    Set the global settings instance (useful for testing or customization).
    
    Args:
        settings: GlobalSettings instance to use
    """
    global _global_settings
    _global_settings = settings

