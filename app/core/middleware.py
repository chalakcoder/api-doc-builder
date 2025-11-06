"""
Enhanced middleware for the Spec Documentation API with structured logging.
"""
import time
import uuid
from typing import Callable
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.rate_limiter import rate_limiter
from app.core.logging import (
    get_logger, 
    set_correlation_id, 
    set_request_context, 
    generate_correlation_id,
    PerformanceLogger
)

logger = get_logger(__name__)
performance_logger = PerformanceLogger()


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """
    Enhanced middleware to add correlation IDs to requests for tracing.
    
    This middleware ensures every request has a correlation ID for
    better debugging and request tracing across services, and sets
    up the logging context.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Add correlation ID to request and response headers, set up logging context."""
        
        # Get correlation ID from request headers or generate new one
        correlation_id = request.headers.get("x-correlation-id")
        if not correlation_id:
            correlation_id = generate_correlation_id()
        
        # Set correlation ID in context for logging
        set_correlation_id(correlation_id)
        
        # Add correlation ID to request state for access in handlers
        request.state.correlation_id = correlation_id
        
        # Set up request context for logging
        request_context = {
            "method": request.method,
            "path": str(request.url.path),
            "query_params": dict(request.query_params),
            "client_host": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
            "content_type": request.headers.get("content-type"),
            "correlation_id": correlation_id
        }
        set_request_context(request_context)
        
        # Log request initiation
        logger.info(
            "Request initiated",
            method=request.method,
            path=str(request.url.path),
            client_host=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:100]  # Truncate long user agents
        )
        
        # Process the request
        response = await call_next(request)
        
        # Add correlation ID to response headers
        if isinstance(response, (Response, JSONResponse)):
            response.headers["X-Correlation-ID"] = correlation_id
        
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add rate limiting headers to responses.
    
    This middleware adds rate limit information to response headers
    for better client experience.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and add rate limiting headers."""
        
        # Skip rate limiting for health checks and system endpoints
        if request.url.path in ["/health", "/api/v1/health", "/api/v1/health/detailed"]:
            return await call_next(request)
        
        try:
            # Get rate limit status without incrementing
            rate_status = await rate_limiter.get_rate_limit_status(request)
            
            # Process the request
            response = await call_next(request)
            
            # Add rate limit headers to response
            if isinstance(response, (Response, JSONResponse)):
                response.headers["X-RateLimit-Limit"] = str(rate_status.get("requests_remaining", 0) + rate_status.get("requests_made", 0))
                response.headers["X-RateLimit-Remaining"] = str(rate_status.get("requests_remaining", 0))
                response.headers["X-RateLimit-Reset"] = str(rate_status.get("reset_time", int(time.time()) + 60))
            
            return response
            
        except Exception as e:
            logger.error(f"Rate limit middleware error: {e}")
            # Continue with request even if rate limiting fails
            return await call_next(request)


class EnhancedLoggingMiddleware(BaseHTTPMiddleware):
    """
    Enhanced middleware for request/response logging with structured logging and performance metrics.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Log request and response information with enhanced context and performance tracking."""
        
        start_time = time.time()
        
        # Get correlation ID from request state (set by CorrelationIDMiddleware)
        correlation_id = getattr(request.state, 'correlation_id', 'unknown')
        
        # Skip detailed logging for health check endpoints to reduce noise
        is_health_check = request.url.path in ["/health", "/api/v1/health", "/api/v1/health/detailed"]
        
        if not is_health_check:
            # Log request start with structured data
            logger.info(
                "Request started",
                method=request.method,
                path=str(request.url.path),
                query_params=dict(request.query_params) if request.query_params else None,
                content_length=request.headers.get("content-length"),
                content_type=request.headers.get("content-type")
            )
        
        try:
            # Process request
            response = await call_next(request)
            
            # Calculate processing time
            process_time_ms = (time.time() - start_time) * 1000
            
            if not is_health_check:
                # Log successful response with performance metrics
                logger.info(
                    "Request completed",
                    status_code=response.status_code,
                    duration_ms=round(process_time_ms, 2),
                    response_size=response.headers.get("content-length")
                )
                
                # Log performance metrics
                performance_logger.log_request_performance(
                    method=request.method,
                    path=str(request.url.path),
                    status_code=response.status_code,
                    duration_ms=round(process_time_ms, 2),
                    content_length=request.headers.get("content-length"),
                    response_size=response.headers.get("content-length")
                )
            
            # Add processing time headers
            if isinstance(response, (Response, JSONResponse)):
                response.headers["X-Process-Time"] = str(round(process_time_ms, 2))
                response.headers["X-Correlation-ID"] = correlation_id
            
            return response
            
        except Exception as e:
            process_time_ms = (time.time() - start_time) * 1000
            
            # Log request failure with detailed error context
            logger.error(
                "Request failed",
                error_type=type(e).__name__,
                error_message=str(e),
                duration_ms=round(process_time_ms, 2),
                exc_info=True
            )
            
            # Log performance metrics for failed requests
            performance_logger.log_request_performance(
                method=request.method,
                path=str(request.url.path),
                status_code=500,  # Assume 500 for unhandled exceptions
                duration_ms=round(process_time_ms, 2),
                error=str(e),
                success=False
            )
            
            raise


# Backward compatibility alias
LoggingMiddleware = EnhancedLoggingMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to responses.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Add security headers to response."""
        
        response = await call_next(request)
        
        # Add security headers
        if isinstance(response, (Response, JSONResponse)):
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            
            # Add API version header
            response.headers["X-API-Version"] = "1.0.0"
        
        return response