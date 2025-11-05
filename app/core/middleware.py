"""
Custom middleware for the Spec Documentation API.
"""
import time
import logging
from typing import Callable
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)


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


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for request/response logging.
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Log request and response information."""
        
        start_time = time.time()
        
        # Log request
        logger.info(
            f"Request: {request.method} {request.url.path} "
            f"from {request.client.host if request.client else 'unknown'}"
        )
        
        try:
            # Process request
            response = await call_next(request)
            
            # Calculate processing time
            process_time = time.time() - start_time
            
            # Log response
            logger.info(
                f"Response: {response.status_code} "
                f"for {request.method} {request.url.path} "
                f"in {process_time:.3f}s"
            )
            
            # Add processing time header
            if isinstance(response, (Response, JSONResponse)):
                response.headers["X-Process-Time"] = str(process_time)
            
            return response
            
        except Exception as e:
            process_time = time.time() - start_time
            logger.error(
                f"Request failed: {request.method} {request.url.path} "
                f"after {process_time:.3f}s - {str(e)}"
            )
            raise


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