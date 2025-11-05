"""
Application configuration management using Pydantic settings.
"""
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )
    
    # Application settings
    DEBUG: bool = Field(default=False, description="Enable debug mode")
    HOST: str = Field(default="0.0.0.0", description="Host to bind the server")
    PORT: int = Field(default=8000, description="Port to bind the server")
    
    # CORS settings
    ALLOWED_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        description="Allowed CORS origins"
    )
    
    # Database settings
    DATABASE_URL: str = Field(
        default="postgresql://user:password@localhost/spec_docs",
        description="Database connection URL"
    )
    
    # Redis settings for job queue
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for job queue"
    )
    
    # GenAI endpoint settings
    GENAI_ENDPOINT_URL: str = Field(
        default="http://localhost:8001/generate",
        description="Internal GenAI service endpoint URL"
    )
    GENAI_API_KEY: str = Field(
        default="",
        description="API key for GenAI service authentication"
    )
    GENAI_TIMEOUT: int = Field(
        default=300,
        description="Timeout for GenAI requests in seconds"
    )
    
    # Rate limiting
    RATE_LIMIT_REQUESTS: int = Field(
        default=100,
        description="Number of requests per minute per client"
    )
    
    # Job processing
    MAX_CONCURRENT_JOBS: int = Field(
        default=10,
        description="Maximum number of concurrent documentation generation jobs"
    )
    JOB_TIMEOUT: int = Field(
        default=600,
        description="Job timeout in seconds"
    )
    
    # File storage
    UPLOAD_MAX_SIZE: int = Field(
        default=10 * 1024 * 1024,  # 10MB
        description="Maximum file upload size in bytes"
    )
    STORAGE_PATH: str = Field(
        default="./storage",
        description="Path for storing generated documentation files"
    )
    
    # Logging
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    LOG_FORMAT: str = Field(
        default="json",
        description="Log format (json or text)"
    )


# Global settings instance
settings = Settings()