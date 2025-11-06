"""
Enhanced exceptions and global error handling for the Spec Documentation API.
"""
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel
import traceback

from app.core.logging import get_logger, get_correlation_id
from app.services.error_pattern_tracker import track_error_pattern

logger = get_logger(__name__)


# Enhanced error response models
class ErrorDetails(BaseModel):
    """Detailed error information model."""
    message: str
    code: str
    type: str
    details: Optional[Dict[str, Any]] = None
    field: Optional[str] = None  # For validation errors
    retry_after: Optional[int] = None  # For rate limit errors
    correlation_id: Optional[str] = None


class StandardErrorResponse(BaseModel):
    """Standardized error response format."""
    error: ErrorDetails
    request_id: str
    timestamp: datetime
    path: Optional[str] = None
    method: Optional[str] = None


class ValidationErrorDetail(BaseModel):
    """Detailed validation error information."""
    field: str
    message: str
    type: str
    input: Optional[Any] = None


class FieldValidationError(BaseModel):
    """Field-level validation error details."""
    field: str
    errors: List[ValidationErrorDetail]


class EnhancedValidationErrorResponse(BaseModel):
    """Enhanced validation error response with field-level details."""
    error: ErrorDetails
    request_id: str
    timestamp: datetime
    path: Optional[str] = None
    method: Optional[str] = None
    field_errors: List[FieldValidationError] = []


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


# Utility functions for error handling
def generate_correlation_id() -> str:
    """Generate a unique correlation ID for request tracing."""
    return str(uuid.uuid4())


