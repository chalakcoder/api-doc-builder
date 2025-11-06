"""
Database configuration and session management.
"""
import logging
import time
import asyncio
from typing import Generator, Optional, Dict, Any, Callable
from contextlib import contextmanager
from functools import wraps
from datetime import datetime, timedelta

from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError, DisconnectionError, OperationalError
from sqlalchemy.pool import Pool
from alembic.config import Config
from alembic import command

from app.core.config import settings
from app.db.models import Base
from app.core.exceptions import DatabaseError, handle_service_errors, ErrorContext

logger = logging.getLogger(__name__)


class DatabaseConnectionMetrics:
    """Tracks database connection metrics and health status."""
    
    def __init__(self):
        self.connection_attempts = 0
        self.successful_connections = 0
        self.failed_connections = 0
        self.last_connection_time = None
        self.last_error = None
        self.response_times = []
        self.max_response_time_samples = 100
        
    def record_connection_attempt(self):
        """Record a connection attempt."""
        self.connection_attempts += 1
        
    def record_successful_connection(self, response_time: float):
        """Record a successful connection with response time."""
        self.successful_connections += 1
        self.last_connection_time = datetime.now()
        self.response_times.append(response_time)
        
        # Keep only recent response times
        if len(self.response_times) > self.max_response_time_samples:
            self.response_times = self.response_times[-self.max_response_time_samples:]
            
    def record_failed_connection(self, error: Exception):
        """Record a failed connection with error details."""
        self.failed_connections += 1
        self.last_error = str(error)
        
    def get_success_rate(self) -> float:
        """Calculate connection success rate."""
        if self.connection_attempts == 0:
            return 0.0
        return self.successful_connections / self.connection_attempts
        
    def get_average_response_time(self) -> float:
        """Calculate average response time."""
        if not self.response_times:
            return 0.0
        return sum(self.response_times) / len(self.response_times)
        
    def get_metrics(self) -> Dict[str, Any]:
        """Get all metrics as a dictionary."""
        return {
            "connection_attempts": self.connection_attempts,
            "successful_connections": self.successful_connections,
            "failed_connections": self.failed_connections,
            "success_rate": self.get_success_rate(),
            "average_response_time_ms": self.get_average_response_time() * 1000,
            "last_connection_time": self.last_connection_time.isoformat() if self.last_connection_time else None,
            "last_error": self.last_error
        }


