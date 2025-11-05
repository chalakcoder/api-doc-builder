"""
Database components package for the Spec Documentation API.
"""

from .database import (
    engine,
    SessionLocal,
    get_db,
    get_db_session,
    create_tables,
    init_db,
    check_database_connection,
    run_migrations,
    get_database_info
)

from .models import (
    Base,
    DocumentationJob,
    QualityScoreDB
)

from .repositories import (
    BaseRepository,
    QualityScoreRepository,
    DocumentationJobRepository
)

from .repository_factory import (
    RepositoryFactory,
    create_repository_factory
)

__all__ = [
    # Database
    "engine",
    "SessionLocal", 
    "get_db",
    "get_db_session",
    "create_tables",
    "init_db",
    "check_database_connection",
    "run_migrations",
    "get_database_info",
    
    # Models
    "Base",
    "DocumentationJob",
    "QualityScoreDB",
    
    # Repositories
    "BaseRepository",
    "QualityScoreRepository",
    "DocumentationJobRepository",
    
    # Repository Factory
    "RepositoryFactory",
    "create_repository_factory"
]