"""
Quality service that combines scoring and persistence.
"""
import hashlib
import logging
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.repositories import QualityScoreRepository, DocumentationJobRepository
from app.models.quality import QualityScore, QualityTrend
from app.services.quality_scorer import QualityScorer

logger = logging.getLogger(__name__)


class QualityService:
    """Service for managing quality scoring and persistence."""
    
    def __init__(self, db: Session):
        """Initialize quality service with database session."""
        self.db = db
        self.scorer = QualityScorer()
        self.quality_repo = QualityScoreRepository(db)
        self.job_repo = DocumentationJobRepository(db)
        self.logger = logging.getLogger(__name__)
    
    def evaluate_and_store_quality(
        self,
        job_id: UUID,
        team_id: str,
        service_name: str,
        spec_format: str,
        documentation: str,
        specification: Dict,
        specification_content: str = ""
    ) -> QualityScore:
        """
        Evaluate documentation quality and store the results.
        
        Args:
            job_id: Documentation job identifier
            team_id: Team identifier
            service_name: Service name
            spec_format: Specification format
            documentation: Generated documentation content
            specification: Original specification data
            specification_content: Raw specification content for hashing
            
        Returns:
            QualityScore with calculated metrics
        """
        self.logger.info(f"Evaluating quality for job {job_id}")
        
        # Calculate quality metrics
        metrics = self.scorer.calculate_quality_metrics(
            documentation=documentation,
            specification=specification,
            spec_format=spec_format
        )
        
        # Create specification hash for tracking
        spec_hash = None
        if specification_content:
            spec_hash = hashlib.sha256(specification_content.encode()).hexdigest()
        
        # Create job record if it doesn't exist
        existing_job = self.job_repo.get_job_by_id(job_id)
        if not existing_job:
            self.job_repo.create_job(
                job_id=job_id,
                team_id=team_id,
                service_name=service_name,
                spec_format=spec_format,
                specification_hash=spec_hash
            )
        
        # Create quality score record
        quality_score = QualityScore(
            job_id=job_id,
            team_id=team_id,
            service_name=service_name,
            spec_format=spec_format,
            metrics=metrics,
            specification_hash=spec_hash
        )
        
        # Store in database
        self.quality_repo.create_quality_score(quality_score)
        
        self.logger.info(
            f"Quality evaluation complete for job {job_id}: "
            f"overall={metrics.overall_score}, "
            f"completeness={metrics.completeness}, "
            f"clarity={metrics.clarity}, "
            f"accuracy={metrics.accuracy}"
        )
        
        return quality_score
    
    def get_quality_score_by_job(self, job_id: UUID) -> Optional[QualityScore]:
        """
        Get quality score for a specific job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            QualityScore or None if not found
        """
        db_score = self.quality_repo.get_quality_score_by_job_id(job_id)
        if not db_score:
            return None
        
        # Convert database model back to domain model
        # Note: This is a simplified conversion - in a real implementation,
        # you'd want to properly reconstruct the QualityMetrics and QualityFeedback
        from app.models.quality import QualityMetrics, QualityFeedback, QualityMetricType
        
        feedback = []
        if db_score.feedback_json:
            for fb_data in db_score.feedback_json:
                feedback.append(QualityFeedback(
                    metric_type=QualityMetricType(fb_data['metric_type']),
                    score=fb_data['score'],
                    suggestions=fb_data.get('suggestions', []),
                    details=fb_data.get('details', {})
                ))
        
        metrics = QualityMetrics(
            completeness=db_score.completeness_score,
            clarity=db_score.clarity_score,
            accuracy=db_score.accuracy_score,
            overall_score=db_score.overall_score,
            feedback=feedback
        )
        
        return QualityScore(
            id=db_score.id,
            job_id=db_score.job_id,
            team_id=db_score.job.team_id,
            service_name=db_score.job.service_name,
            spec_format=db_score.job.spec_format,
            metrics=metrics,
            created_at=db_score.created_at,
            specification_hash=db_score.job.specification_hash
        )
    
    def get_service_quality_trend(
        self, 
        team_id: str, 
        service_name: str
    ) -> Optional[QualityTrend]:
        """
        Get quality trend for a specific service.
        
        Args:
            team_id: Team identifier
            service_name: Service name
            
        Returns:
            QualityTrend or None if no data available
        """
        return self.quality_repo.get_quality_trend(team_id, service_name)
    
    def get_team_leaderboard(self, time_period_days: int = 30) -> List[Dict]:
        """
        Get team leaderboard data.
        
        Args:
            time_period_days: Number of days to look back
            
        Returns:
            List of team statistics for leaderboard
        """
        return self.quality_repo.get_team_average_scores(time_period_days)
    
    def get_poor_quality_services(
        self, 
        threshold: int = 60,
        time_period_days: int = 30
    ) -> List[Dict]:
        """
        Get services with poor quality scores.
        
        Args:
            threshold: Score threshold below which services are considered poor quality
            time_period_days: Number of days to look back
            
        Returns:
            List of poor quality services
        """
        return self.quality_repo.get_poor_quality_services(threshold, time_period_days)
    
    def update_job_status(self, job_id: UUID, status: str) -> bool:
        """
        Update documentation job status.
        
        Args:
            job_id: Job identifier
            status: New status
            
        Returns:
            True if updated successfully, False otherwise
        """
        job = self.job_repo.update_job_status(job_id, status)
        return job is not None


# Factory function for dependency injection
def create_quality_service(db: Session) -> QualityService:
    """Create a quality service instance with database session."""
    return QualityService(db)