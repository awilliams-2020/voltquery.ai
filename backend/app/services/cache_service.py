"""
Cache service for API responses and query results.

Provides in-memory caching with TTL (time-to-live) support.
"""

from typing import Dict, Any, Callable, Optional, TypeVar
from datetime import datetime, timedelta
import hashlib
import json
import asyncio
from app.services.logger_service import get_logger

T = TypeVar('T')


class CacheEntry:
    """Represents a cached entry with timestamp."""
    
    def __init__(self, data: Any, timestamp: datetime):
        self.data = data
        self.timestamp = timestamp
    
    def is_expired(self, ttl: timedelta) -> bool:
        """Check if entry is expired."""
        return datetime.now() - self.timestamp > ttl


class CacheService:
    """
    In-memory cache service with TTL support.
    
    Thread-safe for async operations.
    """
    
    def __init__(self):
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self.logger = get_logger("cache_service", log_level="DEBUG")
    
    def _make_key(self, prefix: str, *args, **kwargs) -> str:
        """Create cache key from prefix and arguments."""
        key_data = json.dumps(
            {"prefix": prefix, "args": args, "kwargs": kwargs},
            sort_keys=True,
            default=str
        )
        key_hash = hashlib.md5(key_data.encode()).hexdigest()
        return f"{prefix}:{key_hash}"
    
    async def get(self, key: str, ttl: timedelta) -> Optional[Any]:
        """
        Get cached value if not expired.
        
        Args:
            key: Cache key
            ttl: Time-to-live for the cache entry
            
        Returns:
            Cached value or None if not found/expired
        """
        async with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if not entry.is_expired(ttl):
                    self.logger.log_cache(
                        operation="get",
                        key=key,
                        cache_hit=True,
                        ttl_seconds=int(ttl.total_seconds())
                    )
                    return entry.data
                else:
                    # Remove expired entry
                    del self._cache[key]
            self.logger.log_cache(
                operation="get",
                key=key,
                cache_hit=False,
                ttl_seconds=int(ttl.total_seconds())
            )
            return None
    
    async def set(self, key: str, value: Any) -> None:
        """
        Set cached value.
        
        Args:
            key: Cache key
            value: Value to cache
        """
        async with self._lock:
            self._cache[key] = CacheEntry(value, datetime.now())
            self.logger.log_cache(
                operation="set",
                key=key,
                cache_hit=False
            )
    
    async def get_or_fetch(
        self,
        key: str,
        fetch_func: Callable[..., T],
        ttl: timedelta,
        *args,
        **kwargs
    ) -> T:
        """
        Get from cache or fetch and cache.
        
        Args:
            key: Cache key
            fetch_func: Async function to fetch data if not cached
            ttl: Time-to-live for cached data
            *args, **kwargs: Arguments to pass to fetch_func
            
        Returns:
            Cached or freshly fetched data
        """
        # Try to get from cache
        cached = await self.get(key, ttl)
        if cached is not None:
            return cached
        
        # Fetch and cache
        result = await fetch_func(*args, **kwargs)
        await self.set(key, result)
        return result
    
    async def clear(self, prefix: Optional[str] = None) -> int:
        """
        Clear cache entries.
        
        Args:
            prefix: Optional prefix to clear only matching keys
            
        Returns:
            Number of entries cleared
        """
        async with self._lock:
            if prefix:
                keys_to_remove = [
                    key for key in self._cache.keys()
                    if key.startswith(prefix)
                ]
                for key in keys_to_remove:
                    del self._cache[key]
                return len(keys_to_remove)
            else:
                count = len(self._cache)
                self._cache.clear()
                return count
    
    async def cleanup_expired(self, ttl: timedelta) -> int:
        """
        Remove expired entries from cache.
        
        Args:
            ttl: TTL to check against
            
        Returns:
            Number of entries removed
        """
        async with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired(ttl)
            ]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        async def _get_stats():
            async with self._lock:
                return {
                    "total_entries": len(self._cache),
                    "keys": list(self._cache.keys())[:10]  # First 10 keys
                }
        # For sync access, we'll just return current state
        return {
            "total_entries": len(self._cache),
            "keys": list(self._cache.keys())[:10]
        }


# Global cache instance
_cache_service: Optional[CacheService] = None


def get_cache_service() -> CacheService:
    """Get global cache service instance."""
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service

