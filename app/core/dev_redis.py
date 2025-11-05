"""
Development Redis replacement using in-memory storage.
This is a simple mock Redis client for development when Redis is not available.
"""
import json
import time
from typing import Dict, Any, Optional, Union
from datetime import datetime, timedelta


class MockRedisClient:
    """
    Mock Redis client for development.
    
    This provides basic Redis-like functionality using in-memory storage.
    Only implements the methods used by the application.
    """
    
    def __init__(self):
        self._data: Dict[str, Any] = {}
        self._expiry: Dict[str, float] = {}
    
    def _is_expired(self, key: str) -> bool:
        """Check if a key has expired."""
        if key in self._expiry:
            return time.time() > self._expiry[key]
        return False
    
    def _cleanup_expired(self, key: str) -> None:
        """Remove expired key."""
        if self._is_expired(key):
            self._data.pop(key, None)
            self._expiry.pop(key, None)
    
    def ping(self) -> bool:
        """Ping the Redis server."""
        return True
    
    def set(self, key: str, value: Union[str, bytes], ex: Optional[int] = None) -> bool:
        """Set a key-value pair with optional expiration."""
        self._data[key] = value
        if ex:
            self._expiry[key] = time.time() + ex
        return True
    
    def get(self, key: str) -> Optional[Union[str, bytes]]:
        """Get a value by key."""
        self._cleanup_expired(key)
        return self._data.get(key)
    
    def delete(self, *keys: str) -> int:
        """Delete one or more keys."""
        deleted = 0
        for key in keys:
            if key in self._data:
                self._data.pop(key, None)
                self._expiry.pop(key, None)
                deleted += 1
        return deleted
    
    def exists(self, key: str) -> bool:
        """Check if a key exists."""
        self._cleanup_expired(key)
        return key in self._data
    
    def expire(self, key: str, seconds: int) -> bool:
        """Set expiration for a key."""
        if key in self._data:
            self._expiry[key] = time.time() + seconds
            return True
        return False
    
    def hset(self, key: str, mapping: Dict[str, Any]) -> int:
        """Set hash fields."""
        if key not in self._data:
            self._data[key] = {}
        
        if not isinstance(self._data[key], dict):
            self._data[key] = {}
        
        count = 0
        for field, value in mapping.items():
            if field not in self._data[key]:
                count += 1
            self._data[key][field] = value
        
        return count
    
    def hget(self, key: str, field: str) -> Optional[Any]:
        """Get a hash field value."""
        self._cleanup_expired(key)
        if key in self._data and isinstance(self._data[key], dict):
            return self._data[key].get(field)
        return None
    
    def hgetall(self, key: str) -> Dict[str, Any]:
        """Get all hash fields and values."""
        self._cleanup_expired(key)
        if key in self._data and isinstance(self._data[key], dict):
            return self._data[key].copy()
        return {}
    
    def keys(self, pattern: str = "*") -> list:
        """Get all keys matching a pattern."""
        # Simple pattern matching - only supports * wildcard
        if pattern == "*":
            return [k for k in self._data.keys() if not self._is_expired(k)]
        
        # Basic pattern matching
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return [k for k in self._data.keys() 
                   if k.startswith(prefix) and not self._is_expired(k)]
        
        return [k for k in self._data.keys() 
               if k == pattern and not self._is_expired(k)]
    
    def flushdb(self) -> bool:
        """Clear all data."""
        self._data.clear()
        self._expiry.clear()
        return True


def create_redis_client(url: str = None) -> Union[MockRedisClient, Any]:
    """
    Create a Redis client, falling back to mock client if Redis is not available.
    
    Args:
        url: Redis connection URL
        
    Returns:
        Redis client or mock client
    """
    try:
        import redis
        
        if url:
            client = redis.from_url(url)
        else:
            client = redis.Redis(host='localhost', port=6379, db=0)
        
        # Test the connection
        client.ping()
        print("✅ Connected to Redis server")
        return client
        
    except Exception as e:
        print(f"⚠️  Redis not available ({e}), using in-memory mock client for development")
        return MockRedisClient()


# Global mock client for development
_mock_client = None

def get_mock_redis_client() -> MockRedisClient:
    """Get the global mock Redis client."""
    global _mock_client
    if _mock_client is None:
        _mock_client = MockRedisClient()
    return _mock_client