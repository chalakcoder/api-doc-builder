"""
Database configuration and session management.
"""
import logging
from typing import Generator, Optional
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from alembic.config import Config
from alembic import command

from app.core.config import settings
from app.db.models import Base
from app.core.exceptions import DatabaseError, handle_service_errors, ErrorContext

logger = logging.getLogger(__name__)

# Database engine configuration
def create_database_engine():
    """Create database engine with appropriate configuration for the database type."""
    database_url = settings.DATABASE_URL
    
    # Configure engine based on database type
    if database_url.startswith("sqlite"):
        # SQLite configuration
        engine = create_engine(
            database_url,
            echo=settings.DEBUG,
            # SQLite-specific settings
            connect_args={"check_same_thread": False}  # Allow SQLite to be used with FastAPI
        )
    else:
        # PostgreSQL or other database configuration
        engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_recycle=300,
            echo=settings.DEBUG,
            pool_size=10,
            max_overflow=20
        )
    
    return engine

# Create the engine
engine = create_database_engine()

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_tables():
    """Create all database tables."""
    logger.info("Creating database tables")
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    Dependency to get database session.
    
    Yields:
        Database session
        
    Raises:
        DatabaseError: If database connection fails
    """
    db = SessionLocal()
    try:
        # Test the connection
        db.execute(text("SELECT 1"))
        yield db
    except SQLAlchemyError as e:
        logger.error(f"Database session error: {e}")
        raise DatabaseError(
            message=f"Database connection failed: {str(e)}",
            operation="get_session",
            details={"error_type": type(e).__name__}
        )
    finally:
        db.close()


@contextmanager
def get_db_session():
    """
    Context manager for database sessions.
    
    Yields:
        Database session
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_database_connection() -> bool:
    """
    Check if database connection is working.
    
    Returns:
        True if connection is successful, False otherwise
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as e:
        logger.error(f"Database connection failed: {e}")
        return False


def run_migrations():
    """Run database migrations using Alembic."""
    try:
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        logger.info("Database migrations completed successfully")
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise


@handle_service_errors("database initialization")
def init_db():
    """
    Initialize database with migrations.
    
    Raises:
        DatabaseError: If database initialization fails
    """
    with ErrorContext("init_db"):
        logger.info("Initializing database")
        
        try:
            # Check database connection
            if not check_database_connection():
                raise DatabaseError(
                    message="Cannot connect to database during initialization",
                    operation="connection_check",
                    details={"database_url": settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else "unknown"}
                )
            
            # Run migrations
            run_migrations()
            logger.info("Database initialized successfully")
            
        except DatabaseError:
            raise
        except Exception as e:
            raise DatabaseError(
                message=f"Database initialization failed: {str(e)}",
                operation="initialization",
                details={"original_error": str(e)}
            )


def get_database_info() -> dict:
    """
    Get database connection information.
    
    Returns:
        Dictionary with database info
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            
            result = conn.execute(text("SELECT current_database()"))
            database = result.scalar()
            
            return {
                "connected": True,
                "version": version,
                "database": database,
                "url": settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else "unknown"
            }
    except SQLAlchemyError as e:
        return {
            "connected": False,
            "error": str(e)
        }