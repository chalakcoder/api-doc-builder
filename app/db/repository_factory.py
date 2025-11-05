"""
Repository factory for managing database repository instances.
"""
from typing import Optional
from sqlalchemy.orm import Session

from app.db.repositories import QualityScoreRepository, DocumentationJobRepository


class RepositoryFactory:
    """Factory class for creating repository instances."""
    
    def __init__(self, db: Session):
        """
        Initialize factory with database session.
        
        Args:
            db: Database session
        """
        self.db = db
        self._quality_score_repo: Optional[QualityScoreRepository] = None
        self._job_repo: Optional[DocumentationJobRepository] = None
    
    @property
    def quality_score_repo(self) -> QualityScoreRepository:
        """Get or create quality score repository."""
        if self._quality_score_repo is None:
            self._quality_score_repo = QualityScoreRepository(self.db)
        return self._quality_score_repo
    
    @property
    def job_repo(self) -> DocumentationJobRepository:
        """Get or create documentation job repository."""
        if self._job_repo is None:
            self._job_repo = DocumentationJobRepository(self.db)
        return self._job_repo
    
    def get_quality_score_repository(self) -> QualityScoreRepository:
        """Get quality score repository instance."""
        return self.quality_score_repo
    
    def get_job_repository(self) -> DocumentationJobRepository:
        """Get documentation job repository instance."""
        return self.job_repo


def create_repository_factory(db: Session) -> RepositoryFactory:
    """
    Create a repository factory instance.
    
    Args:
        db: Database session
        
    Returns:
        RepositoryFactory instance
    """
    return RepositoryFactory(db)