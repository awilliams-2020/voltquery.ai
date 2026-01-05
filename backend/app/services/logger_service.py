"""
Structured logging service for RAG system.

Provides structured JSON logging for better observability and debugging.
"""

import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum


class LogLevel(Enum):
    """Log levels."""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class StructuredLogger:
    """
    Structured logger that outputs JSON-formatted logs.
    
    Makes it easier to parse logs and extract metrics.
    """
    
    def __init__(self, name: str, log_level: str = "INFO"):
        """
        Initialize structured logger.
        
        Args:
            name: Logger name (usually module/service name)
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, log_level.upper()))
        
        # Create console handler if not exists
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setLevel(getattr(logging, log_level.upper()))
            self.logger.addHandler(handler)
    
    def _log(self, level: LogLevel, event: str, data: Dict[str, Any]):
        """
        Log structured data.
        
        Args:
            level: Log level
            event: Event name (e.g., "query", "api_call", "error")
            data: Structured data dictionary
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level.value,
            "event": event,
            **data
        }
        
        log_message = json.dumps(log_entry)
        
        if level == LogLevel.DEBUG:
            self.logger.debug(log_message)
        elif level == LogLevel.INFO:
            self.logger.info(log_message)
        elif level == LogLevel.WARNING:
            self.logger.warning(log_message)
        elif level == LogLevel.ERROR:
            self.logger.error(log_message)
        elif level == LogLevel.CRITICAL:
            self.logger.critical(log_message)
    
    def log_query(
        self,
        question: str,
        user_id: Optional[str] = None,
        tools_used: Optional[List[str]] = None,
        response_time_ms: Optional[float] = None,
        success: bool = True,
        error: Optional[str] = None,
        num_sources: Optional[int] = None,
        zip_code: Optional[str] = None
    ):
        """
        Log a query event.
        
        Args:
            question: User question
            user_id: User ID (optional)
            tools_used: List of tools used (optional)
            response_time_ms: Response time in milliseconds (optional)
            success: Whether query succeeded
            error: Error message if failed (optional)
            num_sources: Number of sources returned (optional)
            zip_code: Zip code used (optional)
        """
        data = {
            "question": question,
            "success": success
        }
        
        if user_id:
            data["user_id"] = user_id
        if tools_used:
            data["tools_used"] = tools_used
        if response_time_ms is not None:
            data["response_time_ms"] = response_time_ms
        if error:
            data["error"] = error
        if num_sources is not None:
            data["num_sources"] = num_sources
        if zip_code:
            data["zip_code"] = zip_code
        
        level = LogLevel.ERROR if error else LogLevel.INFO
        self._log(level, "query", data)
    
    def log_api_call(
        self,
        service: str,
        endpoint: str,
        method: str = "GET",
        status_code: Optional[int] = None,
        response_time_ms: Optional[float] = None,
        success: bool = True,
        error: Optional[str] = None,
        cache_hit: Optional[bool] = None
    ):
        """
        Log an API call.
        
        Args:
            service: Service name (e.g., "nrel", "geocoding")
            endpoint: API endpoint
            method: HTTP method
            status_code: HTTP status code (optional)
            response_time_ms: Response time in milliseconds (optional)
            success: Whether call succeeded
            error: Error message if failed (optional)
            cache_hit: Whether cache was hit (optional)
        """
        data = {
            "service": service,
            "endpoint": endpoint,
            "method": method,
            "success": success
        }
        
        if status_code:
            data["status_code"] = status_code
        if response_time_ms is not None:
            data["response_time_ms"] = response_time_ms
        if error:
            data["error"] = error
        if cache_hit is not None:
            data["cache_hit"] = cache_hit
        
        level = LogLevel.ERROR if error else LogLevel.INFO
        self._log(level, "api_call", data)
    
    def log_circuit_breaker(
        self,
        breaker_name: str,
        state: str,
        failure_count: int,
        action: str
    ):
        """
        Log circuit breaker state change.
        
        Args:
            breaker_name: Circuit breaker name
            state: New state (closed, open, half_open)
            failure_count: Current failure count
            action: Action taken (opened, closed, half_opened)
        """
        data = {
            "breaker_name": breaker_name,
            "state": state,
            "failure_count": failure_count,
            "action": action
        }
        
        level = LogLevel.WARNING if state == "open" else LogLevel.INFO
        self._log(level, "circuit_breaker", data)
    
    def log_cache(
        self,
        operation: str,
        key: str,
        cache_hit: bool,
        ttl_seconds: Optional[int] = None
    ):
        """
        Log cache operation.
        
        Args:
            operation: Operation type (get, set, clear)
            key: Cache key
            cache_hit: Whether cache hit occurred
            ttl_seconds: TTL in seconds (optional)
        """
        data = {
            "operation": operation,
            "key": key[:100],  # Truncate long keys
            "cache_hit": cache_hit
        }
        
        if ttl_seconds:
            data["ttl_seconds"] = ttl_seconds
        
        self._log(LogLevel.DEBUG, "cache", data)
    
    def log_tool_execution(
        self,
        tool_name: str,
        question: str,
        success: bool,
        response_time_ms: Optional[float] = None,
        error: Optional[str] = None,
        response_length: Optional[int] = None
    ):
        """
        Log tool execution.
        
        Args:
            tool_name: Tool name (e.g., "utility_tool", "solar_production_tool")
            question: Sub-question asked
            success: Whether tool succeeded
            response_time_ms: Response time in milliseconds (optional)
            error: Error message if failed (optional)
            response_length: Length of response (optional)
        """
        data = {
            "tool_name": tool_name,
            "question": question[:200],  # Truncate long questions
            "success": success
        }
        
        if response_time_ms is not None:
            data["response_time_ms"] = response_time_ms
        if error:
            data["error"] = error
        if response_length is not None:
            data["response_length"] = response_length
        
        level = LogLevel.ERROR if error else LogLevel.INFO
        self._log(level, "tool_execution", data)
    
    def log_error(
        self,
        error_type: str,
        error_message: str,
        context: Optional[Dict[str, Any]] = None
    ):
        """
        Log an error.
        
        Args:
            error_type: Type of error (e.g., "ValidationError", "APIError")
            error_message: Error message
            context: Additional context (optional)
        """
        data = {
            "error_type": error_type,
            "error_message": error_message
        }
        
        if context:
            data.update(context)
        
        self._log(LogLevel.ERROR, "error", data)


# Global logger instances
_loggers: Dict[str, StructuredLogger] = {}


def get_logger(name: str, log_level: str = "INFO") -> StructuredLogger:
    """
    Get or create a structured logger instance.
    
    Args:
        name: Logger name
        log_level: Logging level
        
    Returns:
        StructuredLogger instance
    """
    if name not in _loggers:
        _loggers[name] = StructuredLogger(name, log_level)
    return _loggers[name]

