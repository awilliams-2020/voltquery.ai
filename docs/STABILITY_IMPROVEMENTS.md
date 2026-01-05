# RAG System Stability Improvements

This document outlines recommendations for improving the stability and reliability of the RAG system.

## Current State Analysis

### ✅ What's Working Well
- Basic error handling with try/except blocks
- Timeout configuration for API calls
- Error messages returned to users
- Database error handling

### ⚠️ Areas for Improvement

## 1. Retry Logic with Exponential Backoff

**Problem**: API calls can fail due to transient network issues, rate limits, or temporary service outages.

**Solution**: Implement retry logic with exponential backoff for external API calls.

```python
# Example: backend/app/services/retry_handler.py
import asyncio
from typing import Callable, TypeVar, Optional
from functools import wraps

T = TypeVar('T')

async def retry_with_backoff(
    func: Callable[..., T],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (httpx.HTTPError, httpx.TimeoutException)
) -> T:
    """Retry a function with exponential backoff."""
    delay = initial_delay
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return await func()
        except exceptions as e:
            last_exception = e
            if attempt < max_retries - 1:
                await asyncio.sleep(min(delay, max_delay))
                delay *= backoff_factor
            else:
                raise
    
    raise last_exception
```

**Apply to**:
- NREL API calls (stations, utility rates, solar)
- Geocoding API calls
- LLM API calls (Gemini/Ollama)

## 2. Response Caching

**Problem**: Repeated queries hit APIs unnecessarily, wasting resources and potentially hitting rate limits.

**Solution**: Cache API responses and query results.

```python
# Example: backend/app/services/cache_service.py
from functools import lru_cache
from datetime import datetime, timedelta
import hashlib
import json

class CacheService:
    def __init__(self, ttl_seconds: int = 3600):
        self.cache = {}
        self.ttl = timedelta(seconds=ttl_seconds)
    
    def _make_key(self, *args, **kwargs) -> str:
        """Create cache key from arguments."""
        key_data = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True)
        return hashlib.md5(key_data.encode()).hexdigest()
    
    async def get_or_fetch(
        self,
        key: str,
        fetch_func: Callable,
        *args,
        **kwargs
    ):
        """Get from cache or fetch and cache."""
        cache_key = self._make_key(key, *args, **kwargs)
        
        if cache_key in self.cache:
            cached_data, timestamp = self.cache[cache_key]
            if datetime.now() - timestamp < self.ttl:
                return cached_data
        
        # Fetch and cache
        result = await fetch_func(*args, **kwargs)
        self.cache[cache_key] = (result, datetime.now())
        return result
```

