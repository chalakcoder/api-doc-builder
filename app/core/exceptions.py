"""
Custom exceptions and global error handling for the Spec Documentation API.
"""
import logging
from typing import Dict, Any, Optional
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import traceback

logger = logging.getLogger(__name__)


class SpecDocumentationAPIError(Exception):
    """Base exception for Spec Documentation API errors."""
    
    def __init__(self, message: str, error_code: str = None, details: Dict[str, Any] = None):
        self.message = message
        self.error_code = error_code or "GENERAL_ERROR"
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(SpecDocumentationAPIError):
    """Raised when input validation fails."""
    
    def __init__(self, message: str, field: str = None, details: Dict[str, Any] = None):
        super().__init__(message, "VALIDATION_ERROR", details)
        self.field = field


class SpecificationError(SpecDocumentationAPIError):
    """Raised when specification processing fails."""
    
    def __init__(self, message: str, spec_format: str = None, details: Dict[str, Any] = None):
        super().__init__(message, "SPECIFICATION_ERROR", details)
        self.spec_format = spec_format


class GenAIServiceError(SpecDocumentationAPIError):
    """Raised when GenAI service encounters an error."""
    
    def __init__(self, message: str, service_status: str = None, details: Dict[str, Any] = None):
        super().__init__(message, "GENAI_SERVICE_ERROR", details)
        self.service_status = service_status


class JobProcessingError(SpecDocumentationAPIError):
    """Raised when job processing fails."""
    
    def __init__(self, message: str, job_id: str = None, details: Dict[str, Any] = None):
        super().__init__(message, "JOB_PROCESSING_ERROR", details)
        self.job_id = job_id


class DatabaseError(SpecDocumentationAPIError):
    """Raised when database operations fail."""
    
    def __init__(self, message: str, operation: str = None, details: Dict[str, Any] = None):
        super().__init__(message, "DATABASE_ERROR", details)
        self.operation = operation


class RateLimitError(SpecDocumentationAPIError):
    """Raised when rate limit is exceeded."""
    
    def __init__(self, message: str, retry_after: int = None, details: Dict[str, Any] = None):
        super().__init__(message, "RATE_LIMIT_ERROR", details)
        self.retry_after = retry_after


class ConfigurationError(SpecDocumentationAPIError):
    """Raised when configuration is invalid or missing."""
    
    def __init__(self, message: str, config_key: str = None, details: Dict[str, Any] = None):
        super().__init__(message, "CONFIGURATION_ERROR", details)
        self.config_key = config_key


