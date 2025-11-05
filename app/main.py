"""
Main FastAPI application entry point for Spec Documentation API.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.exceptions import setup_exception_handlers
from app.api.endpoints import router as api_router
from app.core.middleware import RateLimitMiddleware, LoggingMiddleware, SecurityHeadersMiddleware
from app.db.database import init_db, check_database_connection
from app.jobs.celery_app import celery_app
from app.services.genai_client import initialize_genai_client
from app.services.documentation_generator import initialize_documentation_generator
from app.parsers.parser_factory import initialize_parser_factory
from app.validators.format_detector import initialize_format_detector


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager with comprehensive service initialization."""
    # Startup
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting Spec Documentation API")
    
    try:
        # Initialize database
        logger.info("Initializing database connection...")
        if not check_database_connection():
            logger.error("Database connection failed during startup")
            raise RuntimeError("Database connection failed")
        
        init_db()
        logger.info("Database initialized successfully")
        
        # Initialize GenAI client
        logger.info("Initializing GenAI client...")
        initialize_genai_client()
        logger.info("GenAI client initialized successfully")
        
        # Initialize documentation generator
        logger.info("Initializing documentation generator...")
        initialize_documentation_generator()
        logger.info("Documentation generator initialized successfully")
        
        # Initialize parser factory
        logger.info("Initializing parser factory...")
        initialize_parser_factory()
        logger.info("Parser factory initialized successfully")
        
        # Initialize format detector
        logger.info("Initializing format detector...")
        initialize_format_detector()
        logger.info("Format detector initialized successfully")
        
        # Start Celery worker monitoring (optional)
        logger.info("Celery app configured for job processing")
        
        # Verify all components are healthy
        logger.info("Performing startup health checks...")
        from app.jobs.job_service import job_service
        health_status = await job_service.health_check()
        
        if not health_status.get("healthy", False):
            logger.warning("Some components are not healthy, but continuing startup")
            logger.warning(f"Health status: {health_status}")
        else:
            logger.info("All components are healthy")
        
        logger.info("Spec Documentation API startup completed successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize application: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down Spec Documentation API")
    
    try:
        # Cleanup resources
        logger.info("Cleaning up resources...")
        
        # Stop any background tasks
        from app.jobs.job_manager import job_manager
        await job_manager.cleanup_expired_jobs(max_age_hours=1)
        
        logger.info("Shutdown completed successfully")
        
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Spec Documentation API",
        description="Automatically generate high-quality documentation from API specifications using GenAI",
        version="1.0.0",
        lifespan=lifespan,
    )
    
    # Add middleware (order matters - last added is executed first)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(LoggingMiddleware)
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include API routes
    app.include_router(api_router)
    
    # Set up global exception handlers
    setup_exception_handlers(app)
    
    return app


app = create_app()


# Health check endpoint is now handled by the API router


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info"
    )