"""
Circuit breaker pattern for handling failing services.

Prevents cascading failures by stopping calls to failing services.
"""

from enum import Enum
from datetime import datetime, timedelta
from typing import Callable, TypeVar, Optional, Dict, Any
import asyncio
from app.services.logger_service import get_logger

T = TypeVar('T')


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation - calls pass through
    OPEN = "open"  # Failing - calls are blocked
    HALF_OPEN = "half_open"  # Testing recovery - limited calls allowed


class CircuitBreaker:
    """
    Circuit breaker to prevent calling failing services.
    
    Transitions:
    - CLOSED -> OPEN: After failure_threshold failures
    - OPEN -> HALF_OPEN: After timeout_seconds
    - HALF_OPEN -> CLOSED: After success_threshold successes
    - HALF_OPEN -> OPEN: After any failure
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout_seconds: int = 60,
        success_threshold: int = 2
    ):
        """
        Initialize circuit breaker.
        
        Args:
            name: Name of the circuit breaker (for logging)
            failure_threshold: Number of failures before opening circuit
            timeout_seconds: Seconds to wait before trying half-open
            success_threshold: Number of successes to close from half-open
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout = timedelta(seconds=timeout_seconds)
        self.success_threshold = success_threshold
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.last_success_time: Optional[datetime] = None
        self._lock = asyncio.Lock()
        self.logger = get_logger("circuit_breaker")
    
    async def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        Call function with circuit breaker protection.
        
        Args:
            func: Async function to call
            *args, **kwargs: Arguments for function
            
        Returns:
            Function result
            
        Raises:
            Exception: If circuit is open or function fails
        """
        # Check circuit state (with lock)
        async with self._lock:
            # Check if circuit is open
            if self.state == CircuitState.OPEN:
                if self.last_failure_time:
                    elapsed = datetime.now() - self.last_failure_time
                    if elapsed > self.timeout:
                        # Transition to half-open
                        self.state = CircuitState.HALF_OPEN
                        self.success_count = 0
                        self.logger.log_circuit_breaker(
                            breaker_name=self.name,
                            state="half_open",
                            failure_count=self.failure_count,
                            action="transitioned_to_half_open"
                        )
                    else:
                        raise Exception(
                            f"Circuit breaker '{self.name}' is OPEN. "
                            f"Last failure: {elapsed.total_seconds():.1f}s ago. "
                            f"Retry after {self.timeout.total_seconds():.1f}s"
                        )
        
        # Call function WITHOUT holding the lock (allows concurrent requests)
        # This prevents blocking when multiple requests call the same circuit breaker
        # The lock is only held for state checks/updates, not during function execution
        try:
            result = await func(*args, **kwargs)
            
            # Success - update state (with lock)
            async with self._lock:
                if self.state == CircuitState.HALF_OPEN:
                    self.success_count += 1
                    if self.success_count >= self.success_threshold:
                        self.state = CircuitState.CLOSED
                        self.failure_count = 0
                        self.success_count = 0
                        self.logger.log_circuit_breaker(
                            breaker_name=self.name,
                            state="closed",
                            failure_count=0,
                            action="recovered_to_closed"
                        )
                
                self.last_success_time = datetime.now()
            
            return result
                
        except Exception as e:
            # Failure - update state (with lock)
            async with self._lock:
                self.failure_count += 1
                self.last_failure_time = datetime.now()
                
                if self.state == CircuitState.HALF_OPEN:
                    # Any failure in half-open goes back to open
                    self.state = CircuitState.OPEN
                    self.success_count = 0
                    self.logger.log_circuit_breaker(
                        breaker_name=self.name,
                        state="open",
                        failure_count=self.failure_count,
                        action="failed_in_half_open"
                    )
                elif self.failure_count >= self.failure_threshold:
                    # Too many failures - open circuit
                    self.state = CircuitState.OPEN
                    self.logger.log_circuit_breaker(
                        breaker_name=self.name,
                        state="open",
                        failure_count=self.failure_count,
                        action="opened_after_threshold"
                    )
            
            raise
    
    def get_state(self) -> Dict[str, Any]:
        """Get current circuit breaker state."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_time": (
                self.last_failure_time.isoformat()
                if self.last_failure_time else None
            ),
            "last_success_time": (
                self.last_success_time.isoformat()
                if self.last_success_time else None
            )
        }
    
    def reset(self) -> None:
        """Manually reset circuit breaker to closed state."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self.last_success_time = None


class CircuitBreakerManager:
    """Manages multiple circuit breakers."""
    
    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()
    
    def get_breaker(
        self,
        name: str,
        failure_threshold: int = 5,
        timeout_seconds: int = 60,
        success_threshold: int = 2
    ) -> CircuitBreaker:
        """Get or create circuit breaker."""
        async def _get():
            async with self._lock:
                if name not in self._breakers:
                    self._breakers[name] = CircuitBreaker(
                        name=name,
                        failure_threshold=failure_threshold,
                        timeout_seconds=timeout_seconds,
                        success_threshold=success_threshold
                    )
                return self._breakers[name]
        
        # For sync access, create if not exists
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                timeout_seconds=timeout_seconds,
                success_threshold=success_threshold
            )
        return self._breakers[name]
    
    def get_all_states(self) -> Dict[str, Dict[str, Any]]:
        """Get states of all circuit breakers."""
        return {
            name: breaker.get_state()
            for name, breaker in self._breakers.items()
        }


# Global circuit breaker manager
_breaker_manager: Optional[CircuitBreakerManager] = None


def get_breaker_manager() -> CircuitBreakerManager:
    """Get global circuit breaker manager."""
    global _breaker_manager
    if _breaker_manager is None:
        _breaker_manager = CircuitBreakerManager()
    return _breaker_manager

