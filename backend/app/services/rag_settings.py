"""
RAG service settings including TTL configuration for vector store freshness checks.
"""
from datetime import timedelta
from pydantic_settings import BaseSettings


class RAGSettings(BaseSettings):
    """
    Settings for RAG service, including TTL configuration for vector store freshness.
    
    TTL values determine how long cached data in the vector store is considered fresh.
    These should typically be longer than API cache TTL since re-indexing is more expensive.
    """
    
    # TTL for transportation data (charging stations)
    # Default: 30 days (720 hours) - stations change infrequently
    station_data_ttl_hours: int = 720
    
    # TTL for utility rate data
    # Default: 7 days (168 hours) - rates may change monthly/quarterly
    # Longer than API cache (24 hours) to reduce re-indexing
    utility_data_ttl_hours: int = 168
    
    # TTL for building codes and efficiency measures (BCL)
    # Default: 90 days - building codes change infrequently
    bcl_data_ttl_days: int = 90
    
    class Config:
        env_file = ".env"
        extra = "ignore"
    
    def get_station_ttl(self) -> timedelta:
        """Get TTL for station data."""
        return timedelta(hours=self.station_data_ttl_hours)
    
    def get_utility_ttl(self) -> timedelta:
        """Get TTL for utility rate data."""
        return timedelta(hours=self.utility_data_ttl_hours)
    
    def get_bcl_ttl(self) -> timedelta:
        """Get TTL for BCL data."""
        return timedelta(days=self.bcl_data_ttl_days)


