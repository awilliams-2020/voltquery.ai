"""
Unified freshness checker for vector store data.

Consolidates duplicate freshness checking logic across different data types.
"""

from typing import Tuple, Optional, Dict, Any
from datetime import datetime, timedelta
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters, FilterOperator
from app.services.rag_settings import RAGSettings
from app.services.logger_service import get_logger


class FreshnessChecker:
    """
    Unified freshness checker for different data types in vector store.
    
    Consolidates duplicate freshness checking logic.
    """
    
    def __init__(self, vector_store_service, settings: Optional[RAGSettings] = None):
        """
        Initialize freshness checker.
        
        Args:
            vector_store_service: VectorStoreService instance
            settings: RAGSettings instance (optional)
        """
        self.vector_store_service = vector_store_service
        self.settings = settings or RAGSettings()
        self.logger = get_logger("freshness_checker")
    
    async def check_freshness(
        self,
        domain: str,
        filter_key: str,
        filter_value: str,
        query_text: str,
        ttl: timedelta,
        log_prefix: str = ""
    ) -> Tuple[bool, Optional[datetime]]:
        """
        Check if data exists and is fresh in vector store.
        
        Args:
            domain: Domain filter value (e.g., "transportation", "utility", "buildings")
            filter_key: Metadata key to filter by (e.g., "zip", "queried_zip", "state")
            filter_value: Value to filter by
            query_text: Query text for retrieval test
            ttl: Time-to-live for freshness check
            log_prefix: Prefix for log messages
            
        Returns:
            Tuple of (is_fresh, indexed_at_datetime)
        """
        try:
            index = self.vector_store_service.get_index()
            test_retriever = VectorIndexRetriever(
                index=index,
                similarity_top_k=1,
                filters=MetadataFilters(filters=[
                    MetadataFilter(key="domain", value=domain, operator=FilterOperator.EQ),
                    MetadataFilter(key=filter_key, value=filter_value, operator=FilterOperator.EQ)
                ])
            )
            test_nodes = test_retriever.retrieve(query_text)
            
            if not test_nodes or len(test_nodes) == 0:
                self.logger.log_cache(
                    operation="freshness_check",
                    key=f"{domain}:{filter_key}:{filter_value}",
                    cache_hit=False,
                    expired=False
                )
                return False, None
            
            # Check freshness from metadata
            node = test_nodes[0]
            metadata = node.metadata if hasattr(node, 'metadata') else {}
            indexed_at_str = metadata.get("indexed_at")
            
            if not indexed_at_str:
                # No timestamp - assume stale (old data without timestamp)
                self.logger.log_cache(
                    operation="freshness_check",
                    key=f"{domain}:{filter_key}:{filter_value}",
                    cache_hit=True,
                    expired=True,
                    age_seconds=None
                )
                return False, None
            
            try:
                # Parse ISO 8601 timestamp (handle both with and without Z)
                indexed_at_str = indexed_at_str.replace('Z', '+00:00')
                indexed_at = datetime.fromisoformat(indexed_at_str)
                # Convert to UTC naive datetime for comparison
                if indexed_at.tzinfo:
                    indexed_at = indexed_at.astimezone().replace(tzinfo=None)
                
                now = datetime.utcnow()
                age = now - indexed_at
                is_fresh = age < ttl
                
                age_hours = age.total_seconds() / 3600
                ttl_hours = ttl.total_seconds() / 3600
                
                self.logger.log_cache(
                    operation="freshness_check",
                    key=f"{domain}:{filter_key}:{filter_value}",
                    cache_hit=True,
                    expired=not is_fresh,
                    age_seconds=int(age.total_seconds())
                )
                
                return is_fresh, indexed_at
            except (ValueError, TypeError) as e:
                # Invalid timestamp format - assume stale
                self.logger.log_error(
                    error_type="TimestampParseError",
                    error_message=f"Invalid timestamp format: {str(e)}",
                    context={
                        "domain": domain,
                        "filter_key": filter_key,
                        "filter_value": filter_value,
                        "indexed_at_str": indexed_at_str
                    }
                )
                return False, None
                
        except Exception as e:
            self.logger.log_error(
                error_type=type(e).__name__,
                error_message=f"Freshness check failed: {str(e)}",
                context={
                    "domain": domain,
                    "filter_key": filter_key,
                    "filter_value": filter_value
                }
            )
            return False, None
    
    async def check_utility_rates_freshness(
        self,
        zip_code: str
    ) -> Tuple[bool, Optional[datetime]]:
        """Check utility rates freshness."""
        return await self.check_freshness(
            domain="utility",
            filter_key="zip",
            filter_value=zip_code,
            query_text="utility rate",
            ttl=self.settings.get_utility_ttl(),
            log_prefix="utility_rates"
        )
    
    async def check_stations_freshness(
        self,
        zip_code: str
    ) -> Tuple[bool, Optional[datetime]]:
        """Check stations freshness by zip code."""
        return await self.check_freshness(
            domain="transportation",
            filter_key="queried_zip",
            filter_value=zip_code,
            query_text="charging station",
            ttl=self.settings.get_station_ttl(),
            log_prefix="stations"
        )
    
    async def check_stations_freshness_by_state(
        self,
        state: str
    ) -> Tuple[bool, Optional[datetime]]:
        """Check stations freshness by state."""
        return await self.check_freshness(
            domain="transportation",
            filter_key="state",
            filter_value=state,
            query_text="charging station",
            ttl=self.settings.get_station_ttl(),
            log_prefix="stations_state"
        )
    
    async def check_bcl_measures_freshness(
        self,
        state: str
    ) -> Tuple[bool, Optional[datetime]]:
        """Check BCL measures freshness."""
        return await self.check_freshness(
            domain="buildings",
            filter_key="state",
            filter_value=state,
            query_text="building efficiency",
            ttl=self.settings.get_bcl_ttl(),
            log_prefix="bcl_measures"
        )