def create_error_response(
    error: Exception,
    status_code: int = 500,
    include_traceback: bool = False
) -> JSONResponse:
    """
    Create standardized error response.
    
    Args:
        error: Exception that occurred
        status_code: HTTP status code
        include_traceback: Whether to include traceback in response
        
    Returns:
        JSONResponse with error details
    """
    error_data = {
        "error": {
            "message": str(error),
            "type": type(error).__name__,
            "timestamp": logger.handlers[0].formatter.formatTime(
                logging.LogRecord("", 0, "", 0, "", (), None)
            ) if logger.handlers else None
        }
    }
    
    # Add specific error details for custom exceptions
    if isinstance(error, SpecDocumentationAPIError):
        error_data["error"]["code"] = error.error_code
        error_data["error"]["details"] = error.details
        
        # Add field-specific information for validation errors
        if isinstance(error, ValidationError) and error.field:
            error_data["error"]["field"] = error.field
            
        # Add job ID for job processing errors
        if isinstance(error, JobProcessingError) and error.job_id:
            error_data["error"]["job_id"] = error.job_id
            
        # Add retry information for rate limit errors
        if isinstance(error, RateLimitError) and error.retry_after:
            error_data["error"]["retry_after"] = error.retry_after
    
    # Add traceback for debugging (only in development)
    if include_traceback:
        error_data["error"]["traceback"] = traceback.format_exc()
    
    # Add request ID if available (would be set by middleware)
    # This helps with debugging and support
    error_data["error"]["request_id"] = getattr(error, "request_id", None)
    
    return JSONResponse(
        status_code=status_code,
        content=error_data
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Handle FastAPI validation errors.
    
    Args:
        request: FastAPI request object
        exc: Validation exception
        
    Returns:
        JSONResponse with validation error details
    """
    logger.warning(
        f"Validation error on {request.method} {request.url.path}",
        extra={
            "errors": exc.errors(),
            "body": exc.body if hasattr(exc, 'body') else None
        }
    )
    
    # Format validation errors in a user-friendly way
    formatted_errors = []
    for error in exc.errors():
        field_path = " -> ".join(str(loc) for loc in error["loc"])
        formatted_errors.append({
            "field": field_path,
            "message": error["msg"],
            "type": error["type"],
            "input": error.get("input")
        })
    
    error_response = {
        "error": {
            "message": "Request validation failed",
            "code": "VALIDATION_ERROR",
            "type": "RequestValidationError",
            "details": {
                "validation_errors": formatted_errors
            },
            "timestamp": logger.handlers[0].formatter.formatTime(
                logging.LogRecord("", 0, "", 0, "", (), None)
            ) if logger.handlers else None
        }
    }
    
    return JSONResponse(
        status_code=422,
        content=error_response
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    Handle HTTP exceptions.
    
    Args:
        request: FastAPI request object
        exc: HTTP exception
        
    Returns:
        JSONResponse with HTTP error details
    """
    logger.warning(
        f"HTTP {exc.status_code} error on {request.method} {request.url.path}: {exc.detail}"
    )
    
    error_response = {
        "error": {
            "message": exc.detail,
            "code": f"HTTP_{exc.status_code}",
            "type": "HTTPException",
            "timestamp": logger.handlers[0].formatter.formatTime(
                logging.LogRecord("", 0, "", 0, "", (), None)
            ) if logger.handlers else None
        }
    }
    
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle all other exceptions.
    
    Args:
        request: FastAPI request object
        exc: Exception that occurred
        
    Returns:
        JSONResponse with error details
    """
    # Log the full exception with traceback
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path}",
        exc_info=True,
        extra={
            "exception_type": type(exc).__name__,
            "exception_message": str(exc)
        }
    )
    
    # Determine if we should include traceback (only in development)
    from app.core.config import settings
    include_traceback = settings.DEBUG
    
    # Create appropriate status code based on exception type
    status_code = 500
    
    if isinstance(exc, SpecDocumentationAPIError):
        # Map custom exceptions to appropriate HTTP status codes
        status_code_mapping = {
            ValidationError: 400,
            SpecificationError: 400,
            GenAIServiceError: 502,
            JobProcessingError: 500,
            DatabaseError: 503,
            RateLimitError: 429,
            ConfigurationError: 500
        }
        status_code = status_code_mapping.get(type(exc), 500)
    
    return create_error_response(
        error=exc,
        status_code=status_code,
        include_traceback=include_traceback
    )


def setup_exception_handlers(app) -> None:
    """
    Set up global exception handlers for the FastAPI application.
    
    Args:
        app: FastAPI application instance
    """
    # Add custom exception handlers
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    
    logger.info("Global exception handlers configured")


class ErrorContext:
    """
    Context manager for adding error context to exceptions.
    
    This helps provide more detailed error information when exceptions
    are caught and re-raised.
    """
    
    def __init__(self, operation: str, **context):
        self.operation = operation
        self.context = context
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val is not None:
            # Add context to the exception
            if hasattr(exc_val, 'details'):
                exc_val.details.update({
                    "operation": self.operation,
                    **self.context
                })
            else:
                # For non-custom exceptions, add context as attributes
                exc_val.error_context = {
                    "operation": self.operation,
                    **self.context
                }
        
        # Don't suppress the exception
        return False


def handle_service_errors(operation: str):
    """
    Decorator for handling service-level errors with consistent logging and error transformation.
    
    Args:
        operation: Description of the operation being performed
        
    Returns:
        Decorator function
    """
    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except SpecDocumentationAPIError:
                # Re-raise custom exceptions as-is
                raise
            except Exception as e:
                logger.error(
                    f"Service error in {operation}",
                    exc_info=True,
                    extra={
                        "operation": operation,
                        "function": func.__name__,
                        "function_args": str(args)[:200],  # Truncate for logging
                        "function_kwargs": str(kwargs)[:200]
                    }
                )
                
                # Transform generic exceptions to custom ones
                raise SpecDocumentationAPIError(
                    message=f"Service error in {operation}: {str(e)}",
                    error_code="SERVICE_ERROR",
                    details={
                        "operation": operation,
                        "original_error": str(e),
                        "error_type": type(e).__name__
                    }
                )
        
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except SpecDocumentationAPIError:
                # Re-raise custom exceptions as-is
                raise
            except Exception as e:
                logger.error(
                    f"Service error in {operation}",
                    exc_info=True,
                    extra={
                        "operation": operation,
                        "function": func.__name__,
                        "function_args": str(args)[:200],
                        "function_kwargs": str(kwargs)[:200]
                    }
                )
                
                raise SpecDocumentationAPIError(
                    message=f"Service error in {operation}: {str(e)}",
                    error_code="SERVICE_ERROR",
                    details={
                        "operation": operation,
                        "original_error": str(e),
                        "error_type": type(e).__name__
                    }
                )
        
        # Return appropriate wrapper based on function type
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator