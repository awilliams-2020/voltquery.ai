"""
BCL (Building Component Library) Client

Client for interacting with NREL's Building Component Library API.
BCL provides access to OpenStudio measures and building components.

Documentation:
- BCL API: https://bcl.nrel.gov/
- Measure Schema: https://bcl.nrel.gov/static/assets/json/measure_schema.json
- Component Schema: https://bcl.nrel.gov/static/assets/json/component_schema.json
"""

import httpx
from typing import Dict, List, Any, Optional
from datetime import timedelta
from app.services.cache_service import get_cache_service
from app.services.circuit_breaker import get_breaker_manager


class BCLClient:
    """
    Client for interacting with NREL's Building Component Library (BCL).
    
    BCL provides:
    - OpenStudio measures (energy efficiency measures, code compliance, etc.)
    - Building components (construction assemblies, materials, etc.)
    
    The BCL API is public and does not require authentication.
    """
    
    BASE_URL = "https://bcl.nrel.gov/api"
    SEARCH_ENDPOINT = f"{BASE_URL}/search"
    MEASURE_ENDPOINT = f"{BASE_URL}/measure"
    COMPONENT_ENDPOINT = f"{BASE_URL}/component"
    
    def __init__(self):
        # Initialize cache and circuit breakers
        self.cache = get_cache_service()
        self.breaker_manager = get_breaker_manager()
        
        # Create circuit breaker for BCL API
        self.bcl_breaker = self.breaker_manager.get_breaker(
            "bcl_api",
            failure_threshold=5,
            timeout_seconds=60,
            success_threshold=2
        )
    
    async def _search_measures_internal(
        self,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        attributes: Optional[Dict[str, Any]] = None,
        limit: int = 20,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Internal search implementation for OpenStudio measures.
        """
        params = {
            "limit": limit,
            "offset": offset
        }
        
        # Initialize fq[] as a list for multiple filter queries
        fq_filters = ["bundle:measure"]  # Filter to measures only
        
        if query:
            params["q"] = query
        
        if tags:
            for tag in tags:
                fq_filters.append(f"tags:{tag}")
        
        if attributes:
            for attr_name, attr_value in attributes.items():
                fq_filters.append(f"attributes.{attr_name}:{attr_value}")
        
        # Set fq[] as list - httpx automatically formats lists as multiple query params
        # e.g., fq[]=value1&fq[]=value2
        params["fq[]"] = fq_filters
        
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(
                self.SEARCH_ENDPOINT,
                params=params,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            return data
    
    async def search_measures(
        self,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        attributes: Optional[Dict[str, Any]] = None,
        limit: int = 20,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Search for OpenStudio measures in BCL.
        Uses caching and circuit breaker for stability.
        
        Args:
            query: Search query string
            tags: List of taxonomy tags (e.g., ["Reporting.QAQC", "ModelMeasure"])
            attributes: Dictionary of attribute filters (e.g., {"name": "value"})
            limit: Maximum number of results to return
            offset: Offset for pagination
            
        Returns:
            Dictionary containing search results with measure data matching the schema:
            https://bcl.nrel.gov/static/assets/json/measure_schema.json
        """
        # Create cache key
        cache_key = self.cache._make_key(
            "bcl_measures_search",
            query=query,
            tags=tags,
            attributes=attributes,
            limit=limit,
            offset=offset
        )
        
        # Cache TTL: 24 hours (BCL data doesn't change frequently)
        ttl = timedelta(hours=24)
        
        # Get from cache or fetch with circuit breaker
        async def _fetch():
            return await self.bcl_breaker.call(
                self._search_measures_internal,
                query,
                tags,
                attributes,
                limit,
                offset
            )
        
        return await self.cache.get_or_fetch(cache_key, _fetch, ttl)
    
    async def _search_components_internal(
        self,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        attributes: Optional[Dict[str, Any]] = None,
        limit: int = 20,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Internal search implementation for building components.
        """
        params = {
            "limit": limit,
            "offset": offset
        }
        
        # Initialize fq[] as a list for multiple filter queries
        fq_filters = ["bundle:component"]  # Filter to components only
        
        if query:
            params["q"] = query
        
        if tags:
            for tag in tags:
                fq_filters.append(f"tags:{tag}")
        
        if attributes:
            for attr_name, attr_value in attributes.items():
                fq_filters.append(f"attributes.{attr_name}:{attr_value}")
        
        # Set fq[] as list - httpx automatically formats lists as multiple query params
        # e.g., fq[]=value1&fq[]=value2
        params["fq[]"] = fq_filters
        
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(
                self.SEARCH_ENDPOINT,
                params=params,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            return data
    
    async def search_components(
        self,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        attributes: Optional[Dict[str, Any]] = None,
        limit: int = 20,
        offset: int = 0
    ) -> Dict[str, Any]:
        """
        Search for building components in BCL.
        Uses caching and circuit breaker for stability.
        
        Args:
            query: Search query string
            tags: List of taxonomy tags (e.g., ["Construction Assembly.Fenestration.Window"])
            attributes: Dictionary of attribute filters
            limit: Maximum number of results to return
            offset: Offset for pagination
            
        Returns:
            Dictionary containing search results with component data matching the schema:
            https://bcl.nrel.gov/static/assets/json/component_schema.json
        """
        # Create cache key
        cache_key = self.cache._make_key(
            "bcl_components_search",
            query=query,
            tags=tags,
            attributes=attributes,
            limit=limit,
            offset=offset
        )
        
        # Cache TTL: 24 hours (BCL data doesn't change frequently)
        ttl = timedelta(hours=24)
        
        # Get from cache or fetch with circuit breaker
        async def _fetch():
            return await self.bcl_breaker.call(
                self._search_components_internal,
                query,
                tags,
                attributes,
                limit,
                offset
            )
        
        return await self.cache.get_or_fetch(cache_key, _fetch, ttl)
    
    async def _get_measure_internal(self, uuid: str) -> Dict[str, Any]:
        """
        Internal implementation for getting a specific measure by UUID.
        """
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(
                f"{self.MEASURE_ENDPOINT}/{uuid}",
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            return data
    
    async def get_measure(self, uuid: str) -> Dict[str, Any]:
        """
        Get a specific measure by UUID.
        Uses caching and circuit breaker for stability.
        
        Args:
            uuid: The UUID of the measure
            
        Returns:
            Measure data matching the schema:
            https://bcl.nrel.gov/static/assets/json/measure_schema.json
        """
        # Create cache key
        cache_key = self.cache._make_key("bcl_measure", uuid=uuid)
        
        # Cache TTL: 24 hours (BCL data doesn't change frequently)
        ttl = timedelta(hours=24)
        
        # Get from cache or fetch with circuit breaker
        async def _fetch():
            return await self.bcl_breaker.call(
                self._get_measure_internal,
                uuid
            )
        
        return await self.cache.get_or_fetch(cache_key, _fetch, ttl)
    
    async def _get_component_internal(self, uuid: str) -> Dict[str, Any]:
        """
        Internal implementation for getting a specific component by UUID.
        """
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(
                f"{self.COMPONENT_ENDPOINT}/{uuid}",
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            return data
    
    async def get_component(self, uuid: str) -> Dict[str, Any]:
        """
        Get a specific component by UUID.
        Uses caching and circuit breaker for stability.
        
        Args:
            uuid: The UUID of the component
            
        Returns:
            Component data matching the schema:
            https://bcl.nrel.gov/static/assets/json/component_schema.json
        """
        # Create cache key
        cache_key = self.cache._make_key("bcl_component", uuid=uuid)
        
        # Cache TTL: 24 hours (BCL data doesn't change frequently)
        ttl = timedelta(hours=24)
        
        # Get from cache or fetch with circuit breaker
        async def _fetch():
            return await self.bcl_breaker.call(
                self._get_component_internal,
                uuid
            )
        
        return await self.cache.get_or_fetch(cache_key, _fetch, ttl)
    
    async def search_building_codes(
        self,
        query: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Search for building code-related measures.
        Uses caching and circuit breaker for stability.
        
        Convenience method that searches for measures related to building codes,
        energy codes, and compliance.
        
        Args:
            query: Search query (e.g., "IECC", "ASHRAE", "energy code")
            limit: Maximum number of results
            
        Returns:
            List of measure dictionaries
        """
        # Search for measures with building code related tags
        tags = [
            "ModelMeasure",  # General model measures
            "Reporting.QAQC",  # QAQC measures often include code compliance
        ]
        
        result = await self.search_measures(
            query=query,
            tags=tags,
            limit=limit
        )
        
        # Extract measures from result
        # API returns: {"result": [{"measure": {...}}, ...]}
        # We need to extract the "measure" key from each item
        result_list = result.get("result", [])
        measures = []
        for item in result_list:
            if isinstance(item, dict) and "measure" in item:
                measures.append(item["measure"])
            elif isinstance(item, dict):
                # If it's already a measure dict, use it directly
                measures.append(item)
        return measures
    
    async def search_energy_efficiency_measures(
        self,
        query: Optional[str] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Search for energy efficiency-related measures.
        Uses caching and circuit breaker for stability.
        
        Convenience method for finding measures related to energy efficiency,
        retrofits, and building performance.
        
        Args:
            query: Search query
            limit: Maximum number of results
            
        Returns:
            List of measure dictionaries
        """
        result = await self.search_measures(
            query=query,
            limit=limit
        )
        
        # Extract measures from result
        # API returns: {"result": [{"measure": {...}}, ...]}
        # We need to extract the "measure" key from each item
        result_list = result.get("result", [])
        measures = []
        for item in result_list:
            if isinstance(item, dict) and "measure" in item:
                measures.append(item["measure"])
            elif isinstance(item, dict):
                # If it's already a measure dict, use it directly
                measures.append(item)
        return measures