def sanitize_error_details(details: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize error details to prevent sensitive data leakage.
    
    Args:
        details: Raw error details dictionary
        
    Returns:
        Sanitized error details
    """
    if not details:
        return {}
    
    # List of sensitive keys to remove or mask
    sensitive_keys = {
        'password', 'token', 'secret', 'key', 'auth', 'authorization',
        'api_key', 'access_token', 'refresh_token', 'session_id',
        'cookie', 'x-api-key', 'bearer'
    }
    
    sanitized = {}
    for key, value in details.items():
        key_lower = key.lower()
        
        # Check if key contains sensitive information
        if any(sensitive in key_lower for sensitive in sensitive_keys):
            sanitized[key] = "[REDACTED]"
        elif isinstance(value, dict):
            # Recursively sanitize nested dictionaries
            sanitized[key] = sanitize_error_details(value)
        elif isinstance(value, str) and len(value) > 500:
            # Truncate very long strings to prevent log flooding
            sanitized[key] = value[:500] + "... [TRUNCATED]"
        else:
            sanitized[key] = value
    
    return sanitized


def get_request_context(request: Request) -> Dict[str, Any]:
    """
    Extract relevant context information from request.
    
    Args:
        request: FastAPI request object
        
    Returns:
        Dictionary containing request context
    """
    context = {
        "method": request.method,
        "path": str(request.url.path),
        "query_params": dict(request.query_params),
        "client_host": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "content_type": request.headers.get("content-type")
    }
    
    # Add correlation ID if present in headers
    correlation_id = request.headers.get("x-correlation-id")
    if correlation_id:
        context["correlation_id"] = correlation_id
    
    return context


def create_error_response(
    error: Exception,
    status_code: int = 500,
    include_traceback: bool = False,
    request: Optional[Request] = None,
    correlation_id: Optional[str] = None
) -> JSONResponse:
    """
    Create standardized error response with enhanced context.
    
    Args:
        error: Exception that occurred
        status_code: HTTP status code
        include_traceback: Whether to include traceback in response
        request: FastAPI request object for context
        correlation_id: Optional correlation ID for tracing
        
    Returns:
        JSONResponse with standardized error details
    """
    # Generate correlation ID if not provided
    if not correlation_id:
        correlation_id = generate_correlation_id()
    
    # Get request context if available
    request_context = get_request_context(request) if request else {}
    
    # Create error details
    error_details = ErrorDetails(
        message=str(error),
        code="GENERAL_ERROR",
        type=type(error).__name__,
        correlation_id=correlation_id
    )
    
    # Add specific error details for custom exceptions
    if isinstance(error, SpecDocumentationAPIError):
        error_details.code = error.error_code
        error_details.details = sanitize_error_details(error.details) if error.details else None
        
        # Add field-specific information for validation errors
        if isinstance(error, ValidationError) and error.field:
            error_details.field = error.field
            
        # Add retry information for rate limit errors
        if isinstance(error, RateLimitError) and error.retry_after:
            error_details.retry_after = error.retry_after
    
    # Create standardized response
    response_data = StandardErrorResponse(
        error=error_details,
        request_id=correlation_id,
        timestamp=datetime.utcnow(),
        path=request_context.get("path"),
        method=request_context.get("method")
    )
    
    # Add traceback for debugging (only in development)
    if include_traceback:
        if not response_data.error.details:
            response_data.error.details = {}
        response_data.error.details["traceback"] = traceback.format_exc()
    
    # Set response headers for correlation tracking
    headers = {
        "X-Correlation-ID": correlation_id,
        "X-Error-Code": error_details.code
    }
    
    # Add retry-after header for rate limit errors
    if isinstance(error, RateLimitError) and error.retry_after:
        headers["Retry-After"] = str(error.retry_after)
    
    return JSONResponse(
        status_code=status_code,
        content=response_data.dict(),
        headers=headers
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Handle FastAPI validation errors with enhanced field-level details and error tracking.
    
    Args:
        request: FastAPI request object
        exc: Validation exception
        
    Returns:
        JSONResponse with detailed validation error information
    """
    # Get correlation ID from context or generate new one
    correlation_id = get_correlation_id() or request.headers.get("x-correlation-id") or generate_correlation_id()
    
    # Track error pattern
    track_error_pattern(
        error_type="RequestValidationError",
        endpoint=str(request.url.path),
        error_code="VALIDATION_ERROR",
        correlation_id=correlation_id,
        additional_context={
            "method": request.method,
            "error_count": len(exc.errors()),
            "client_host": request.client.host if request.client else None
        }
    )
    
    # Log validation error with structured logging
    logger.warning(
        "Request validation failed",
        error_count=len(exc.errors()),
        errors=exc.errors(),
        body_present=hasattr(exc, 'body') and exc.body is not None,
        method=request.method,
        path=str(request.url.path)
    )
    
    # Group validation errors by field for better organization
    field_errors = {}
    for error in exc.errors():
        field_path = " -> ".join(str(loc) for loc in error["loc"])
        
        if field_path not in field_errors:
            field_errors[field_path] = []
        
        field_errors[field_path].append(ValidationErrorDetail(
            field=field_path,
            message=error["msg"],
            type=error["type"],
            input=error.get("input")
        ))
    
    # Create field validation errors list
    field_validation_errors = [
        FieldValidationError(field=field, errors=errors)
        for field, errors in field_errors.items()
    ]
    
    # Create error details
    error_details = ErrorDetails(
        message="Request validation failed",
        code="VALIDATION_ERROR",
        type="RequestValidationError",
        correlation_id=correlation_id,
        details={
            "total_errors": len(exc.errors()),
            "fields_with_errors": list(field_errors.keys())
        }
    )
    
    # Create enhanced validation error response
    response_data = EnhancedValidationErrorResponse(
        error=error_details,
        request_id=correlation_id,
        timestamp=datetime.utcnow(),
        path=str(request.url.path),
        method=request.method,
        field_errors=field_validation_errors
    )
    
    # Set response headers
    headers = {
        "X-Correlation-ID": correlation_id,
        "X-Error-Code": "VALIDATION_ERROR",
        "X-Validation-Errors": str(len(exc.errors()))
    }
    
    return JSONResponse(
        status_code=422,
        content=response_data.dict(),
        headers=headers
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    Handle HTTP exceptions with enhanced context, correlation tracking, and error pattern analysis.
    
    Args:
        request: FastAPI request object
        exc: HTTP exception
        
    Returns:
        JSONResponse with standardized HTTP error details
    """
    # Get correlation ID from context or generate new one
    correlation_id = get_correlation_id() or request.headers.get("x-correlation-id") or generate_correlation_id()
    
    # Track error pattern
    track_error_pattern(
        error_type="HTTPException",
        endpoint=str(request.url.path),
        error_code=f"HTTP_{exc.status_code}",
        correlation_id=correlation_id,
        additional_context={
            "method": request.method,
            "status_code": exc.status_code,
            "detail": str(exc.detail)[:200],  # Truncate long details
            "client_host": request.client.host if request.client else None
        }
    )
    
    # Log HTTP error with structured logging
    logger.warning(
        "HTTP exception occurred",
        status_code=exc.status_code,
        detail=exc.detail,
        method=request.method,
        path=str(request.url.path),
        user_agent=request.headers.get("user-agent", "")[:100]  # Truncate long user agents
    )
    
    # Create error details with retry guidance for specific status codes
    error_details = ErrorDetails(
        message=exc.detail,
        code=f"HTTP_{exc.status_code}",
        type="HTTPException",
        correlation_id=correlation_id
    )
    
    # Add retry guidance for specific error types
    if exc.status_code == 429:  # Too Many Requests
        error_details.retry_after = 60  # Default retry after 60 seconds
        error_details.details = {
            "retry_guidance": "Request rate limit exceeded. Please wait before retrying.",
            "suggested_action": "Implement exponential backoff in your client"
        }
    elif exc.status_code == 503:  # Service Unavailable
        error_details.retry_after = 30
        error_details.details = {
            "retry_guidance": "Service temporarily unavailable. Please retry after a short delay.",
            "suggested_action": "Check system status and retry with exponential backoff"
        }
    elif exc.status_code == 502:  # Bad Gateway
        error_details.details = {
            "retry_guidance": "Upstream service error. This may be temporary.",
            "suggested_action": "Retry the request after a brief delay"
        }
    
    # Create standardized response
    response_data = StandardErrorResponse(
        error=error_details,
        request_id=correlation_id,
        timestamp=datetime.utcnow(),
        path=str(request.url.path),
        method=request.method
    )
    
    # Set response headers
    headers = {
        "X-Correlation-ID": correlation_id,
        "X-Error-Code": error_details.code
    }
    
    # Add retry-after header for rate limiting and service unavailable
    if error_details.retry_after:
        headers["Retry-After"] = str(error_details.retry_after)
    
    return JSONResponse(
        status_code=exc.status_code,
        content=response_data.dict(),
        headers=headers
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Handle all other exceptions with enhanced logging, context, and error pattern tracking.
    
    Args:
        request: FastAPI request object
        exc: Exception that occurred
        
    Returns:
        JSONResponse with standardized error details
    """
    # Get correlation ID from context or generate new one
    correlation_id = get_correlation_id() or request.headers.get("x-correlation-id") or generate_correlation_id()
    
    # Get request context for logging
    request_context = get_request_context(request)
    
    # Determine error code for tracking
    error_code = "GENERAL_ERROR"
    if isinstance(exc, SpecDocumentationAPIError):
        error_code = exc.error_code
    
    # Track error pattern
    track_error_pattern(
        error_type=type(exc).__name__,
        endpoint=str(request.url.path),
        error_code=error_code,
        correlation_id=correlation_id,
        additional_context={
            "method": request.method,
            "exception_message": str(exc)[:200],  # Truncate long messages
            "client_host": request.client.host if request.client else None
        }
    )
    
    # Log the full exception with enhanced structured logging
    logger.error(
        "Unhandled exception occurred",
        exception_type=type(exc).__name__,
        exception_message=str(exc),
        method=request.method,
        path=str(request.url.path),
        request_context=sanitize_error_details(request_context),
        exc_info=True
    )
    
    # Determine if we should include traceback (only in development)
    try:
        from app.core.config import settings
        include_traceback = getattr(settings, 'DEBUG', False)
    except ImportError:
        include_traceback = False
    
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
        include_traceback=include_traceback,
        request=request,
        correlation_id=correlation_id
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