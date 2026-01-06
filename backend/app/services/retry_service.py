"""
Retry service with exponential backoff for resilient API calls.

Provides retry logic without external dependencies.
"""

import asyncio
import time
from typing import TypeVar, Callable, Optional, List, Type
from functools import wraps
from app.services.logger_service import get_logger

T = TypeVar('T')


class RetryConfig:
    """Configuration for retry behavior."""
    
    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: Optional[List[Type[Exception]]] = None
    ):
        """
        Initialize retry configuration.
        
        Args:
            max_attempts: Maximum number of retry attempts (default: 3)
            initial_delay: Initial delay in seconds (default: 1.0)
            max_delay: Maximum delay in seconds (default: 60.0)
            exponential_base: Base for exponential backoff (default: 2.0)
            jitter: Whether to add random jitter to delays (default: True)
            retryable_exceptions: List of exception types to retry (default: all)
        """
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions or [Exception]
    
    def calculate_delay(self, attempt: int) -> float:
        """
        Calculate delay for retry attempt.
        
        Args:
            attempt: Current attempt number (0-indexed)
            
        Returns:
            Delay in seconds
        """
        delay = self.initial_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)
        
        if self.jitter:
            import random
            # Add ±20% jitter
            jitter_amount = delay * 0.2
            delay += random.uniform(-jitter_amount, jitter_amount)
            delay = max(0.1, delay)  # Ensure minimum delay
        
        return delay


def retry_with_backoff(config: Optional[RetryConfig] = None):
    """
    Decorator for retrying async functions with exponential backoff.
    
    Usage:
        @retry_with_backoff(RetryConfig(max_attempts=3))
        async def my_function():
            ...
    """
    if config is None:
        config = RetryConfig()
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            logger = get_logger("retry_service")
            last_exception = None
            
            for attempt in range(config.max_attempts):
                try:
                    result = await func(*args, **kwargs)
                    if attempt > 0:
                        logger.log_api_call(
                            service=func.__name__,
                            endpoint="retry_success",
                            success=True,
                            response_time_ms=0
                        )
                    return result
                except Exception as e:
                    last_exception = e
                    
                    # Check if exception is retryable
                    if not any(isinstance(e, exc_type) for exc_type in config.retryable_exceptions):
                        raise
                    
                    # Don't retry on last attempt
                    if attempt == config.max_attempts - 1:
                        break
                    
                    # Calculate delay
                    delay = config.calculate_delay(attempt)
                    
                    logger.log_error(
                        error_type=type(e).__name__,
                        error_message=f"Attempt {attempt + 1}/{config.max_attempts} failed: {str(e)}",
                        context={
                            "function": func.__name__,
                            "attempt": attempt + 1,
                            "max_attempts": config.max_attempts,
                            "delay_seconds": delay
                        }
                    )
                    
                    await asyncio.sleep(delay)
            
            # All attempts failed
            if last_exception:
                raise last_exception
            
        return wrapper
    return decorator


class RetryService:
    """
    Service for retrying operations with exponential backoff.
    
    Provides both decorator and direct call patterns.
    """
    
    def __init__(self, default_config: Optional[RetryConfig] = None):
        """
        Initialize retry service.
        
        Args:
            default_config: Default retry configuration
        """
        self.default_config = default_config or RetryConfig()
        self.logger = get_logger("retry_service")
    
    async def retry(
        self,
        func: Callable[..., T],
        *args,
        config: Optional[RetryConfig] = None,
        **kwargs
    ) -> T:
        """
        Retry a function with exponential backoff.
        
        Args:
            func: Async function to retry
            *args: Positional arguments for function
            config: Retry configuration (uses default if not provided)
            **kwargs: Keyword arguments for function
            
        Returns:
            Function result
            
        Raises:
            Exception: Last exception if all attempts fail
        """
        retry_config = config or self.default_config
        last_exception = None
        
        for attempt in range(retry_config.max_attempts):
            try:
                result = await func(*args, **kwargs)
                if attempt > 0:
                    self.logger.log_api_call(
                        service=func.__name__ if hasattr(func, '__name__') else "unknown",
                        endpoint="retry_success",
                        success=True
                    )
                return result
            except Exception as e:
                last_exception = e
                
                # Check if exception is retryable
                if not any(isinstance(e, exc_type) for exc_type in retry_config.retryable_exceptions):
                    raise
                
                # Don't retry on last attempt
                if attempt == retry_config.max_attempts - 1:
                    break
                
                # Calculate delay
                delay = retry_config.calculate_delay(attempt)
                
                self.logger.log_error(
                    error_type=type(e).__name__,
                    error_message=f"Attempt {attempt + 1}/{retry_config.max_attempts} failed: {str(e)}",
                    context={
                        "function": func.__name__ if hasattr(func, '__name__') else "unknown",
                        "attempt": attempt + 1,
                        "max_attempts": retry_config.max_attempts,
                        "delay_seconds": delay
                    }
                )
                
                await asyncio.sleep(delay)
        
        # All attempts failed
        if last_exception:
            raise last_exception


# Global retry service instance
_retry_service: Optional[RetryService] = None


def get_retry_service() -> RetryService:
    """Get global retry service instance."""
    global _retry_service
    if _retry_service is None:
        _retry_service = RetryService()
    return _retry_service

