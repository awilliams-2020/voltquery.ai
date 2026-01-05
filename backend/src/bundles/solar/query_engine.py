"""
Solar Query Engine: Handles solar production queries.

Extracts location and system capacity from queries and calls NREL PVWatts API.
"""

import re
import json
from typing import Dict, Any, Optional
from llama_index.core.query_engine import BaseQueryEngine
from llama_index.core.schema import NodeWithScore, TextNode, QueryBundle
from llama_index.core.base.response.schema import Response
from llama_index.core.callbacks import CallbackManager
from app.services.nrel_client import NRELClient
from app.services.location_service import LocationService


class SolarQueryEngine(BaseQueryEngine):
    """
    Query engine for solar production estimates.
    
    Extracts location and system capacity from queries and returns
    formatted solar production data from NREL PVWatts API.
    """
    
    def __init__(
        self,
        llm,
        nrel_client: NRELClient,
        location_service: LocationService,
        callback_manager: Optional[CallbackManager] = None,
        default_system_capacity_kw: float = 5.0
    ):
        self.llm = llm
        self.nrel_client = nrel_client
        self.location_service = location_service
        self.default_system_capacity_kw = default_system_capacity_kw
        super().__init__(callback_manager=callback_manager)
    
    def _get_prompt_modules(self):
        """Get prompt sub-modules. Returns empty dict since we don't use prompts."""
        return {}
    
    def _query(self, query_bundle: QueryBundle) -> Response:
        """Synchronous query - not used but required by base class."""
        raise NotImplementedError("Use async query instead")
    
    async def _aquery(self, query_bundle: QueryBundle) -> Response:
        """Async query that extracts location and system capacity, then calls NREL API."""
        query_str = query_bundle.query_str
        
        # Extract location from query string
        location = None
        system_capacity = self.default_system_capacity_kw
        
        # Try to extract zip code (5 digits)
        zip_match = re.search(r'\b\d{5}\b', query_str)
        if zip_match:
            location = zip_match.group(0)
        
        # Try to extract city, state pattern
        if not location:
            city_state_match = re.search(r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s*([A-Z]{2})', query_str)
            if city_state_match:
                location = f"{city_state_match.group(1)}, {city_state_match.group(2)}"
        
        # Try to extract coordinates (lat,lon)
        if not location:
            coord_match = re.search(r'(-?\d+\.?\d*),\s*(-?\d+\.?\d*)', query_str)
            if coord_match:
                lat = float(coord_match.group(1))
                lon = float(coord_match.group(2))
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    location = f"{lat},{lon}"
        
        # Try to extract system capacity if mentioned (e.g., "5 kW", "10kW")
        capacity_match = re.search(r'(\d+(?:\.\d+)?)\s*kw', query_str, re.IGNORECASE)
        if capacity_match:
            system_capacity = float(capacity_match.group(1))
        
        # If no location found, use the whole query string as location
        # The geocoding function will try to parse it
        if not location:
            location = query_str.strip()
        
        try:
            # Get solar estimate
            result = await self._get_solar_estimate(location, system_capacity)
            
            # Format response
            if isinstance(result, dict):
                if "error" in result:
                    response_text = f"Error: {result.get('message', result.get('error', 'Unknown error'))}"
                else:
                    response_text = self._format_solar_response(result, location, system_capacity)
            elif isinstance(result, str):
                response_text = result
            else:
                response_text = json.dumps(result, indent=2) if result else "No result"
        except Exception as e:
            response_text = f"Error getting solar estimate: {str(e)}"
        
        # Create response node
        node = TextNode(text=response_text)
        node_with_score = NodeWithScore(node=node, score=1.0)
        
        return Response(
            response=response_text,
            source_nodes=[node_with_score]
        )
    
    async def _get_solar_estimate(
        self,
        location: str,
        system_capacity: float
    ) -> Dict[str, Any]:
        """
        Get solar estimate for a location.
        
        Args:
            location: Location string (zip code, "city, state", or "lat,lon")
            system_capacity: System capacity in kW
            
        Returns:
            Dictionary containing solar production estimates
        """
        try:
            # Check if location is already lat/lon format
            if "," in location:
                parts = location.split(",")
                if len(parts) == 2:
                    try:
                        lat = float(parts[0].strip())
                        lon = float(parts[1].strip())
                        # Basic validation
                        if -90 <= lat <= 90 and -180 <= lon <= 180:
                            return await self.nrel_client.get_solar_estimate(
                                lat=lat,
                                lon=lon,
                                system_capacity=system_capacity
                            )
                    except ValueError:
                        pass  # Not lat/lon, continue to geocode
            
            # Geocode location to get lat/lon
            lat, lon = await self.nrel_client._geocode_location(location)
            
            # Get solar estimate
            return await self.nrel_client.get_solar_estimate(
                lat=lat,
                lon=lon,
                system_capacity=system_capacity
            )
        except Exception as e:
            return {
                "error": str(e),
                "location": location,
                "message": f"Failed to get solar estimate for location '{location}': {str(e)}"
            }
    
    def _format_solar_response(
        self,
        result: Dict[str, Any],
        location: str,
        system_capacity: float
    ) -> str:
        """
        Format solar production data into a readable response.
        
        Args:
            result: NREL PVWatts API response
            location: Location string
            system_capacity: System capacity in kW
            
        Returns:
            Formatted response string
        """
        ac_annual = result.get("ac_annual", "N/A")
        ac_monthly = result.get("ac_monthly", [])
        
        response_parts = [
            "SOLAR PRODUCTION DATA (from NREL PVWatts API):",
            f"Location: {location}",
            f"System Capacity: {system_capacity} kW",
            f"Annual AC Energy Production: {ac_annual} kWh/year",
        ]
        
        if isinstance(ac_monthly, list) and len(ac_monthly) == 12:
            monthly_avg = sum(ac_monthly) / 12
            response_parts.append(f"Average Monthly Production: {monthly_avg:.1f} kWh/month")
            response_parts.append("\nMonthly Breakdown:")
            months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", 
                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            for month, production in zip(months, ac_monthly):
                response_parts.append(f"  {month}: {production:.1f} kWh")
        
        # Add other useful fields if available
        if "solrad_annual" in result:
            response_parts.append(f"\nAnnual Solar Radiation: {result['solrad_annual']} kWh/m²/day")
        if "capacity_factor" in result:
            response_parts.append(f"Capacity Factor: {result['capacity_factor']:.1f}%")
        
        return "\n".join(response_parts)