class DatabaseRetryConfig:
    """Configuration for database retry logic."""
    
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number."""
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)
        
        if self.jitter:
            import random
            delay *= (0.5 + random.random() * 0.5)  # Add 0-50% jitter
            
        return delay


def database_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: tuple = (DisconnectionError, OperationalError)
):
    """
    Decorator for database operations with exponential backoff retry logic.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        jitter: Whether to add random jitter to delays
        retryable_exceptions: Tuple of exceptions that should trigger retries
    """
    retry_config = DatabaseRetryConfig(max_retries, base_delay, max_delay, exponential_base, jitter)
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    connection_metrics.record_connection_attempt()
                    start_time = time.time()
                    
                    result = func(*args, **kwargs)
                    
                    response_time = time.time() - start_time
                    connection_metrics.record_successful_connection(response_time)
                    
                    if attempt > 0:
                        logger.info(f"Database operation succeeded after {attempt} retries")
                    
                    return result
                    
                except retryable_exceptions as e:
                    last_exception = e
                    connection_metrics.record_failed_connection(e)
                    
                    if attempt < max_retries:
                        delay = retry_config.get_delay(attempt)
                        logger.warning(
                            f"Database operation failed (attempt {attempt + 1}/{max_retries + 1}), "
                            f"retrying in {delay:.2f}s: {str(e)}"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"Database operation failed after {max_retries} retries: {str(e)}")
                        
                except Exception as e:
                    # Non-retryable exceptions
                    connection_metrics.record_failed_connection(e)
                    logger.error(f"Database operation failed with non-retryable error: {str(e)}")
                    raise
            
            # If we get here, all retries failed
            raise DatabaseError(
                message=f"Database operation failed after {max_retries} retries",
                operation="retry_operation",
                details={
                    "last_error": str(last_exception),
                    "attempts": max_retries + 1,
                    "error_type": type(last_exception).__name__ if last_exception else "Unknown"
                }
            )
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    connection_metrics.record_connection_attempt()
                    start_time = time.time()
                    
                    result = await func(*args, **kwargs)
                    
                    response_time = time.time() - start_time
                    connection_metrics.record_successful_connection(response_time)
                    
                    if attempt > 0:
                        logger.info(f"Database operation succeeded after {attempt} retries")
                    
                    return result
                    
                except retryable_exceptions as e:
                    last_exception = e
                    connection_metrics.record_failed_connection(e)
                    
                    if attempt < max_retries:
                        delay = retry_config.get_delay(attempt)
                        logger.warning(
                            f"Database operation failed (attempt {attempt + 1}/{max_retries + 1}), "
                            f"retrying in {delay:.2f}s: {str(e)}"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"Database operation failed after {max_retries} retries: {str(e)}")
                        
                except Exception as e:
                    # Non-retryable exceptions
                    connection_metrics.record_failed_connection(e)
                    logger.error(f"Database operation failed with non-retryable error: {str(e)}")
                    raise
            
            # If we get here, all retries failed
            raise DatabaseError(
                message=f"Database operation failed after {max_retries} retries",
                operation="retry_operation",
                details={
                    "last_error": str(last_exception),
                    "attempts": max_retries + 1,
                    "error_type": type(last_exception).__name__ if last_exception else "Unknown"
                }
            )
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


# Global connection metrics instance
connection_metrics = DatabaseConnectionMetrics()

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
            max_overflow=20,
            # Enhanced connection pool settings for resilience
            pool_timeout=30,
            pool_reset_on_return='commit'
        )
    
    # Add connection pool event listeners for monitoring
    setup_connection_pool_monitoring(engine)
    
    return engine


def setup_connection_pool_monitoring(engine):
    """Set up connection pool event listeners for monitoring and health checks."""
    
    @event.listens_for(engine, "connect")
    def receive_connect(dbapi_connection, connection_record):
        """Handle new database connections."""
        logger.debug("New database connection established")
        
    @event.listens_for(engine, "checkout")
    def receive_checkout(dbapi_connection, connection_record, connection_proxy):
        """Handle connection checkout from pool."""
        logger.debug("Database connection checked out from pool")
        
    @event.listens_for(engine, "checkin")
    def receive_checkin(dbapi_connection, connection_record):
        """Handle connection checkin to pool."""
        logger.debug("Database connection checked in to pool")
        
    @event.listens_for(engine, "invalidate")
    def receive_invalidate(dbapi_connection, connection_record, exception):
        """Handle connection invalidation."""
        logger.warning(f"Database connection invalidated: {exception}")
        connection_metrics.record_failed_connection(exception)


def get_connection_pool_status(engine) -> Dict[str, Any]:
    """
    Get current connection pool status and metrics.
    
    Args:
        engine: SQLAlchemy engine
        
    Returns:
        Dictionary with connection pool metrics
    """
    pool = engine.pool
    
    return {
        "pool_size": pool.size(),
        "checked_in_connections": pool.checkedin(),
        "checked_out_connections": pool.checkedout(),
        "overflow_connections": pool.overflow(),
        "invalid_connections": pool.invalid(),
        "total_connections": pool.size() + pool.overflow(),
        "pool_timeout": getattr(pool, '_timeout', None),
        "max_overflow": getattr(pool, '_max_overflow', None)
    }

# Create the engine
engine = create_database_engine()

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def create_tables():
    """Create all database tables."""
    logger.info("Creating database tables")
    Base.metadata.create_all(bind=engine)


@database_retry(max_retries=3, base_delay=1.0)
def get_db() -> Generator[Session, None, None]:
    """
    Dependency to get database session with retry logic.
    
    Yields:
        Database session
        
    Raises:
        DatabaseError: If database connection fails after retries
    """
    db = SessionLocal()
    try:
        # Test the connection with a simple query
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


@database_retry(max_retries=3, base_delay=1.0)
def get_db_session_with_retry():
    """
    Get database session with retry logic for direct usage.
    
    Returns:
        Database session
        
    Raises:
        DatabaseError: If database connection fails after retries
    """
    db = SessionLocal()
    try:
        # Test the connection
        db.execute(text("SELECT 1"))
        return db
    except SQLAlchemyError as e:
        db.close()
        logger.error(f"Database session creation failed: {e}")
        raise DatabaseError(
            message=f"Database connection failed: {str(e)}",
            operation="get_session_with_retry",
            details={"error_type": type(e).__name__}
        )


@contextmanager
def get_db_session():
    """
    Context manager for database sessions with retry logic.
    
    Yields:
        Database session
    """
    db = None
    try:
        db = get_db_session_with_retry()
        yield db
        db.commit()
    except Exception:
        if db:
            db.rollback()
        raise
    finally:
        if db:
            db.close()


def reconnect_database() -> bool:
    """
    Attempt to reconnect to the database by disposing current connections.
    
    Returns:
        True if reconnection successful, False otherwise
    """
    try:
        logger.info("Attempting database reconnection...")
        
        # Dispose of all connections in the pool
        engine.dispose()
        
        # Test the new connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            
        logger.info("Database reconnection successful")
        return True
        
    except SQLAlchemyError as e:
        logger.error(f"Database reconnection failed: {e}")
        connection_metrics.record_failed_connection(e)
        return False


@database_retry(max_retries=2, base_delay=0.5)
def check_database_connection() -> bool:
    """
    Check if database connection is working with retry logic.
    
    Returns:
        True if connection is successful, False otherwise
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError as e:
        logger.error(f"Database connection check failed: {e}")
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


