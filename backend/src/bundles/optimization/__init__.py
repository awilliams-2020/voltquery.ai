"""
Optimization Bundle: REopt optimization for solar/storage system sizing and financial analysis.

This bundle provides:
- Optimal solar and storage system sizing
- NPV (Net Present Value) calculations
- ROI (Return on Investment) analysis
- Financial optimization using NREL REopt v3 API
"""

import re
import json
from typing import Optional, Dict, Any, List
from llama_index.core.tools import QueryEngineTool
from llama_index.core.query_engine import BaseQueryEngine
from llama_index.core.callbacks import CallbackManager
from llama_index.core.schema import NodeWithScore, TextNode, QueryBundle
from llama_index.core.base.response.schema import Response
from llama_index.core.vector_stores import MetadataFilter
from app.services.reopt_service import REoptService
from app.services.nrel_client import NRELClient
from src.global_settings import get_global_settings

# State name to abbreviation mapping
STATE_ABBREVIATIONS = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
    "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "washington dc": "DC", "dc": "DC"
}


class OptimizationQueryEngine(BaseQueryEngine):
    """
    Query engine for REopt optimization queries.
    
    Extracts location, load profile type, and additional load from queries
    and returns formatted optimization results from NREL REopt API.
    """
    
    def __init__(
        self,
        llm,
        reopt_service: REoptService,
        nrel_client: Optional[NRELClient] = None,
        callback_manager: Optional[CallbackManager] = None,
        default_location: Optional[str] = None,
        default_city: Optional[str] = None,
        default_state: Optional[str] = None
    ):
        self.llm = llm
        self.reopt_service = reopt_service
        self.nrel_client = nrel_client or NRELClient()
        self.settings = get_global_settings()
        self.default_location = default_location
        self.default_city = default_city
        self.default_state = default_state
        super().__init__(callback_manager=callback_manager)
    
    def _get_prompt_modules(self):
        """Get prompt sub-modules. Returns empty dict since we don't use prompts."""
        return {}
    
    def _query(self, query_bundle: QueryBundle) -> Response:
        """Synchronous query - not used but required by base class."""
        raise NotImplementedError("Use async query instead")
    
    async def _aquery(self, query_bundle: QueryBundle) -> Response:
        """Async query that extracts parameters and calls REopt API."""
        query_str = query_bundle.query_str
        query_lower = query_str.lower()
        
        # Extract location, load_profile_type, urdb_label, additional_load_kw, property_type, and ownership_type
        location = None
        load_profile_type = "residential"  # Default
        urdb_label = None
        additional_load_kw = 0.0
        property_type = None
        ownership_type = None
        
        # Detect if this is a purchase or lease query from parallel scenario approach
        # The orchestrator will call this tool twice with explicit purchase/lease keywords
        is_purchase_query = any(keyword in query_lower for keyword in [
            "purchase", "buy", "buying", "purchasing", "0% itc", "zero itc"
        ])
        is_lease_query = any(keyword in query_lower for keyword in [
            "lease", "leasing", "leased", "ppa", "30% itc", "thirty percent itc"
        ])
        
        # Try to extract zip code (5 digits) - most reliable
        zip_match = re.search(r'\b\d{5}\b', query_str)
        if zip_match:
            location = zip_match.group(0)
        
        # Try to extract city, state pattern (e.g., "Denver, CO" or "Atlanta, Georgia")
        if not location:
            # First try 2-letter state abbreviation (e.g., "Denver, CO")
            city_state_match = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s*([A-Z]{2})\b', query_str)
            if city_state_match:
                location = f"{city_state_match.group(1)}, {city_state_match.group(2)}"
            else:
                # Try full state name (e.g., "Atlanta, Georgia")
                city_state_full_match = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', query_str)
                if city_state_full_match:
                    city = city_state_full_match.group(1)
                    state_name = city_state_full_match.group(2).lower()
                    # Convert state name to abbreviation
                    state_abbr = STATE_ABBREVIATIONS.get(state_name)
                    if state_abbr:
                        location = f"{city}, {state_abbr}"
                    else:
                        # If we can't find abbreviation, use the full name (geocoding should handle it)
                        location = f"{city}, {city_state_full_match.group(2)}"
        
        # Try to extract coordinates (lat,lon)
        if not location:
            coord_match = re.search(r'(-?\d+\.?\d*),\s*(-?\d+\.?\d*)', query_str)
            if coord_match:
                lat_val = float(coord_match.group(1))
                lon_val = float(coord_match.group(2))
                if -90 <= lat_val <= 90 and -180 <= lon_val <= 180:
                    location = f"{lat_val},{lon_val}"
        
        # Try to use default city/state from location_filters if available
        if not location and self.default_city and self.default_state:
            location = f"{self.default_city}, {self.default_state}"
        
        # Policy-Aware Financial Strategy: Extract lease/business keywords
        # Note: query_lower already set above, but ensure it's fresh
        query_lower = query_str.lower()
        
        # Check for residential keywords first (homeowner, residential, home, house)
        # These take priority over commercial keywords to avoid false positives
        # Use word boundaries to avoid false matches (e.g., "house" matching in "warehouse")
        residential_patterns = [
            r'\bhomeowner\b', r'\bhome owner\b', r'\bresidential\b', r'\bhome\b', 
            r'\bhouse\b', r'\bhousehold\b', r'\bmy home\b', r'\bmy house\b', 
            r'\bresidential property\b'
        ]
        is_residential_keyword = any(re.search(pattern, query_lower) for pattern in residential_patterns)
        
        # Check for business/commercial keywords (but exclude if residential keywords present)
        # IMPORTANT: Exclude tax credit references - "commercial credit", "48e", etc. refer to tax credits, NOT property type
        # Only check for actual business property keywords, not tax credit terminology
        has_business_keywords = any(keyword in query_lower for keyword in [
            "business", "commercial", "commercial property", "industrial", "company", "corporation", 
            "corp", "llc", "enterprise", "facility", "warehouse", "office",
            "retail", "store", "shop", "restaurant", "retro-fit", "retrofit", "retro fit"
        ])
        
        # Exclude tax credit references from business detection
        # Only exclude if "commercial" appears WITH tax credit terms, not standalone "tax credit"
        has_tax_credit_refs = any(exclude in query_lower for exclude in [
            "commercial credit", "48e", "section 48e", "commercial tax credit",
            "section 25d", "25d"
        ])
        
        is_business = not is_residential_keyword and has_business_keywords and not has_tax_credit_refs
        
        # Debug logging - show what we detected
        print(f"[OptimizationTool] DEBUG: query_lower[:100]={query_lower[:100]}")
        print(f"[OptimizationTool] DEBUG: is_residential_keyword={is_residential_keyword}, has_business_keywords={has_business_keywords}, has_tax_credit_refs={has_tax_credit_refs}, is_business={is_business}")
        
        # Check for lease keywords (including PPA and third-party)
        # For parallel scenarios, prioritize explicit keywords from orchestrator
        is_lease = is_lease_query or any(keyword in query_lower for keyword in [
            "lease", "leasing", "leased", "rent", "renting", "rented",
            "ppa", "power purchase agreement", "third-party", "third party"
        ])
        
        # Determine property type and ownership type based on keywords
        # CRITICAL: Check business keywords FIRST before defaulting to residential
        # This ensures commercial/warehouse properties are detected even if residential keywords are absent
        if is_business:
            # Business/commercial property detected
            load_profile_type = "commercial"
            property_type = "commercial"
            if not is_lease:
                ownership_type = "purchase"  # Business purchase still gets 30% ITC
            else:
                ownership_type = "lease"
        elif "industrial" in query_lower:
            # Industrial property
            load_profile_type = "industrial"
            property_type = "industrial"
            ownership_type = "purchase" if not is_lease else "lease"
        elif is_residential_keyword:
            # Residential property
            load_profile_type = "residential"
            property_type = "residential"
            # Residential: extract ownership type explicitly
            # For parallel scenarios, prioritize explicit keywords from orchestrator
            if is_lease_query or is_lease:
                ownership_type = "lease"
            elif is_purchase_query or "purchase" in query_lower or "buy" in query_lower or "buying" in query_lower or "purchasing" in query_lower:
                ownership_type = "purchase"
            else:
                # Default residential to purchase (will get 0% ITC)
                ownership_type = "purchase"
        else:
            # Default to residential if unclear
            load_profile_type = "residential"
            property_type = "residential"
            ownership_type = "purchase"
        
        print(f"[OptimizationTool] property_type={property_type} | ownership_type={ownership_type} | load_profile={load_profile_type}")
        
        # Try to extract URDB label (usually a UUID or identifier)
        urdb_match = re.search(r'urdb[_\s]*label[:\s]+([a-zA-Z0-9_-]+)', query_str, re.IGNORECASE)
        if urdb_match:
            urdb_label = urdb_match.group(1)
        
        # Extract additional load (EV chargers, etc.)
        charger_patterns = [
            r'(\d+)\s*(?:DC\s*)?(?:Fast\s*)?(?:EV\s*)?(?:charging\s*)?chargers?\s*(?:of\s*)?(?:@\s*)?(\d+)\s*kw',
            r'(\d+)\s*(?:DC\s*)?(?:Fast\s*)?(?:EV\s*)?(?:charging\s*)?chargers?\s*(?:@\s*)?(\d+)\s*kw',
            r'(\d+)\s*kw\s*(?:DC\s*)?(?:Fast\s*)?(?:EV\s*)?(?:charging\s*)?chargers?',
            r'(\d+)\s*(?:DC\s*)?(?:Fast\s*)?(?:EV\s*)?(?:charging\s*)?chargers?\s*(?:each\s*)?(?:@\s*)?(\d+)\s*kw',
        ]
        for pattern in charger_patterns:
            match = re.search(pattern, query_str, re.IGNORECASE)
            if match:
                if len(match.groups()) == 2:
                    count = float(match.group(1))
                    kw_per_charger = float(match.group(2))
                    additional_load_kw = count * kw_per_charger
                else:
                    additional_load_kw = float(match.group(1))
                break
        
        # If no location found, try using default_location if provided
        if not location and self.default_location:
            location = self.default_location
        
        # If still no location found, raise an error
        if not location:
            response_text = (
                f"Could not extract location from query: '{query_str}'. "
                f"Please include a zip code (e.g., '45424'), city/state (e.g., 'Denver, CO'), "
                f"or coordinates (e.g., '39.7392,-104.9903') in your question."
            )
            node = TextNode(text=response_text)
            node_with_score = NodeWithScore(node=node, score=0.0)
            return Response(
                response=response_text,
                source_nodes=[node_with_score]
            )
        
        try:
            # Geocode location to get lat/lon
            lat, lon = await self.nrel_client._geocode_location(location)
            
            # Extract zip code if location is a zip code
            zip_code = None
            if location.isdigit() and len(location) == 5:
                zip_code = location
            
            # Determine if this is a lease-only query (not comparison)
            # If query explicitly mentions lease/PPA and doesn't ask for comparison, run lease-only
            is_lease_only_query = (
                (is_lease_query or is_lease) and 
                property_type == "residential" and
                not any(keyword in query_lower for keyword in [
                    "compare", "comparison", "vs", "versus", "both", "purchase and lease",
                    "buy or lease", "purchase or lease"
                ])
            )
            
            # Scenario Branching: Run dual scenarios for residential comparison queries, single for lease-only or commercial
            if property_type == "residential" and not is_lease_only_query:
                # Run scenario branching (Purchase vs Lease) for comparison queries
                print(f"[OptimizationTool] scenario_branching | type=residential | comparison=true")
                result = await self.reopt_service.run_reopt_scenario_branching(
                    lat=lat,
                    lon=lon,
                    load_profile_type=load_profile_type,
                    urdb_label=urdb_label,
                    zip_code=zip_code,
                    additional_load_kw=additional_load_kw,
                    property_type=property_type
                )
            else:
                # Lease-only or commercial: Run single scenario
                if is_lease_only_query:
                    # Single lease scenario for residential lease-only queries
                    print(f"[OptimizationTool] scenario=single | type=residential | ownership=lease")
                    result = await self.reopt_service.run_reopt_optimization(
                        lat=lat,
                        lon=lon,
                        load_profile_type=load_profile_type,
                        urdb_label=urdb_label,
                        zip_code=zip_code,
                        additional_load_kw=additional_load_kw,
                        property_type=property_type,
                        ownership_type="lease"
                    )
                else:
                    # Commercial: Run single scenario with policy flag
                    print(f"[OptimizationTool] scenario_branching | type={property_type}")
                    result = await self.reopt_service.run_reopt_scenario_branching(
                        lat=lat,
                        lon=lon,
                        load_profile_type=load_profile_type,
                        urdb_label=urdb_label,
                        zip_code=zip_code,
                        additional_load_kw=additional_load_kw,
                        property_type=property_type
                    )
            
            # Format response
            if isinstance(result, dict):
                if "error" in result:
                    response_text = f"Error: {result.get('message', result.get('error', 'Unknown error'))}"
                elif result.get("scenario_type") == "residential":
                    # Format dual scenario response
                    response_text = self._format_scenario_branching_response(
                        result, location, load_profile_type
                    )
                else:
                    # Format single scenario response (commercial)
                    response_text = self._format_optimization_response(
                        result.get("scenario", result), location, load_profile_type, property_type, ownership_type
                    )
            elif isinstance(result, str):
                response_text = result
            else:
                response_text = json.dumps(result, indent=2) if result else "No result"
        except Exception as e:
            response_text = f"Error running optimization: {str(e)}"
        
        # Create response node
        node = TextNode(text=response_text)
        node_with_score = NodeWithScore(node=node, score=1.0)
        
        return Response(
            response=response_text,
            source_nodes=[node_with_score]
        )
    
    def _format_optimization_response(
        self,
        result: Dict[str, Any],
        location: str,
        load_profile_type: str,
        property_type: Optional[str] = None,
        ownership_type: Optional[str] = None
    ) -> str:
        """
        Format REopt optimization results into a readable response.
        
        Args:
            result: REopt API response
            location: Location string
            load_profile_type: Load profile type
            
        Returns:
            Formatted response string
        """
        npv = result.get("npv")
        optimal_sizes = result.get("optimal_system_sizes", {})
        
        # Get financial parameters for display
        financial_params = self.settings.get_financial_params(
            property_type=property_type or load_profile_type.lower(),
            ownership_type=ownership_type
        )
        
        # Check if optimization returned no viable solution
        if (npv is not None and npv == 0.0) and (not optimal_sizes or all(v == 0.0 for v in optimal_sizes.values())):
            policy_notice_text = ""
            policy_notice = result.get("policy_notice", financial_params.get("policy_notice", ""))
            if policy_notice:
                policy_notice_text = f"\n\nPolicy Notice: {policy_notice}\n"
            
            # Add policy_warning if available
            policy_warning_text = ""
            policy_warning = result.get("policy_warning")
            if policy_warning:
                policy_warning_text = f"\n⚠️ POLICY WARNING: {policy_warning}\n"
            
            return (
                f"Based on the REopt optimization analysis for {location}:\n\n"
                "The optimization model indicates that a solar-plus-storage system is not economically "
                "viable under the current conditions. This typically means:\n\n"
                "• The utility rates and solar/storage costs make grid electricity more cost-effective\n"
                "• The load profile and tariff structure don't justify the upfront investment\n"
                f"• The financial parameters (discount rate: {financial_params['offtaker_discount_rate_fraction']*100:.2f}%, "
                f"tax credit: {financial_params['federal_tax_credit_rate']*100:.0f}%, "
                f"analysis period: {financial_params['analysis_years']} years) don't favor solar/storage"
                f"{policy_notice_text}{policy_warning_text}\n"
                "**Recommendations:**\n"
                "• Consider reviewing your utility rate structure - time-of-use rates may improve viability\n"
                "• Explore available tax credits, rebates, or incentives that could improve the economics\n"
                "• Evaluate if your load profile matches your actual usage patterns\n"
                "• Consider a smaller system size or different financing options\n\n"
                "The optimization completed successfully, but the model determined that purchasing electricity "
                "from the utility is currently the most cost-effective option over the analysis period."
            )
        
        # Format REopt optimization data when results are available
        response_parts = [
            "REOPT OPTIMIZATION RESULTS (from NREL REopt v3 API):",
            f"Location: {location}",
            f"Load Profile Type: {load_profile_type}",
            f"Analysis Period: {financial_params['analysis_years']} years",
            f"Federal Tax Credit: {financial_params['federal_tax_credit_rate']*100:.0f}%",
        ]
        
        # Add policy notice if available
        policy_notice = result.get("policy_notice", financial_params.get("policy_notice", ""))
        if policy_notice:
            response_parts.append(f"\nPolicy Notice: {policy_notice}")
        
        # Add policy_warning (July 4th Safe Harbor) if available - CRITICAL for LLM to use
        policy_warning = result.get("policy_warning")
        if policy_warning:
            response_parts.append(f"\n⚠️ POLICY WARNING: {policy_warning}")
        
        if npv is not None:
            response_parts.append(f"\nNet Present Value (NPV): ${npv:,.2f}")
        
        # Add recommended_size_kw (primary recommendation)
        recommended_size_kw = result.get("recommended_size_kw")
        if recommended_size_kw is not None and recommended_size_kw > 0:
            response_parts.append(f"\nRecommended Solar System Size: {recommended_size_kw:.2f} kW")
        
        if optimal_sizes:
            response_parts.append("\nOptimal System Sizes:")
            if "pv_kw" in optimal_sizes and optimal_sizes.get("pv_kw", 0) > 0:
                response_parts.append(f"  Solar PV: {optimal_sizes['pv_kw']:.2f} kW")
            if "storage_kw" in optimal_sizes and optimal_sizes.get("storage_kw", 0) > 0:
                response_parts.append(f"  Storage Power: {optimal_sizes['storage_kw']:.2f} kW")
            if "storage_kwh" in optimal_sizes and optimal_sizes.get("storage_kwh", 0) > 0:
                response_parts.append(f"  Storage Capacity: {optimal_sizes['storage_kwh']:.2f} kWh")
        
        return "\n".join(response_parts)
    
    def _format_scenario_branching_response(
        self,
        result: Dict[str, Any],
        location: str,
        load_profile_type: str
    ) -> str:
        """
        Format scenario branching results (Purchase vs Lease) into a readable response.
        
        Args:
            result: Scenario branching result dictionary with scenario_a and scenario_b
            location: Location string
            load_profile_type: Load profile type
            
        Returns:
            Formatted response string with side-by-side comparison
        """
        scenario_a = result.get("scenario_a", {})
        scenario_b = result.get("scenario_b", {})
        
        # Get financial parameters for display
        financial_params = self.settings.get_financial_params(
            property_type="residential",
            ownership_type="purchase"
        )
        
        response_parts = [
            "REOPT SCENARIO BRANCHING RESULTS (2026 OBBBA Policy Comparison):",
            f"Location: {location}",
            f"Load Profile Type: {load_profile_type}",
            f"Analysis Period: {financial_params['analysis_years']} years (both scenarios)",
            "",
            "=" * 60,
            "SCENARIO A: PURCHASE (0% Federal Tax Credit)",
            "=" * 60,
            "Federal Tax Credit: 0% (expired in 2025 per 2026 OBBBA rules)",
            f"Ownership Type: {scenario_a.get('ownership_type', 'purchase').title()}",
        ]
        
        npv_a = scenario_a.get("npv")
        if npv_a is not None:
            response_parts.append(f"Net Present Value (NPV): ${npv_a:,.2f}")
        
        recommended_size_a = scenario_a.get("recommended_size_kw")
        if recommended_size_a is not None and recommended_size_a > 0:
            response_parts.append(f"Recommended Solar System Size: {recommended_size_a:.2f} kW")
        
        optimal_sizes_a = scenario_a.get("optimal_system_sizes", {})
        if optimal_sizes_a:
            response_parts.append("\nOptimal System Sizes:")
            if "pv_kw" in optimal_sizes_a and optimal_sizes_a.get("pv_kw", 0) > 0:
                response_parts.append(f"  Solar PV: {optimal_sizes_a['pv_kw']:.2f} kW")
            if "storage_kw" in optimal_sizes_a and optimal_sizes_a.get("storage_kw", 0) > 0:
                response_parts.append(f"  Storage Power: {optimal_sizes_a['storage_kw']:.2f} kW")
            if "storage_kwh" in optimal_sizes_a and optimal_sizes_a.get("storage_kwh", 0) > 0:
                response_parts.append(f"  Storage Capacity: {optimal_sizes_a['storage_kwh']:.2f} kWh")
        
        policy_notice_a = scenario_a.get("policy_notice", "")
        if policy_notice_a:
            response_parts.append(f"\nPolicy Notice: {policy_notice_a}")
        
        response_parts.extend([
            "",
            "=" * 60,
            "SCENARIO B: LEASE (30% Federal Tax Credit)",
            "=" * 60,
            "Federal Tax Credit: 30% (PPA provider receives credit)",
            f"Ownership Type: {scenario_b.get('ownership_type', 'lease').title()}/PPA",
        ])
        
        npv_b = scenario_b.get("npv")
        if npv_b is not None:
            response_parts.append(f"Net Present Value (NPV): ${npv_b:,.2f}")
        
        recommended_size_b = scenario_b.get("recommended_size_kw")
        if recommended_size_b is not None and recommended_size_b > 0:
            response_parts.append(f"Recommended Solar System Size: {recommended_size_b:.2f} kW")
        
        optimal_sizes_b = scenario_b.get("optimal_system_sizes", {})
        if optimal_sizes_b:
            response_parts.append("\nOptimal System Sizes:")
            if "pv_kw" in optimal_sizes_b and optimal_sizes_b.get("pv_kw", 0) > 0:
                response_parts.append(f"  Solar PV: {optimal_sizes_b['pv_kw']:.2f} kW")
            if "storage_kw" in optimal_sizes_b and optimal_sizes_b.get("storage_kw", 0) > 0:
                response_parts.append(f"  Storage Power: {optimal_sizes_b['storage_kw']:.2f} kW")
            if "storage_kwh" in optimal_sizes_b and optimal_sizes_b.get("storage_kwh", 0) > 0:
                response_parts.append(f"  Storage Capacity: {optimal_sizes_b['storage_kwh']:.2f} kWh")
        
        policy_notice_b = scenario_b.get("policy_notice", "")
        if policy_notice_b:
            response_parts.append(f"\nPolicy Notice: {policy_notice_b}")
        
        # Comparison summary
        response_parts.extend([
            "",
            "=" * 60,
            "COMPARISON SUMMARY",
            "=" * 60,
        ])
        
        if npv_a is not None and npv_b is not None:
            npv_diff = npv_b - npv_a
            response_parts.append(f"NPV Difference (Lease - Purchase): ${npv_diff:,.2f}")
            if npv_diff > 0:
                response_parts.append(f"✓ Lease scenario shows ${npv_diff:,.2f} higher NPV due to 30% tax credit")
            elif npv_diff < 0:
                response_parts.append(f"⚠ Purchase scenario shows ${abs(npv_diff):,.2f} higher NPV")
            else:
                response_parts.append("Both scenarios show similar NPV")
        
        response_parts.extend([
            "",
            "2026 OBBBA POLICY CONTEXT:",
            "The 30% Residential Tax Credit expired in 2025 for homeowner purchases.",
            "However, leased/PPA systems remain eligible because the provider (not the homeowner)",
            "receives the 30% federal tax credit. This makes lease scenarios more viable for",
            "homeowners in 2026, as the provider can pass savings through lower lease rates.",
        ])
        
        return "\n".join(response_parts)


