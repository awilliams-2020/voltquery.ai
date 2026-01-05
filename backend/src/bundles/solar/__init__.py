"""
Solar Bundle: Solar energy production estimates and analysis.

This bundle provides:
- Solar production estimates via NREL PVWatts API
- System sizing calculations
- Production forecasting
"""

from typing import Optional
from llama_index.core.tools import QueryEngineTool
from llama_index.core.query_engine import BaseQueryEngine
from llama_index.core.callbacks import CallbackManager
from app.services.nrel_client import NRELClient
from app.services.location_service import LocationService
from src.global_settings import get_global_settings
from src.bundles.solar.query_engine import SolarQueryEngine


def get_tool(
    llm,
    callback_manager: Optional[CallbackManager] = None,
    nrel_client: Optional[NRELClient] = None,
    location_service: Optional[LocationService] = None
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
        
    Returns:
        QueryEngineTool configured for solar production queries
    """
    # Initialize dependencies if not provided
    if nrel_client is None:
        nrel_client = NRELClient()
    if location_service is None:
        from app.services.location_service import LocationService
        location_service = LocationService()
    
    # Get global settings
    settings = get_global_settings()
    
    # Create query engine
    query_engine = SolarQueryEngine(
        llm=llm,
        nrel_client=nrel_client,
        location_service=location_service,
        callback_manager=callback_manager,
        default_system_capacity_kw=settings.default_solar_system_capacity_kw
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

