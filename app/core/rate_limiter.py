"""
Rate limiting functionality for API endpoints.
"""
import time
import logging
from typing import Dict, Optional
from fastapi import HTTPException, Request
import redis
from app.core.config import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Redis-based rate limiter for API endpoints.
    
    Uses sliding window approach to track requests per client.
    """
    
    def __init__(self, redis_url: str = None):
        """Initialize rate limiter with Redis connection."""
        self.redis_url = redis_url or settings.REDIS_URL
        self.redis_client = None
        self._connect_redis()
    
    def _connect_redis(self):
        """Connect to Redis server."""
        try:
            self.redis_client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            # Test connection
            self.redis_client.ping()
            logger.info("Rate limiter connected to Redis")
        except Exception as e:
            logger.warning(f"Redis not available for rate limiting ({e}), using in-memory storage")
            from app.core.dev_redis import get_mock_redis_client
            self.redis_client = get_mock_redis_client()
    
    def _get_client_key(self, request: Request) -> str:
        """
        Generate a unique key for the client.
        
        Uses IP address and User-Agent for identification.
        """
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        
        # Create a simple hash of IP + User-Agent for the key
        import hashlib
        client_info = f"{client_ip}:{user_agent}"
        client_hash = hashlib.md5(client_info.encode()).hexdigest()[:16]
        
        return f"rate_limit:{client_hash}"
    
    async def check_rate_limit(
        self, 
        request: Request, 
        max_requests: int = None,
        window_seconds: int = 60
    ) -> Dict[str, any]:
        """
        Check if request is within rate limits.
        
        Args:
            request: FastAPI request object
            max_requests: Maximum requests allowed (defaults to config)
            window_seconds: Time window in seconds
            
        Returns:
            Dict with rate limit info
            
        Raises:
            HTTPException: If rate limit exceeded
        """
        if not self.redis_client:
            # If Redis is not available, allow all requests but log warning
            logger.warning("Rate limiting disabled - Redis not available")
            return {
                "allowed": True,
                "requests_remaining": max_requests or settings.RATE_LIMIT_REQUESTS,
                "reset_time": int(time.time()) + window_seconds
            }
        
        max_requests = max_requests or settings.RATE_LIMIT_REQUESTS
        client_key = self._get_client_key(request)
        current_time = int(time.time())
        window_start = current_time - window_seconds
        
        try:
            # Use Redis pipeline for atomic operations
            pipe = self.redis_client.pipeline()
            
            # Remove old entries outside the window
            pipe.zremrangebyscore(client_key, 0, window_start)
            
            # Count current requests in window
            pipe.zcard(client_key)
            
            # Add current request
            pipe.zadd(client_key, {str(current_time): current_time})
            
            # Set expiration for cleanup
            pipe.expire(client_key, window_seconds + 10)
            
            # Execute pipeline
            results = pipe.execute()
            current_requests = results[1]  # Count from zcard
            
            # Check if limit exceeded
            if current_requests >= max_requests:
                # Remove the request we just added since it's rejected
                self.redis_client.zrem(client_key, str(current_time))
                
                # Calculate reset time
                oldest_request = self.redis_client.zrange(client_key, 0, 0, withscores=True)
                reset_time = int(oldest_request[0][1]) + window_seconds if oldest_request else current_time + window_seconds
                
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={
                        "X-RateLimit-Limit": str(max_requests),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(reset_time),
                        "Retry-After": str(reset_time - current_time)
                    }
                )
            
            # Calculate remaining requests and reset time
            requests_remaining = max_requests - current_requests - 1  # -1 for current request
            reset_time = current_time + window_seconds
            
            return {
                "allowed": True,
                "requests_remaining": requests_remaining,
                "reset_time": reset_time,
                "headers": {
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Remaining": str(requests_remaining),
                    "X-RateLimit-Reset": str(reset_time)
                }
            }
            
        except redis.RedisError as e:
            logger.error(f"Redis error in rate limiting: {e}")
            # If Redis fails, allow the request but log the error
            return {
                "allowed": True,
                "requests_remaining": max_requests,
                "reset_time": current_time + window_seconds
            }
    
    async def get_rate_limit_status(self, request: Request) -> Dict[str, any]:
        """
        Get current rate limit status for a client without incrementing.
        
        Args:
            request: FastAPI request object
            
        Returns:
            Dict with current rate limit status
        """
        if not self.redis_client:
            return {
                "requests_made": 0,
                "requests_remaining": settings.RATE_LIMIT_REQUESTS,
                "reset_time": int(time.time()) + 60
            }
        
        client_key = self._get_client_key(request)
        current_time = int(time.time())
        window_start = current_time - 60  # 1 minute window
        
        try:
            # Clean old entries and count current
            self.redis_client.zremrangebyscore(client_key, 0, window_start)
            current_requests = self.redis_client.zcard(client_key)
            
            # Calculate reset time
            oldest_request = self.redis_client.zrange(client_key, 0, 0, withscores=True)
            reset_time = int(oldest_request[0][1]) + 60 if oldest_request else current_time + 60
            
            return {
                "requests_made": current_requests,
                "requests_remaining": max(0, settings.RATE_LIMIT_REQUESTS - current_requests),
                "reset_time": reset_time
            }
            
        except redis.RedisError as e:
            logger.error(f"Redis error getting rate limit status: {e}")
            return {
                "requests_made": 0,
                "requests_remaining": settings.RATE_LIMIT_REQUESTS,
                "reset_time": current_time + 60
            }


# Global rate limiter instance
rate_limiter = RateLimiter()