import os
import httpx
from typing import Dict, List, Any, Optional, Tuple
from pydantic_settings import BaseSettings
from datetime import timedelta
from app.services.cache_service import get_cache_service
from app.services.circuit_breaker import get_breaker_manager


class Settings(BaseSettings):
    nrel_api_key: str
    
    class Config:
        env_file = ".env"
        extra = "ignore"  # Ignore extra fields from .env file


class NRELClient:
    """
    Client for interacting with NREL APIs:
    - Alternative Fuels Data Center API (EV charging stations)
    - Electricity API (Utility rates)
    - PVWatts API (Solar energy production)
    
    Documentation:
    - Stations: https://developer.nrel.gov/docs/transportation/alt-fuel-stations-v1/
    - Electricity: https://developer.nrel.gov/docs/electricity/
    - PVWatts: https://developer.nrel.gov/docs/solar/pvwatts/v8/
    """
    
    BASE_URL_STATIONS = "https://developer.nrel.gov/api/alt-fuel-stations/v1"
    BASE_URL_ELECTRICITY = "https://developer.nrel.gov/api/utility_rates/v3"
    BASE_URL_PVWATTS = "https://developer.nrel.gov/api/pvwatts/v8.json"
    GEOCODING_URL = "https://nominatim.openstreetmap.org/search"  # Free geocoding service
    
    def __init__(self):
        settings = Settings()
        self.api_key = settings.nrel_api_key
        if not self.api_key or self.api_key == "your_nrel_api_key_here":
            raise ValueError("NREL_API_KEY must be set in environment variables")
        
        # Initialize cache and circuit breakers
        self.cache = get_cache_service()
        self.breaker_manager = get_breaker_manager()
        
        # Create circuit breakers for different API endpoints
        self.stations_breaker = self.breaker_manager.get_breaker(
            "nrel_stations",
            failure_threshold=5,
            timeout_seconds=60,
            success_threshold=2
        )
        self.utility_rates_breaker = self.breaker_manager.get_breaker(
            "nrel_utility_rates",
            failure_threshold=5,
            timeout_seconds=60,
            success_threshold=2
        )
        self.solar_breaker = self.breaker_manager.get_breaker(
            "nrel_solar",
            failure_threshold=5,
            timeout_seconds=60,
            success_threshold=2
        )
        self.geocoding_breaker = self.breaker_manager.get_breaker(
            "geocoding",
            failure_threshold=5,
            timeout_seconds=60,
            success_threshold=2
        )
    
    async def _geocode_zip_code_internal(self, zip_code: str) -> Tuple[float, float]:
        """
        Internal geocoding implementation.
        """
        async with httpx.AsyncClient() as client:
            # Use Nominatim to geocode zip code
            params = {
                "postalcode": zip_code,
                "country": "US",
                "format": "json",
                "limit": 1
            }
            
            headers = {
                "User-Agent": "VoltQuery.ai/1.0"  # Required by Nominatim
            }
            
            try:
                response = await client.get(
                    self.GEOCODING_URL,
                    params=params,
                    headers=headers,
                    timeout=10.0
                )
                response.raise_for_status()
                data = response.json()
                
                if not data or len(data) == 0:
                    raise ValueError(f"Could not geocode zip code {zip_code}")
                
                # Ensure data is a list and has at least one element
                if not isinstance(data, list) or len(data) == 0:
                    raise ValueError(f"Invalid geocoding response for zip code {zip_code}")
                
                # Ensure first element is a dict with lat/lon keys
                first_result = data[0]
                if not isinstance(first_result, dict) or "lat" not in first_result or "lon" not in first_result:
                    raise ValueError(f"Invalid geocoding response format for zip code {zip_code}")
                
                lat = float(first_result["lat"])
                lon = float(first_result["lon"])
                
                return (lat, lon)
            except Exception as e:
                raise ValueError(
                    f"Failed to geocode zip code {zip_code}: {str(e)}"
                ) from e
    
    async def _geocode_zip_code(self, zip_code: str) -> Tuple[float, float]:
        """
        Geocode a zip code to get latitude and longitude.
        Uses caching and circuit breaker for stability.
        
        Args:
            zip_code: 5-digit US zip code
            
        Returns:
            Tuple of (latitude, longitude)
            
        Raises:
            ValueError: If geocoding fails or zip code is invalid
        """
        # Create cache key
        cache_key = self.cache._make_key("geocode_zip", zip_code)
        
        # Cache TTL: 30 days (locations don't change)
        ttl = timedelta(days=30)
        
        # Get from cache or fetch with circuit breaker
        async def _fetch():
            return await self.geocoding_breaker.call(
                self._geocode_zip_code_internal,
                zip_code
            )
        
        return await self.cache.get_or_fetch(cache_key, _fetch, ttl)
    
    async def _lookup_zip_from_city_state(self, city: str, state: str) -> Optional[str]:
        """
        Look up zip code from city/state using a free API.
        Falls back to geocoding if lookup fails.
        
        Args:
            city: City name
            state: State code (2 letters)
            
        Returns:
            Zip code string or None if lookup fails
        """
        try:
            # Use Zippopotam.us API (free, no API key required)
            async with httpx.AsyncClient() as client:
                # Try state abbreviation first
                state_upper = state.upper()
                city_clean = city.replace(" ", "%20")  # URL encode spaces
                
                url = f"https://api.zippopotam.us/us/{state_upper}/{city_clean}"
                response = await client.get(url, timeout=10.0)
                
                if response.status_code == 200:
                    data = response.json()
                    places = data.get("places", [])
                    # Ensure places is a list and has at least one element
                    if isinstance(places, list) and len(places) > 0:
                        # Return the first zip code found
                        zip_code = places[0].get("post code")
                        if zip_code:
                            return zip_code
        except Exception:
            pass
        
        return None
    
    async def _geocode_location_internal(self, location: str) -> Tuple[float, float]:
        """
        Internal geocoding implementation.
        """
        # Check if it's already lat/long format
        if "," in location:
            parts = location.split(",")
            if len(parts) == 2:
                try:
                    lat = float(parts[0].strip())
                    lon = float(parts[1].strip())
                    # Basic validation
                    if -90 <= lat <= 90 and -180 <= lon <= 180:
                        return (lat, lon)
                except ValueError:
                    pass  # Not lat/long, continue to geocode
        
        # Check if it's a zip code (5 digits)
        if location.isdigit() and len(location) == 5:
            return await self._geocode_zip_code(location)
        
        # Geocode as address/city
        async with httpx.AsyncClient() as client:
            # Clean up location string for better geocoding
            # Remove extra spaces and normalize
            location_clean = " ".join(location.split())
            
            headers = {
                "User-Agent": "VoltQuery.ai/1.0"
            }
            
            # Try structured parameters first (city, state) - more reliable
            # Parse "City, State" format
            if "," in location_clean:
                parts = [p.strip() for p in location_clean.split(",")]
                if len(parts) == 2:
                    city = parts[0]
                    state = parts[1]
                    
                    # Map state abbreviations to full names if needed
                    state_abbrev_map = {
                        "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
                        "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
                        "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
                        "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
                        "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
                        "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
                        "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
                        "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
                        "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
                        "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
                        "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
                        "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
                        "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia"
                    }
                    
                    # Use full state name if it's an abbreviation
                    if len(state) == 2 and state.upper() in state_abbrev_map:
                        state = state_abbrev_map[state.upper()]
                    
                    try:
                        params = {
                            "city": city,
                            "state": state,
                            "country": "US",
                            "format": "json",
                            "limit": 1
                        }
                        
                        response = await client.get(
                            self.GEOCODING_URL,
                            params=params,
                            headers=headers,
                            timeout=10.0
                        )
                        
                        if response.status_code == 200:
                            data = response.json()
                            if data and isinstance(data, list) and len(data) > 0:
                                first_result = data[0]
                                if isinstance(first_result, dict) and "lat" in first_result and "lon" in first_result:
                                    lat = float(first_result["lat"])
                                    lon = float(first_result["lon"])
                                    return (lat, lon)
                    except Exception:
                        pass  # Fall through to q parameter method
            
            # Fallback: Try different query formats with 'q' parameter
            query_formats = [
                location_clean,  # Original format
                f"{location_clean}, USA",  # Add USA suffix
            ]
            
            last_error = None
            for query_format in query_formats:
                try:
                    params = {
                        "q": query_format,
                        "country": "US",
                        "format": "json",
                        "limit": 1
                    }
                    
                    response = await client.get(
                        self.GEOCODING_URL,
                        params=params,
                        headers=headers,
                        timeout=10.0
                    )
                    
                    # If we get a 400 error, try the next format
                    if response.status_code == 400:
                        last_error = f"400 Bad Request for query: {query_format}"
                        continue
                    
                    response.raise_for_status()
                    data = response.json()
                    
                    if not data or not isinstance(data, list) or len(data) == 0:
                        last_error = f"No results for query: {query_format}"
                        continue
                    
                    # Ensure first element is a dict with lat/lon keys
                    first_result = data[0]
                    if not isinstance(first_result, dict) or "lat" not in first_result or "lon" not in first_result:
                        last_error = f"Invalid response format for query: {query_format}"
                        continue
                    
                    lat = float(first_result["lat"])
                    lon = float(first_result["lon"])
                    
                    return (lat, lon)
                except Exception as e:
                    last_error = str(e)
                    continue
            
            # If all formats failed, raise the last error
            raise ValueError(
                f"Failed to geocode location '{location}' after trying multiple formats. Last error: {last_error}"
            )
    
    async def _geocode_location(self, location: str) -> Tuple[float, float]:
        """
        Geocode a location string (address, city, etc.) to get latitude and longitude.
        Uses caching and circuit breaker for stability.
        
        Args:
            location: Location string (e.g., "Denver, CO", "80202", "39.7392,-104.9903")
            
        Returns:
            Tuple of (latitude, longitude)
        """
        # Create cache key
        cache_key = self.cache._make_key("geocode_location", location)
        
        # Cache TTL: 30 days (locations don't change)
        ttl = timedelta(days=30)
        
        # Get from cache or fetch with circuit breaker
        async def _fetch():
            return await self.geocoding_breaker.call(
                self._geocode_location_internal,
                location
            )
        
        return await self.cache.get_or_fetch(cache_key, _fetch, ttl)
    
    async def get_stations_by_zip(
        self, 
        zip_code: str,
        fuel_type: str = "ELEC",
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Fetch EV charging stations by zip code.
        
        Args:
            zip_code: 5-digit US zip code
            fuel_type: Fuel type filter (default: ELEC for electric)
            limit: Maximum number of results (default: 50)
        
        Returns:
            List of station dictionaries
        """
        # Geocode zip code to get lat/long
        latitude, longitude = await self._geocode_zip_code(zip_code)
        
        return await self.get_stations_by_coordinates(
            latitude=latitude,
            longitude=longitude,
            fuel_type=fuel_type,
            limit=limit
        )
    
    async def get_stations_by_coordinates(
        self,
        latitude: float,
        longitude: float,
        fuel_type: str = "ELEC",
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Fetch EV charging stations by latitude and longitude.
        
        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            fuel_type: Fuel type filter (default: ELEC for electric)
            limit: Maximum number of results (default: 50)
        
        Returns:
            List of station dictionaries
        """
        async with httpx.AsyncClient() as client:
            params = {
                "api_key": self.api_key,
                "latitude": latitude,
                "longitude": longitude,
                "fuel_type": fuel_type,
                "limit": limit,
                "format": "json"
            }
            
            response = await client.get(
                f"{self.BASE_URL_STATIONS}/nearest.json",
                params=params,
                timeout=30.0
            )
            
            # Better error handling for 422 errors
            if response.status_code == 422:
                try:
                    error_data = response.json()
                    errors = error_data.get("errors", [])
                    error_msg = errors[0] if errors else error_data.get("error", {}).get("message", "Unknown error")
                    raise ValueError(
                        f"NREL API returned 422 Unprocessable Entity: {error_msg}. "
                        f"Request params: latitude={latitude}, longitude={longitude}, limit={limit}"
                    )
                except Exception:
                    raise ValueError(
                        f"NREL API returned 422 Unprocessable Entity. "
                        f"Response: {response.text[:500]}. "
                        f"Request params: latitude={latitude}, longitude={longitude}, limit={limit}"
                    )
            
            response.raise_for_status()
            data = response.json()
            
            # Extract station data from NREL API response
            if "fuel_stations" in data:
                return data["fuel_stations"]
            return []
    
    async def get_stations_by_state(
        self,
        state: str,
        fuel_type: str = "ELEC",
        limit: int = 200,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Fetch EV charging stations by state.
        
        Args:
            state: 2-letter US state code (e.g., "OH" for Ohio)
            fuel_type: Fuel type filter (default: ELEC for electric)
            limit: Maximum number of results per request (default: 200, max: 200)
            offset: Offset for pagination (default: 0)
        
        Returns:
            List of station dictionaries
        """
        async with httpx.AsyncClient() as client:
            params = {
                "api_key": self.api_key,
                "state": state.upper(),
                "fuel_type": fuel_type,
                "limit": min(limit, 200),  # API max appears to be 200, not 10000
                "offset": offset,
                "format": "json"
            }
            
            response = await client.get(
                f"{self.BASE_URL_STATIONS}.json",
                params=params,
                timeout=60.0  # Longer timeout for large requests
            )
            
            # Better error handling for 422 errors
            if response.status_code == 422:
                try:
                    error_data = response.json()
                    error_msg = error_data.get("error", {}).get("message", "Unknown error")
                    raise ValueError(
                        f"NREL API returned 422 Unprocessable Entity: {error_msg}. "
                        f"Request params: state={state}, limit={limit}, offset={offset}"
                    )
                except Exception:
                    raise ValueError(
                        f"NREL API returned 422 Unprocessable Entity. "
                        f"Response: {response.text[:500]}. "
                        f"Request params: state={state}, limit={limit}, offset={offset}"
                    )
            
            response.raise_for_status()
            data = response.json()
            
            # Extract station data from NREL API response
            if "fuel_stations" in data:
                return data["fuel_stations"]
            return []
    
    async def get_all_stations_by_state(
        self,
        state: str,
        fuel_type: str = "ELEC"
    ) -> List[Dict[str, Any]]:
        """
        Fetch ALL EV charging stations for a state (handles pagination automatically).
        
        Args:
            state: 2-letter US state code (e.g., "OH" for Ohio)
            fuel_type: Fuel type filter (default: ELEC for electric)
        
        Returns:
            List of all station dictionaries for the state
        """
        all_stations = []
        offset = 0
        page_size = 200  # Max per request (NREL API limit)
        
        while True:
            stations = await self.get_stations_by_state(
                state=state,
                fuel_type=fuel_type,
                limit=page_size,
                offset=offset
            )
            
            if not stations:
                break
            
            all_stations.extend(stations)
            
            # If we got fewer than page_size, we've reached the end
            if len(stations) < page_size:
                break
            
            offset += page_size
        
        return all_stations
    
    async def get_utility_rates(
        self,
        location: str,
        sector: str = "residential"
    ) -> Dict[str, Any]:
        """
        Fetch utility rates (electricity costs) for a specific location.
        
        Args:
            location: Location identifier (zip code, address, or lat/long)
                     Examples: "80202", "Denver, CO", "39.7392,-104.9903"
            sector: Sector type - "residential", "commercial", or "industrial"
                   (default: "residential")
        
        Returns:
            Dictionary containing utility rate information including:
            - utility_name: Name of the utility company
            - residential_rate: Average residential rate ($/kWh)
            - commercial_rate: Average commercial rate ($/kWh)
            - industrial_rate: Average industrial rate ($/kWh)
            - location: Location information
            - eiaid: EIA utility ID
            
        Note: NREL API v3 no longer supports 'address' parameter (as of 2025-02-25).
        This function now always geocodes to lat/lon first.
        Documentation: https://developer.nrel.gov/docs/electricity/utility-rates-v3/
        """
        # NREL API v3 no longer supports 'address' parameter - must use lat/lon
        # Always geocode to coordinates first
        
        # Check if location is already lat/lon format
        if "," in location:
            parts = location.split(",")
            if len(parts) == 2:
                try:
                    lat = float(parts[0].strip())
                    lon = float(parts[1].strip())
                    # Basic validation
                    if -90 <= lat <= 90 and -180 <= lon <= 180:
                        return await self.get_utility_rates_by_coordinates(
                            latitude=lat,
                            longitude=lon,
                            sector=sector
                        )
                except ValueError:
                    pass  # Not lat/lon, continue to geocode
        
        # If location is a zip code, use zip code geocoding (more reliable)
        if location.isdigit() and len(location) == 5:
            try:
                latitude, longitude = await self._geocode_zip_code(location)
                return await self.get_utility_rates_by_coordinates(
                    latitude=latitude,
                    longitude=longitude,
                    sector=sector
                )
            except Exception as e:
                # If zip code geocoding fails, try general geocoding
                print(f"Warning: Zip code geocoding failed for {location}, trying general geocoding: {str(e)}")
        
        # Geocode location to get lat/long
        try:
            latitude, longitude = await self._geocode_location(location)
            return await self.get_utility_rates_by_coordinates(
                latitude=latitude,
                longitude=longitude,
                sector=sector
            )
        except Exception as e:
            # If geocoding fails and location looks like a zip code, try zip code geocoding
            if location.isdigit() and len(location) == 5:
                try:
                    latitude, longitude = await self._geocode_zip_code(location)
                    return await self.get_utility_rates_by_coordinates(
                        latitude=latitude,
                        longitude=longitude,
                        sector=sector
                    )
                except Exception:
                    pass
            raise
    
    async def get_utility_rates_by_coordinates(
        self,
        latitude: float,
        longitude: float,
        sector: str = "residential"
    ) -> Dict[str, Any]:
        """
        Fetch utility rates (electricity costs) by latitude and longitude.
        Uses caching and circuit breaker for stability.
        
        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            sector: Sector type - "residential", "commercial", or "industrial"
                   (default: "residential")
        
        Returns:
            Dictionary containing utility rate information
        """
        # Create cache key
        cache_key = self.cache._make_key(
            "utility_rates",
            latitude=latitude,
            longitude=longitude,
            sector=sector
        )
        
        # Cache TTL: 24 hours (utility rates change infrequently)
        ttl = timedelta(hours=24)
        
        # Get from cache or fetch with circuit breaker
        async def _fetch():
            return await self.utility_rates_breaker.call(
                self._get_utility_rates_by_coordinates_internal,
                latitude,
                longitude,
                sector
            )
        
        return await self.cache.get_or_fetch(cache_key, _fetch, ttl)
    
    async def _get_utility_rates_by_coordinates_internal(
        self,
        latitude: float,
        longitude: float,
        sector: str = "residential"
    ) -> Dict[str, Any]:
        """
        Fetch utility rates (electricity costs) by latitude and longitude.
        
        Args:
            latitude: Latitude coordinate
            longitude: Longitude coordinate
            sector: Sector type - "residential", "commercial", or "industrial"
                   (default: "residential")
        
        Returns:
            Dictionary containing utility rate information
        """
        async with httpx.AsyncClient() as client:
            # NREL API v3 requires "lat" and "lon" parameters (address parameter deprecated 2025-02-25)
            # Use lat/lon directly - this is the only supported format
            params = {
                "api_key": self.api_key,
                "lat": str(latitude),
                "lon": str(longitude),
                "format": "json"
            }
            
            if sector:
                params["sector"] = sector.lower()
            
            response = await client.get(
                self.BASE_URL_ELECTRICITY,
                params=params,
                timeout=30.0
            )
            
            # Better error handling for 422 errors
            if response.status_code == 422:
                try:
                    error_data = response.json()
                    errors = error_data.get("errors", [])
                    error_msg = errors[0] if errors else error_data.get("error", {}).get("message", "Unknown error")
                    raise ValueError(
                        f"NREL API returned 422 Unprocessable Entity: {error_msg}. "
                        f"Request params: lat={latitude}, lon={longitude}, sector={sector}"
                    )
                except Exception:
                    raise ValueError(
                        f"NREL API returned 422 Unprocessable Entity. "
                        f"Response: {response.text[:500]}. "
                        f"Request params: lat={latitude}, lon={longitude}, sector={sector}"
                    )
            
            response.raise_for_status()
            data = response.json()
            
            # Extract utility rate data from NREL API response
            # The API response structure may vary, so we'll return the full response
            # but extract common fields
            if "outputs" in data:
                outputs = data["outputs"]
                if isinstance(outputs, list) and len(outputs) > 0:
                    return outputs[0]
                return outputs
            
            # If no "outputs" key, return the full response
            return data
    
    async def get_utility_rates_by_zip(
        self,
        zip_code: str,
        sector: str = "residential"
    ) -> Dict[str, Any]:
        """
        Convenience method to get utility rates by zip code.
        
        Args:
            zip_code: 5-digit US zip code
            sector: Sector type - "residential", "commercial", or "industrial"
        
        Returns:
            Dictionary containing utility rate information
        """
        return await self.get_utility_rates(location=zip_code, sector=sector)
    
    async def _get_solar_estimate_internal(
        self,
        lat: float,
        lon: float,
        system_capacity: float = 5.0,
        azimuth: float = 180.0,
        tilt: float = 20.0,
        array_type: int = 1,
        module_type: int = 0,
        losses: float = 14.0
    ) -> Dict[str, Any]:
        """
        Internal solar estimate implementation.
        """
        async with httpx.AsyncClient() as client:
            params = {
                "api_key": self.api_key,
                "lat": lat,
                "lon": lon,
                "system_capacity": system_capacity,
                "azimuth": azimuth,
                "tilt": tilt,
                "array_type": array_type,
                "module_type": module_type,
                "losses": losses,
                "format": "json"
            }
            
            try:
                response = await client.get(
                    self.BASE_URL_PVWATTS,
                    params=params,
                    timeout=30.0
                )
                
                # Handle 422 errors (validation errors)
                if response.status_code == 422:
                    try:
                        error_data = response.json()
                        errors = error_data.get("errors", [])
                        error_msg = errors[0] if errors else error_data.get("error", {}).get("message", "Unknown error")
                        raise ValueError(
                            f"NREL PVWatts API returned 422 Unprocessable Entity: {error_msg}. "
                            f"Request params: lat={lat}, lon={lon}, system_capacity={system_capacity}"
                        )
                    except Exception:
                        raise ValueError(
                            f"NREL PVWatts API returned 422 Unprocessable Entity. "
                            f"Response: {response.text[:500]}. "
                            f"Request params: lat={lat}, lon={lon}, system_capacity={system_capacity}"
                        )
                
                response.raise_for_status()
                data = response.json()
                
                # Extract outputs from NREL API response
                if "outputs" in data:
                    outputs = data["outputs"]
                    if isinstance(outputs, list) and len(outputs) > 0:
                        return outputs[0]
                    return outputs
                
                # If no "outputs" key, return the full response
                return data
                
            except httpx.TimeoutException as e:
                raise ValueError(
                    f"NREL PVWatts API request timed out for coordinates lat={lat}, lon={lon}. "
                    f"Please try again later."
                ) from e
            except httpx.HTTPStatusError as e:
                raise ValueError(
                    f"NREL PVWatts API returned error {e.response.status_code}: {e.response.text[:500]}"
                ) from e
            except Exception as e:
                raise ValueError(
                    f"Failed to get solar estimate: {str(e)}"
                ) from e
    
    async def get_solar_estimate(
        self,
        lat: float,
        lon: float,
        system_capacity: float = 5.0,
        azimuth: float = 180.0,
        tilt: float = 20.0,
        array_type: int = 1,
        module_type: int = 0,
        losses: float = 14.0
    ) -> Dict[str, Any]:
        """
        Get solar energy production estimate using NREL PVWatts v8 API.
        Uses caching and circuit breaker for stability.
        
        Args:
            lat: Latitude coordinate
            lon: Longitude coordinate
            system_capacity: System capacity in kW (default: 5.0)
            azimuth: Azimuth angle in degrees (default: 180.0, south-facing)
            tilt: Tilt angle in degrees (default: 20.0)
            array_type: Array type (default: 1 for roof mount)
                        0 = Fixed - Open Rack
                        1 = Fixed - Roof Mounted
                        2 = Fixed - 1-Axis
                        3 = Fixed - 1-Axis Backtracking
                        4 = Fixed - 2-Axis
            module_type: Module type (default: 0 for standard)
                        0 = Standard
                        1 = Premium
                        2 = Thin Film
            losses: System losses percentage (default: 14.0)
        
        Returns:
            Dictionary containing solar production estimates including:
            - ac_annual: Annual AC energy production (kWh)
            - ac_monthly: Monthly AC energy production (kWh) - list of 12 values
            - solrad_annual: Annual solar radiation (kWh/m2/day)
            - solrad_monthly: Monthly solar radiation (kWh/m2/day) - list of 12 values
            - capacity_factor: Capacity factor (%)
            
        Raises:
            ValueError: If API returns an error or invalid coordinates
            httpx.TimeoutException: If API request times out
        """
        # Create cache key
        cache_key = self.cache._make_key(
            "solar_estimate",
            lat=lat,
            lon=lon,
            system_capacity=system_capacity,
            azimuth=azimuth,
            tilt=tilt,
            array_type=array_type,
            module_type=module_type,
            losses=losses
        )
        
        # Cache TTL: 1 hour (solar estimates are relatively stable)
        ttl = timedelta(hours=1)
        
        # Get from cache or fetch with circuit breaker
        async def _fetch():
            return await self.solar_breaker.call(
                self._get_solar_estimate_internal,
                lat,
                lon,
                system_capacity,
                azimuth,
                tilt,
                array_type,
                module_type,
                losses
            )
        
        return await self.cache.get_or_fetch(cache_key, _fetch, ttl)

