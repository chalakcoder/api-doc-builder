"""
GenAI client wrapper for internal GenAI endpoint communication.
Provides async client with retry logic and error handling.
"""
import asyncio
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

import aiohttp
from aiohttp import ClientTimeout, ClientError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

from app.core.config import settings
from app.core.exceptions import GenAIServiceError, RateLimitError, handle_service_errors, ErrorContext

logger = logging.getLogger(__name__)


class GenAIError(GenAIServiceError):
    """Base exception for GenAI client errors."""
    pass


class GenAITimeoutError(GenAIError):
    """Raised when GenAI request times out."""
    pass


class GenAIServiceUnavailableError(GenAIError):
    """Raised when GenAI service is unavailable."""
    pass


class GenAIRateLimitError(RateLimitError):
    """Raised when GenAI service rate limit is exceeded."""
    pass


@dataclass
class GenAIRequest:
    """Request model for GenAI endpoint."""
    prompt: str
    max_tokens: int = 2000
    temperature: float = 0.3
    model: str = "default"
    context: Optional[Dict[str, Any]] = None


@dataclass
class GenAIResponse:
    """Response model from GenAI endpoint."""
    content: str
    tokens_used: int
    model: str
    request_id: str
    metadata: Optional[Dict[str, Any]] = None


class GenAIClient:
    """
    Async client for internal GenAI endpoint communication.
    
    Provides retry logic, error handling, and proper resource management
    for GenAI service calls.
    """
    
    def __init__(
        self,
        endpoint_url: str = None,
        api_key: str = None,
        timeout: int = None,
        max_retries: int = 3,
        session: Optional[aiohttp.ClientSession] = None
    ):
        """
        Initialize GenAI client.
        
        Args:
            endpoint_url: GenAI service endpoint URL
            api_key: API key for authentication
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            session: Optional existing aiohttp session
        """
        self.endpoint_url = endpoint_url or settings.GENAI_ENDPOINT_URL
        self.api_key = api_key or settings.GENAI_API_KEY
        self.timeout = timeout or settings.GENAI_TIMEOUT
        self.max_retries = max_retries
        self._session = session
        self._owned_session = session is None
        
    async def __aenter__(self):
        """Async context manager entry."""
        if self._session is None:
            timeout = ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._owned_session and self._session:
            await self._session.close()
            
    @property
    def session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None:
            timeout = ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
        
    def _prepare_headers(self) -> Dict[str, str]:
        """Prepare request headers."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "SpecDocumentationAPI/1.0"
        }
        
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            
        return headers
        
    def _prepare_payload(self, request: GenAIRequest) -> Dict[str, Any]:
        """Prepare request payload."""
        payload = {
            "prompt": request.prompt,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "model": request.model
        }
        
        if request.context:
            payload["context"] = request.context
            
        return payload
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((
            aiohttp.ClientError,
            GenAIServiceUnavailableError,
            GenAITimeoutError
        )),
        before_sleep=before_sleep_log(logger, logging.WARNING)
    )
    async def _make_request(self, request: GenAIRequest) -> GenAIResponse:
        """
        Make HTTP request to GenAI endpoint with retry logic.
        
        Args:
            request: GenAI request object
            
        Returns:
            GenAI response object
            
        Raises:
            GenAIError: Various GenAI-specific errors
        """
        headers = self._prepare_headers()
        payload = self._prepare_payload(request)
        
        try:
            async with self.session.post(
                self.endpoint_url,
                json=payload,
                headers=headers
            ) as response:
                
                # Handle different HTTP status codes
                if response.status == 200:
                    data = await response.json()
                    return self._parse_response(data)
                    
                elif response.status == 429:
                    error_data = await response.json()
                    raise GenAIRateLimitError(
                        f"Rate limit exceeded: {error_data.get('message', 'Unknown error')}"
                    )
                    
                elif response.status in (502, 503, 504):
                    error_data = await response.json()
                    raise GenAIServiceUnavailableError(
                        f"GenAI service unavailable (HTTP {response.status}): "
                        f"{error_data.get('message', 'Service temporarily unavailable')}"
                    )
                    
                else:
                    error_data = await response.json()
                    raise GenAIError(
                        f"GenAI request failed (HTTP {response.status}): "
                        f"{error_data.get('message', 'Unknown error')}"
                    )
                    
        except asyncio.TimeoutError:
            raise GenAITimeoutError(
                f"GenAI request timed out after {self.timeout} seconds"
            )
            
        except ClientError as e:
            raise GenAIServiceUnavailableError(
                f"Failed to connect to GenAI service: {str(e)}"
            )
            
    def _parse_response(self, data: Dict[str, Any]) -> GenAIResponse:
        """
        Parse GenAI response data.
        
        Args:
            data: Raw response data from GenAI endpoint
            
        Returns:
            Parsed GenAI response object
            
        Raises:
            GenAIError: If response format is invalid
        """
        try:
            return GenAIResponse(
                content=data["content"],
                tokens_used=data.get("tokens_used", 0),
                model=data.get("model", "unknown"),
                request_id=data.get("request_id", ""),
                metadata=data.get("metadata")
            )
        except KeyError as e:
            raise GenAIError(f"Invalid GenAI response format: missing field {e}")
            
    @handle_service_errors("GenAI content generation")
    async def generate(
        self,
        prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.3,
        model: str = "default",
        context: Optional[Dict[str, Any]] = None
    ) -> GenAIResponse:
        """
        Generate content using GenAI endpoint.
        
        Args:
            prompt: Text prompt for generation
            max_tokens: Maximum tokens to generate
            temperature: Generation temperature (0.0-1.0)
            model: Model to use for generation
            context: Additional context for generation
            
        Returns:
            GenAI response with generated content
            
        Raises:
            GenAIError: Various GenAI-specific errors
        """
        with ErrorContext("generate_content", 
                         prompt_length=len(prompt), 
                         max_tokens=max_tokens, 
                         model=model):
            
            request = GenAIRequest(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                model=model,
                context=context
            )
            
            logger.info(
                f"Generating content with GenAI",
                extra={
                    "prompt_length": len(prompt),
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "model": model
                }
            )
            
            try:
                response = await self._make_request(request)
                
                logger.info(
                    f"GenAI generation completed",
                    extra={
                        "tokens_used": response.tokens_used,
                        "content_length": len(response.content),
                        "request_id": response.request_id
                    }
                )
                
                return response
                
            except (GenAIError, RateLimitError):
                # Re-raise our custom exceptions
                raise
            except Exception as e:
                logger.error(
                    f"GenAI generation failed: {str(e)}",
                    extra={
                        "prompt_length": len(prompt),
                        "error_type": type(e).__name__
                    }
                )
                raise GenAIServiceError(
                    message=f"GenAI generation failed: {str(e)}",
                    details={
                        "prompt_length": len(prompt),
                        "max_tokens": max_tokens,
                        "model": model,
                        "original_error": str(e)
                    }
                )
            
    async def generate_batch(
        self,
        requests: List[GenAIRequest],
        max_concurrent: int = 5
    ) -> List[GenAIResponse]:
        """
        Generate content for multiple requests concurrently.
        
        Args:
            requests: List of GenAI requests
            max_concurrent: Maximum concurrent requests
            
        Returns:
            List of GenAI responses in same order as requests
            
        Raises:
            GenAIError: If any request fails
        """
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def _generate_with_semaphore(request: GenAIRequest) -> GenAIResponse:
            async with semaphore:
                return await self._make_request(request)
                
        logger.info(
            f"Starting batch generation",
            extra={
                "batch_size": len(requests),
                "max_concurrent": max_concurrent
            }
        )
        
        try:
            tasks = [_generate_with_semaphore(req) for req in requests]
            responses = await asyncio.gather(*tasks)
            
            logger.info(
                f"Batch generation completed",
                extra={
                    "batch_size": len(requests),
                    "total_tokens": sum(r.tokens_used for r in responses)
                }
            )
            
            return responses
            
        except Exception as e:
            logger.error(
                f"Batch generation failed: {str(e)}",
                extra={
                    "batch_size": len(requests),
                    "error_type": type(e).__name__
                }
            )
            raise
            
    async def health_check(self) -> bool:
        """
        Check if GenAI service is healthy.
        
        Returns:
            True if service is healthy, False otherwise
        """
        try:
            # Simple health check with minimal prompt
            response = await self.generate(
                prompt="Health check",
                max_tokens=10,
                temperature=0.0
            )
            return len(response.content) > 0
            
        except Exception as e:
            logger.warning(f"GenAI health check failed: {str(e)}")
            return False


# Global client instance (will be initialized in main app)
genai_client: Optional[GenAIClient] = None


def get_genai_client() -> GenAIClient:
    """
    Get global GenAI client instance.
    
    Returns:
        GenAI client instance
        
    Raises:
        RuntimeError: If client is not initialized
    """
    if genai_client is None:
        raise RuntimeError("GenAI client not initialized")
    return genai_client


def init_genai_client() -> GenAIClient:
    """
    Initialize global GenAI client instance.
    
    Returns:
        Initialized GenAI client
    """
    global genai_client
    genai_client = GenAIClient()
    return genai_client


def initialize_genai_client() -> None:
    """
    Initialize GenAI client for application startup.
    
    This function is called during application startup to ensure
    the GenAI client is properly configured and ready for use.
    """
    logger.info("Initializing GenAI client...")
    
    try:
        # Initialize the global client
        client = init_genai_client()
        
        # Validate configuration
        if not client.endpoint_url:
            raise ValueError("GenAI endpoint URL not configured")
        
        logger.info(
            f"GenAI client initialized successfully",
            extra={
                "endpoint_url": client.endpoint_url,
                "timeout": client.timeout,
                "max_retries": client.max_retries
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to initialize GenAI client: {e}")
        raise