def get_tool(
    llm,
    reopt_service: REoptService,
    nrel_client: Optional[NRELClient] = None,
    callback_manager: Optional[CallbackManager] = None,
    location_filters: Optional[List[MetadataFilter]] = None
) -> QueryEngineTool:
    """
    Get the optimization tool as a QueryEngineTool.
    
    This tool provides REopt optimization analysis for solar/storage system sizing
    and financial analysis using the NREL REopt v3 API.
    
    Args:
        llm: LLM instance for query processing
        reopt_service: REopt service instance
        nrel_client: Optional NREL client (creates new if not provided)
        callback_manager: Optional callback manager for observability
        location_filters: Optional location-based metadata filters (used to extract zipcode)
        
    Returns:
        QueryEngineTool configured for optimization queries
    """
    # Extract location information from location_filters if provided
    default_location = None
    default_city = None
    default_state = None
    if location_filters:
        for filter_obj in location_filters:
            if hasattr(filter_obj, 'key') and hasattr(filter_obj, 'value'):
                filter_key = filter_obj.key
                filter_value = filter_obj.value
                if filter_key in ['zip', 'queried_zip']:
                    default_location = str(filter_value)
                elif filter_key == 'city':
                    default_city = str(filter_value)
                elif filter_key == 'state':
                    # Convert state name to abbreviation if needed
                    state_val = str(filter_value)
                    state_lower = state_val.lower()
                    if state_lower in STATE_ABBREVIATIONS:
                        default_state = STATE_ABBREVIATIONS[state_lower]
                    elif len(state_val) == 2:
                        default_state = state_val.upper()
                    else:
                        default_state = state_val
    
    # Create query engine
    query_engine = OptimizationQueryEngine(
        llm=llm,
        reopt_service=reopt_service,
        nrel_client=nrel_client,
        callback_manager=callback_manager,
        default_location=default_location,
        default_city=default_city,
        default_state=default_state
    )
    
    # Create tool with high-quality metadata
    tool = QueryEngineTool.from_defaults(
        query_engine=query_engine,
        name="optimization_tool",
        description=(
            "OPTIMIZATION DOMAIN: Use this tool for questions about investment analysis, system sizing, "
            "ROI (Return on Investment), optimal solar and storage system sizes, financial optimization, "
            "net present value (NPV), economic analysis of renewable energy systems, optimal energy system design, "
            "and cost-benefit analysis. "
            "Use this when the question contains words like 'investment', 'sizing', 'ROI', 'optimal size', "
            "'optimal system', 'NPV', 'net present value', 'financial analysis', 'economic analysis', "
            "'optimal design', 'cost-benefit', 'payback', 'optimize', or 'optimization'. "
            "The location can be a zip code (e.g., '80202'), city and state (e.g., 'Denver, CO'), "
            "or coordinates (e.g., '39.7392,-104.9903'). "
            "This tool uses NREL REopt v3 API to perform comprehensive optimization analysis with "
            "25-year analysis period, 30% federal tax credit, and standard financial parameters."
        )
    )
    
    return tool

