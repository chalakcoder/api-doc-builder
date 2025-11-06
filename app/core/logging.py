"""
Enhanced structured logging configuration with correlation IDs and context information.
"""
import logging
import sys
import uuid
import contextvars
from typing import Any, Dict, Optional
from datetime import datetime

import structlog
from structlog.stdlib import LoggerFactory

from app.core.config import settings

# Context variable for correlation ID tracking
correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar('correlation_id', default=None)
request_context_var: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar('request_context', default={})


class CorrelationIDProcessor:
    """Processor to add correlation ID to log entries."""
    
    def __call__(self, logger, method_name, event_dict):
        correlation_id = correlation_id_var.get()
        if correlation_id:
            event_dict['correlation_id'] = correlation_id
        return event_dict


class RequestContextProcessor:
    """Processor to add request context to log entries."""
    
    def __call__(self, logger, method_name, event_dict):
        context = request_context_var.get()
        if context:
            # Add selected context fields to avoid log bloat
            if 'method' in context:
                event_dict['request_method'] = context['method']
            if 'path' in context:
                event_dict['request_path'] = context['path']
            if 'client_host' in context:
                event_dict['client_host'] = context['client_host']
            if 'user_agent' in context:
                event_dict['user_agent'] = context['user_agent'][:100]  # Truncate long user agents
        return event_dict


class SensitiveDataSanitizer:
    """Processor to sanitize sensitive data from log entries."""
    
    SENSITIVE_KEYS = {
        'password', 'token', 'secret', 'key', 'auth', 'authorization',
        'api_key', 'access_token', 'refresh_token', 'session_id',
        'cookie', 'x-api-key', 'bearer', 'credentials'
    }
    
    def __call__(self, logger, method_name, event_dict):
        return self._sanitize_dict(event_dict)
    
    def _sanitize_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively sanitize dictionary data."""
        if not isinstance(data, dict):
            return data
        
        sanitized = {}
        for key, value in data.items():
            key_lower = str(key).lower()
            
            # Check if key contains sensitive information
            if any(sensitive in key_lower for sensitive in self.SENSITIVE_KEYS):
                sanitized[key] = "[REDACTED]"
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_dict(value)
            elif isinstance(value, list):
                sanitized[key] = [self._sanitize_dict(item) if isinstance(item, dict) else item for item in value]
            elif isinstance(value, str) and len(value) > 1000:
                # Truncate very long strings to prevent log flooding
                sanitized[key] = value[:1000] + "... [TRUNCATED]"
            else:
                sanitized[key] = value
        
        return sanitized


def setup_logging() -> None:
    """Configure enhanced structured logging for the application."""
    
    # Configure structlog with enhanced processors
    structlog.configure(
        processors=[
            # Add correlation ID and request context
            CorrelationIDProcessor(),
            RequestContextProcessor(),
            # Standard processors
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # Sanitize sensitive data
            SensitiveDataSanitizer(),
            # Choose output format based on settings
            _get_renderer(),
        ],
        context_class=dict,
        logger_factory=LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.LOG_LEVEL.upper()),
    )
    
    # Set specific logger levels
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def _get_renderer():
    """Get the appropriate log renderer based on configuration."""
    if settings.LOG_FORMAT.lower() == "json":
        return structlog.processors.JSONRenderer()
    else:
        return structlog.dev.ConsoleRenderer(colors=True)


def get_logger(name: str = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)


def set_correlation_id(correlation_id: str) -> None:
    """Set correlation ID for current context."""
    correlation_id_var.set(correlation_id)


def get_correlation_id() -> Optional[str]:
    """Get correlation ID from current context."""
    return correlation_id_var.get()


def set_request_context(context: Dict[str, Any]) -> None:
    """Set request context for current context."""
    request_context_var.set(context)


def get_request_context() -> Dict[str, Any]:
    """Get request context from current context."""
    return request_context_var.get() or {}


def generate_correlation_id() -> str:
    """Generate a new correlation ID."""
    return str(uuid.uuid4())


class EnhancedLoggerMixin:
    """Enhanced mixin class to add structured logging with context to any class."""
    
    @property
    def logger(self) -> structlog.stdlib.BoundLogger:
        """Get logger instance for this class with automatic context binding."""
        logger = get_logger(self.__class__.__name__)
        
        # Bind correlation ID if available
        correlation_id = get_correlation_id()
        if correlation_id:
            logger = logger.bind(correlation_id=correlation_id)
        
        # Bind class context
        logger = logger.bind(component=self.__class__.__name__)
        
        return logger
    
    def log_operation_start(self, operation: str, **context) -> None:
        """Log the start of an operation with context."""
        self.logger.info(f"Starting {operation}", operation=operation, **context)
    
    def log_operation_success(self, operation: str, duration_ms: float = None, **context) -> None:
        """Log successful completion of an operation."""
        log_data = {"operation": operation, **context}
        if duration_ms is not None:
            log_data["duration_ms"] = duration_ms
        self.logger.info(f"Completed {operation}", **log_data)
    
    def log_operation_error(self, operation: str, error: Exception, duration_ms: float = None, **context) -> None:
        """Log error during an operation."""
        log_data = {
            "operation": operation,
            "error_type": type(error).__name__,
            "error_message": str(error),
            **context
        }
        if duration_ms is not None:
            log_data["duration_ms"] = duration_ms
        self.logger.error(f"Failed {operation}", **log_data)


class LoggerMixin(EnhancedLoggerMixin):
    """Backward compatibility alias for LoggerMixin."""
    pass


class PerformanceLogger:
    """Logger for performance metrics and monitoring."""
    
    def __init__(self):
        self.logger = get_logger("performance")
    
    def log_request_performance(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        **context
    ) -> None:
        """Log request performance metrics."""
        self.logger.info(
            "Request performance",
            request_method=method,
            request_path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            **context
        )
    
    def log_database_performance(
        self,
        operation: str,
        duration_ms: float,
        success: bool,
        **context
    ) -> None:
        """Log database operation performance."""
        self.logger.info(
            "Database performance",
            db_operation=operation,
            duration_ms=duration_ms,
            success=success,
            **context
        )
    
    def log_service_performance(
        self,
        service: str,
        operation: str,
        duration_ms: float,
        success: bool,
        **context
    ) -> None:
        """Log service operation performance."""
        self.logger.info(
            "Service performance",
            service=service,
            operation=operation,
            duration_ms=duration_ms,
            success=success,
            **context
        )