**Cache**:
- Utility rates by zip code (TTL: 24 hours - rates change infrequently)
- Solar estimates by location/system_size (TTL: 1 hour)
- Geocoding results (TTL: 30 days - locations don't change)
- Station data by zip code (TTL: 1 hour)

## 3. Circuit Breaker Pattern

**Problem**: If an external service is down, we continue making requests, wasting resources and slowing responses.

**Solution**: Implement circuit breaker to stop calling failing services.

```python
# Example: backend/app/services/circuit_breaker.py
from enum import Enum
from datetime import datetime, timedelta

class CircuitState(Enum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, don't call
    HALF_OPEN = "half_open"  # Testing if recovered

class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        timeout_seconds: int = 60,
        success_threshold: int = 2
    ):
        self.failure_threshold = failure_threshold
        self.timeout = timedelta(seconds=timeout_seconds)
        self.success_threshold = success_threshold
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
    
    async def call(self, func: Callable, *args, **kwargs):
        """Call function with circuit breaker protection."""
        if self.state == CircuitState.OPEN:
            if datetime.now() - self.last_failure_time > self.timeout:
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
            else:
                raise Exception("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.success_threshold:
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = datetime.now()
            
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
            
            raise
```

**Apply to**:
- NREL API calls
- LLM API calls
- Geocoding service

## 4. Input Validation

**Problem**: Invalid inputs can cause unexpected errors or poor responses.

**Solution**: Validate inputs before processing.

```python
# Example: backend/app/services/validators.py
from pydantic import BaseModel, validator
import re

class QueryValidator:
    @staticmethod
    def validate_zip_code(zip_code: str) -> bool:
        """Validate US zip code format."""
        return bool(re.match(r'^\d{5}$', zip_code))
    
    @staticmethod
    def validate_location(location: str) -> bool:
        """Validate location format."""
        # Zip code
        if QueryValidator.validate_zip_code(location):
            return True
        # City, State
        if re.match(r'^[A-Za-z\s]+,\s*[A-Z]{2}$', location):
            return True
        # Coordinates
        if re.match(r'^-?\d+\.?\d*,\s*-?\d+\.?\d*$', location):
            return True
        return False
    
    @staticmethod
    def validate_system_capacity(capacity: float) -> bool:
        """Validate solar system capacity."""
        return 0.1 <= capacity <= 1000.0  # Reasonable range
```

## 5. Response Validation

**Problem**: LLM responses might be malformed or contain errors.

**Solution**: Validate LLM responses before returning to users.

```python
# Example: backend/app/services/response_validator.py
def validate_llm_response(response: str) -> tuple[bool, Optional[str]]:
    """Validate LLM response quality."""
    # Check for refusal phrases
    refusal_phrases = [
        "i cannot", "i cannot provide", "i'm not able",
        "i don't have access", "i cannot assist"
    ]
    
    response_lower = response.lower()
    for phrase in refusal_phrases:
        if phrase in response_lower:
            return False, f"Response contains refusal phrase: {phrase}"
    
    # Check minimum length
    if len(response.strip()) < 10:
        return False, "Response too short"
    
    # Check for error indicators
    error_indicators = ["error:", "exception:", "failed:", "unable to"]
    for indicator in error_indicators:
        if indicator in response_lower:
            return False, f"Response contains error indicator: {indicator}"
    
    return True, None
```

## 6. Rate Limiting

**Problem**: Could hit API rate limits, causing failures.

**Solution**: Implement rate limiting for API calls.

```python
# Example: backend/app/services/rate_limiter.py
from collections import defaultdict
from datetime import datetime, timedelta

class RateLimiter:
    def __init__(self, max_calls: int, period_seconds: int):
        self.max_calls = max_calls
        self.period = timedelta(seconds=period_seconds)
        self.calls = defaultdict(list)
    
    async def acquire(self, key: str) -> bool:
        """Check if we can make a call, record if yes."""
        now = datetime.now()
        # Remove old calls
        self.calls[key] = [
            call_time for call_time in self.calls[key]
            if now - call_time < self.period
        ]
        
        if len(self.calls[key]) >= self.max_calls:
            return False
        
        self.calls[key].append(now)
        return True
```

## 7. Graceful Degradation

**Problem**: If one tool fails, the entire query fails.

**Solution**: Allow partial responses when some tools fail.

```python
# Example: In rag_service.py query method
async def query(self, question: str, ...):
    # Try to get utility rates, but don't fail if it doesn't work
    utility_data = None
    try:
        utility_data = await self._get_utility_rates(...)
    except Exception as e:
        print(f"Warning: Could not get utility rates: {e}")
        # Continue without utility data
    
    # Try to get solar data, but don't fail if it doesn't work
    solar_data = None
    try:
        solar_data = await self._get_solar_estimate(...)
    except Exception as e:
        print(f"Warning: Could not get solar data: {e}")
        # Continue without solar data
    
    # Generate response with available data
    # If some data is missing, mention it in the response
```

## 8. Structured Logging

**Problem**: Hard to debug issues without structured logs.

**Solution**: Implement structured logging.

```python
# Example: backend/app/services/logger.py
import logging
import json
from datetime import datetime

class StructuredLogger:
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
    
    def log_query(
        self,
        question: str,
        user_id: str,
        tools_used: list[str],
        response_time: float,
        success: bool,
        error: Optional[str] = None
    ):
        """Log query with structured data."""
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "event": "query",
            "question": question,
            "user_id": user_id,
            "tools_used": tools_used,
            "response_time_ms": response_time * 1000,
            "success": success,
            "error": error
        }
        self.logger.info(json.dumps(log_data))
```

## 9. Health Checks

**Problem**: No way to verify system health.

**Solution**: Add health check endpoints.

```python
# Example: backend/app/routers/health.py
@router.get("/health")
async def health_check():
    """Check system health."""
    checks = {
        "database": await check_database(),
        "nrel_api": await check_nrel_api(),
        "llm": await check_llm(),
        "vector_store": await check_vector_store()
    }
    
    all_healthy = all(checks.values())
    status_code = 200 if all_healthy else 503
    
    return JSONResponse(
        status_code=status_code,
        content={"status": "healthy" if all_healthy else "degraded", "checks": checks}
    )
```

## 10. Idempotency for Indexing

**Problem**: Could index the same data multiple times.

**Solution**: Check for existing documents before indexing.

```python
# Example: In rag_service.py
async def _index_utility_rates(self, utility_rates: Dict, location: str):
    """Index utility rates with idempotency check."""
    # Create document ID
    doc_id = f"utility_{location}_{utility_rates.get('eiaid', 'unknown')}"
    
    # Check if already exists
    index = self.vector_store_service.get_index()
    # Query for existing document (implementation depends on vector store)
    # If exists, skip or update
    
    # Index if new
    index.insert(doc)
```

## 11. Monitoring and Alerting

**Problem**: No visibility into system performance or errors.

**Solution**: Add metrics and alerting.

**Metrics to track**:
- API call success/failure rates
- Response times (p50, p95, p99)
- Cache hit rates
- Circuit breaker state changes
- Error rates by type
- Tool usage statistics

**Tools**:
- Prometheus for metrics
- Grafana for dashboards
- Sentry for error tracking
- Or simple logging to structured logs

## 12. Timeout Configuration

**Problem**: Timeouts are hardcoded or inconsistent.

**Solution**: Make timeouts configurable and context-aware.

```python
# Example: backend/app/services/config.py
class TimeoutConfig:
    NREL_API = 30.0  # seconds
    GEOCODING = 10.0
    LLM_COMPLETION = 60.0
    LLM_STREAMING = 120.0
    VECTOR_SEARCH = 5.0
```

## Implementation Priority

### High Priority (Do First)
1. ✅ **Retry Logic** - Prevents transient failures
2. ✅ **Input Validation** - Prevents invalid data issues
3. ✅ **Graceful Degradation** - Better user experience
4. ✅ **Structured Logging** - Essential for debugging

### Medium Priority
5. **Response Caching** - Improves performance
6. **Circuit Breaker** - Prevents cascading failures
7. **Response Validation** - Ensures quality
8. **Health Checks** - Operational visibility

### Low Priority (Nice to Have)
9. **Rate Limiting** - If hitting API limits
10. **Idempotency** - If duplicate indexing is an issue
11. **Monitoring** - For production scale
12. **Timeout Configuration** - Fine-tuning

## Testing Stability Improvements

Add tests for:
- Retry logic (test retry on failure)
- Circuit breaker (test state transitions)
- Caching (test cache hits/misses)
- Graceful degradation (test partial failures)
- Input validation (test invalid inputs)

## Next Steps

1. Start with retry logic for NREL API calls
2. Add input validation for user queries
3. Implement graceful degradation for tool failures
4. Add structured logging
5. Gradually add other improvements based on needs