class DatabaseHealthMonitor:
    """Comprehensive database health monitoring and metrics collection."""
    
    def __init__(self, engine):
        self.engine = engine
        self.query_count = 0
        self.query_times = []
        self.max_query_time_samples = 1000
        self.last_health_check = None
        self.health_check_history = []
        self.max_health_history = 100
        
    def record_query(self, query_time: float):
        """Record a database query execution time."""
        self.query_count += 1
        self.query_times.append(query_time)
        
        # Keep only recent query times
        if len(self.query_times) > self.max_query_time_samples:
            self.query_times = self.query_times[-self.max_query_time_samples:]
    
    @database_retry(max_retries=2, base_delay=0.5)
    def comprehensive_health_check(self) -> Dict[str, Any]:
        """
        Perform comprehensive database health check.
        
        Returns:
            Dictionary with detailed health information
        """
        start_time = time.time()
        health_status = {
            "timestamp": datetime.now().isoformat(),
            "overall_healthy": False,
            "connection_status": {},
            "pool_status": {},
            "performance_metrics": {},
            "connection_metrics": {},
            "database_info": {}
        }
        
        try:
            # Test basic connectivity
            with self.engine.connect() as conn:
                # Basic connectivity test
                conn.execute(text("SELECT 1"))
                connection_test_time = time.time() - start_time
                
                # Get database version and info
                try:
                    version_result = conn.execute(text("SELECT version()"))
                    version = version_result.scalar()
                    
                    db_result = conn.execute(text("SELECT current_database()"))
                    database_name = db_result.scalar()
                    
                    health_status["database_info"] = {
                        "version": version,
                        "database_name": database_name,
                        "connection_test_time_ms": connection_test_time * 1000
                    }
                except Exception as e:
                    logger.warning(f"Could not retrieve database info: {e}")
                    health_status["database_info"] = {"error": str(e)}
                
                # Test transaction capability
                trans = conn.begin()
                try:
                    conn.execute(text("SELECT 1"))
                    trans.commit()
                    transaction_test_passed = True
                except Exception as e:
                    trans.rollback()
                    transaction_test_passed = False
                    logger.warning(f"Transaction test failed: {e}")
                
                health_status["connection_status"] = {
                    "connected": True,
                    "connection_test_time_ms": connection_test_time * 1000,
                    "transaction_test_passed": transaction_test_passed
                }
                
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            health_status["connection_status"] = {
                "connected": False,
                "error": str(e),
                "error_type": type(e).__name__
            }
            connection_metrics.record_failed_connection(e)
        
        # Get connection pool status
        try:
            pool_status = get_connection_pool_status(self.engine)
            health_status["pool_status"] = pool_status
        except Exception as e:
            logger.warning(f"Could not get pool status: {e}")
            health_status["pool_status"] = {"error": str(e)}
        
        # Get performance metrics
        health_status["performance_metrics"] = self.get_performance_metrics()
        
        # Get connection metrics
        health_status["connection_metrics"] = connection_metrics.get_metrics()
        
        # Determine overall health
        health_status["overall_healthy"] = (
            health_status["connection_status"].get("connected", False) and
            health_status["connection_status"].get("transaction_test_passed", False) and
            connection_metrics.get_success_rate() > 0.8  # 80% success rate threshold
        )
        
        # Record this health check
        self.last_health_check = health_status
        self.health_check_history.append({
            "timestamp": health_status["timestamp"],
            "healthy": health_status["overall_healthy"],
            "connection_time_ms": health_status["connection_status"].get("connection_test_time_ms", 0)
        })
        
        # Keep only recent history
        if len(self.health_check_history) > self.max_health_history:
            self.health_check_history = self.health_check_history[-self.max_health_history:]
        
        return health_status
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get database performance metrics."""
        if not self.query_times:
            return {
                "total_queries": self.query_count,
                "average_query_time_ms": 0,
                "min_query_time_ms": 0,
                "max_query_time_ms": 0,
                "recent_queries_count": 0
            }
        
        return {
            "total_queries": self.query_count,
            "average_query_time_ms": (sum(self.query_times) / len(self.query_times)) * 1000,
            "min_query_time_ms": min(self.query_times) * 1000,
            "max_query_time_ms": max(self.query_times) * 1000,
            "recent_queries_count": len(self.query_times)
        }
    
    def get_health_trends(self, hours: int = 24) -> Dict[str, Any]:
        """
        Analyze health trends over the specified time period.
        
        Args:
            hours: Number of hours to analyze
            
        Returns:
            Dictionary with health trend analysis
        """
        cutoff_time = datetime.now() - timedelta(hours=hours)
        
        recent_checks = [
            check for check in self.health_check_history
            if datetime.fromisoformat(check["timestamp"]) > cutoff_time
        ]
        
        if not recent_checks:
            return {
                "period_hours": hours,
                "total_checks": 0,
                "healthy_checks": 0,
                "health_percentage": 0,
                "average_connection_time_ms": 0,
                "trend": "no_data"
            }
        
        healthy_count = sum(1 for check in recent_checks if check["healthy"])
        health_percentage = (healthy_count / len(recent_checks)) * 100
        
        avg_connection_time = sum(
            check["connection_time_ms"] for check in recent_checks
        ) / len(recent_checks)
        
        # Determine trend (simple analysis based on recent vs older checks)
        if len(recent_checks) >= 10:
            recent_half = recent_checks[-5:]
            older_half = recent_checks[:5]
            
            recent_health = sum(1 for check in recent_half if check["healthy"]) / len(recent_half)
            older_health = sum(1 for check in older_half if check["healthy"]) / len(older_half)
            
            if recent_health > older_health + 0.1:
                trend = "improving"
            elif recent_health < older_health - 0.1:
                trend = "degrading"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"
        
        return {
            "period_hours": hours,
            "total_checks": len(recent_checks),
            "healthy_checks": healthy_count,
            "health_percentage": health_percentage,
            "average_connection_time_ms": avg_connection_time,
            "trend": trend
        }


# Global health monitor instance
health_monitor = DatabaseHealthMonitor(engine)


def monitor_query_performance(func: Callable) -> Callable:
    """
    Decorator to monitor database query performance.
    
    Args:
        func: Function to monitor
        
    Returns:
        Wrapped function with performance monitoring
    """
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            query_time = time.time() - start_time
            health_monitor.record_query(query_time)
            return result
        except Exception as e:
            query_time = time.time() - start_time
            health_monitor.record_query(query_time)
            raise
    
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            query_time = time.time() - start_time
            health_monitor.record_query(query_time)
            return result
        except Exception as e:
            query_time = time.time() - start_time
            health_monitor.record_query(query_time)
            raise
    
    # Return appropriate wrapper based on function type
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper


def get_comprehensive_database_status() -> Dict[str, Any]:
    """
    Get comprehensive database status including health, metrics, and trends.
    
    Returns:
        Dictionary with complete database status information
    """
    try:
        health_status = health_monitor.comprehensive_health_check()
        
        # Add trend analysis
        health_status["trends"] = {
            "last_24_hours": health_monitor.get_health_trends(24),
            "last_hour": health_monitor.get_health_trends(1)
        }
        
        return health_status
        
    except Exception as e:
        logger.error(f"Failed to get comprehensive database status: {e}")
        return {
            "timestamp": datetime.now().isoformat(),
            "overall_healthy": False,
            "error": str(e),
            "error_type": type(e).__name__
        }