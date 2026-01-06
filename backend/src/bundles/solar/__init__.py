"""
Solar Bundle: Solar energy production estimates and analysis.

This bundle provides:
- Solar production estimates via NREL PVWatts API
- System sizing calculations
- Production forecasting
"""

from typing import Optional, List
from llama_index.core.tools import QueryEngineTool
from llama_index.core.query_engine import BaseQueryEngine
from llama_index.core.callbacks import CallbackManager
from llama_index.core.vector_stores import MetadataFilter
from app.services.nrel_client import NRELClient
from app.services.location_service import LocationService
from src.global_settings import get_global_settings
from src.bundles.solar.query_engine import SolarQueryEngine


def get_tool(
    llm,
    callback_manager: Optional[CallbackManager] = None,
    nrel_client: Optional[NRELClient] = None,
    location_service: Optional[LocationService] = None,
    location_filters: Optional[List[MetadataFilter]] = None
) -> QueryEngineTool:
    """
    Get the solar production tool as a QueryEngineTool.
    
    This tool provides solar energy production estimates for a given location
    and system size using the NREL PVWatts API.
    
    Args:
        llm: LLM instance for query processing
        callback_manager: Optional callback manager for observability
        nrel_client: Optional NREL client (creates new if not provided)
        location_service: Optional location service (creates new if not provided)
        location_filters: Optional location-based metadata filters (used to extract zipcode)
        
    Returns:
        QueryEngineTool configured for solar production queries
    """
    # Initialize dependencies if not provided
    if nrel_client is None:
        nrel_client = NRELClient()
    if location_service is None:
        from app.services.location_service import LocationService
        location_service = LocationService()
    
    # Extract zipcode from location_filters if provided
    # This allows the solar tool to use the zipcode from the user's query even if
    # the sub-question doesn't explicitly mention it
    default_location = None
    if location_filters and len(location_filters) > 0:
        print(f"[SolarTool] location_filters provided: {len(location_filters)} filter(s)")
        for i, filter_obj in enumerate(location_filters):
            try:
                # Debug: Print filter object type and attributes
                print(f"[SolarTool] Filter {i}: type={type(filter_obj)}, dir={[attr for attr in dir(filter_obj) if not attr.startswith('_')]}")
                
                # MetadataFilter objects have 'key' and 'value' attributes
                if hasattr(filter_obj, 'key') and hasattr(filter_obj, 'value'):
                    filter_key = filter_obj.key
                    filter_value = filter_obj.value
                    print(f"[SolarTool] Filter {i}: key={filter_key}, value={filter_value}, type(key)={type(filter_key)}, type(value)={type(filter_value)}")
                    
                    # Check if this is a zipcode filter
                    if filter_key in ['zip', 'queried_zip'] and filter_value:
                        default_location = str(filter_value)
                        print(f"[SolarTool] ✓ Extracted zipcode from location_filters: {default_location}")
                        break
                else:
                    print(f"[SolarTool] Filter {i} missing 'key' or 'value' attribute")
            except Exception as e:
                # If filter_obj doesn't have expected structure, skip it
                print(f"[SolarTool] Error accessing filter {i} attributes: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
                continue
    else:
        print(f"[SolarTool] No location_filters provided (location_filters={location_filters})")
    
    if default_location:
        print(f"[SolarTool] ✓ Using default_location: {default_location}")
    else:
        print(f"[SolarTool] ✗ No default_location extracted - will try to extract from query string")
    
    # Get global settings
    settings = get_global_settings()
    
    # Create query engine
    query_engine = SolarQueryEngine(
        llm=llm,
        nrel_client=nrel_client,
        location_service=location_service,
        callback_manager=callback_manager,
        default_system_capacity_kw=settings.default_solar_system_capacity_kw,
        default_location=default_location
    )
    
    # Create tool with high-quality metadata
    tool = QueryEngineTool.from_defaults(
        query_engine=query_engine,
        name="solar_production_tool",
        description=(
            "SOLAR DOMAIN: Use this tool for questions about solar energy production, "
            "solar panel output, solar generation, solar savings, offsetting electricity costs "
            "with solar, calculating solar payback periods, and estimating solar system performance. "
            "The tool uses NREL PVWatts API to provide accurate production estimates based on location "
            "and system size. "
            "Location can be specified as a zip code (e.g., '80202'), city and state (e.g., 'Denver, CO'), "
            "or coordinates (e.g., '39.7392,-104.9903'). "
            "System capacity defaults to 5 kW but can be specified in the question (e.g., '10kW system'). "
            "This tool provides annual and monthly kWh production estimates, capacity factors, "
            "and solar radiation data."
        )
    )
    
    return tool

