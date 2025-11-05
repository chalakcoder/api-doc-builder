"""
Repository classes for database operations.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Generic, TypeVar
from uuid import UUID
from abc import ABC, abstractmethod

from sqlalchemy import desc, func, and_, or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import DocumentationJob, QualityScoreDB
from app.models.quality import QualityScore, QualityMetrics, QualityTrend

logger = logging.getLogger(__name__)

T = TypeVar('T')


class BaseRepository(ABC, Generic[T]):
    """Base repository class with common database operations."""
    
    def __init__(self, db: Session):
        """Initialize repository with database session."""
        self.db = db
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def _handle_db_error(self, operation: str, error: Exception):
        """Handle database errors with logging."""
        self.logger.error(f"Database error during {operation}: {error}")
        raise
    
    def _commit_or_rollback(self):
        """Commit transaction or rollback on error."""
        try:
            self.db.commit()
        except SQLAlchemyError as e:
            self.db.rollback()
            raise e


class QualityScoreRepository(BaseRepository[QualityScoreDB]):
    """Repository for quality score database operations."""
    
    def create_quality_score(self, quality_score: QualityScore) -> QualityScoreDB:
        """
        Create a new quality score record.
        
        Args:
            quality_score: QualityScore model to persist
            
        Returns:
            Created QualityScoreDB instance
        """
        self.logger.info(f"Creating quality score for job {quality_score.job_id}")
        
        # Convert feedback to JSON
        feedback_json = [feedback.dict() for feedback in quality_score.metrics.feedback]
        
        db_score = QualityScoreDB(
            id=quality_score.id,
            job_id=quality_score.job_id,
            overall_score=quality_score.metrics.overall_score,
            completeness_score=quality_score.metrics.completeness,
            clarity_score=quality_score.metrics.clarity,
            accuracy_score=quality_score.metrics.accuracy,
            feedback_json=feedback_json,
            created_at=quality_score.created_at
        )
        
        try:
            self.db.add(db_score)
            self._commit_or_rollback()
            self.db.refresh(db_score)
            return db_score
        except SQLAlchemyError as e:
            self._handle_db_error("create_quality_score", e)
    
    def get_quality_score_by_job_id(self, job_id: UUID) -> Optional[QualityScoreDB]:
        """
        Get quality score by job ID.
        
        Args:
            job_id: Job identifier
            
        Returns:
            QualityScoreDB instance or None
        """
        return self.db.query(QualityScoreDB).filter(
            QualityScoreDB.job_id == job_id
        ).first()
    
    def get_quality_scores_by_service(
        self, 
        team_id: str, 
        service_name: str,
        limit: int = 10
    ) -> List[QualityScoreDB]:
        """
        Get quality scores for a specific service.
        
        Args:
            team_id: Team identifier
            service_name: Service name
            limit: Maximum number of records to return
            
        Returns:
            List of QualityScoreDB instances
        """
        return (
            self.db.query(QualityScoreDB)
            .join(DocumentationJob)
            .filter(
                and_(
                    DocumentationJob.team_id == team_id,
                    DocumentationJob.service_name == service_name
                )
            )
            .order_by(desc(QualityScoreDB.created_at))
            .limit(limit)
            .all()
        )
    
    def get_team_average_scores(
        self, 
        time_period_days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Get average quality scores by team for leaderboard.
        
        Args:
            time_period_days: Number of days to look back
            
        Returns:
            List of team statistics
        """
        cutoff_date = datetime.utcnow() - timedelta(days=time_period_days)
        
        results = (
            self.db.query(
                DocumentationJob.team_id,
                func.avg(QualityScoreDB.overall_score).label('avg_score'),
                func.count(QualityScoreDB.id).label('total_docs'),
                func.max(QualityScoreDB.created_at).label('last_updated')
            )
            .join(QualityScoreDB)
            .filter(QualityScoreDB.created_at >= cutoff_date)
            .group_by(DocumentationJob.team_id)
            .order_by(desc('avg_score'))
            .all()
        )
        
        return [
            {
                'team_id': result.team_id,
                'average_score': round(result.avg_score, 1),
                'total_docs': result.total_docs,
                'last_updated': result.last_updated
            }
            for result in results
        ]
    
    def get_poor_quality_services(
        self, 
        threshold: int = 60,
        time_period_days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Get services with poor quality scores.
        
        Args:
            threshold: Score threshold below which services are considered poor quality
            time_period_days: Number of days to look back
            
        Returns:
            List of poor quality services
        """
        cutoff_date = datetime.utcnow() - timedelta(days=time_period_days)
        
        # Get latest score for each service
        subquery = (
            self.db.query(
                DocumentationJob.team_id,
                DocumentationJob.service_name,
                func.max(QualityScoreDB.created_at).label('max_date')
            )
            .join(QualityScoreDB)
            .filter(QualityScoreDB.created_at >= cutoff_date)
            .group_by(DocumentationJob.team_id, DocumentationJob.service_name)
            .subquery()
        )
        
        results = (
            self.db.query(
                DocumentationJob.team_id,
                DocumentationJob.service_name,
                QualityScoreDB.overall_score,
                QualityScoreDB.created_at
            )
            .join(QualityScoreDB)
            .join(
                subquery,
                and_(
                    DocumentationJob.team_id == subquery.c.team_id,
                    DocumentationJob.service_name == subquery.c.service_name,
                    QualityScoreDB.created_at == subquery.c.max_date
                )
            )
            .filter(QualityScoreDB.overall_score < threshold)
            .order_by(QualityScoreDB.overall_score)
            .all()
        )
        
        return [
            {
                'team_id': result.team_id,
                'service_name': result.service_name,
                'score': result.overall_score,
                'last_updated': result.created_at
            }
            for result in results
        ]
    
    def get_quality_trend(
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
            QualityTrend instance or None
        """
        scores = self.get_quality_scores_by_service(team_id, service_name, limit=5)
        
        if not scores:
            return None
        
        current_score = scores[0].overall_score
        previous_score = scores[1].overall_score if len(scores) > 1 else None
        
        # Build score history
        score_history = [
            {
                'score': score.overall_score,
                'date': score.created_at.isoformat(),
                'completeness': score.completeness_score,
                'clarity': score.clarity_score,
                'accuracy': score.accuracy_score
            }
            for score in reversed(scores)  # Oldest first
        ]
        
        return QualityTrend(
            service_name=service_name,
            team_id=team_id,
            current_score=current_score,
            previous_score=previous_score,
            score_history=score_history
        )
    
    def get_leaderboard_data(
        self, 
        time_period_days: int = 30,
        team_filter: Optional[str] = None,
        service_type_filter: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get comprehensive leaderboard data.
        
        Args:
            time_period_days: Number of days to look back
            team_filter: Optional team filter
            service_type_filter: Optional service type filter
            
        Returns:
            Dictionary with leaderboard data
        """
        cutoff_date = datetime.utcnow() - timedelta(days=time_period_days)
        
        # Base query
        base_query = (
            self.db.query(DocumentationJob, QualityScoreDB)
            .join(QualityScoreDB)
            .filter(QualityScoreDB.created_at >= cutoff_date)
        )
        
        # Apply filters
        if team_filter:
            base_query = base_query.filter(DocumentationJob.team_id == team_filter)
        
        if service_type_filter:
            base_query = base_query.filter(DocumentationJob.spec_format == service_type_filter)
        
        # Get team rankings
        team_stats = (
            base_query
            .with_entities(
                DocumentationJob.team_id,
                func.avg(QualityScoreDB.overall_score).label('avg_score'),
                func.count(QualityScoreDB.id).label('total_docs'),
                func.max(QualityScoreDB.created_at).label('last_updated'),
                func.avg(QualityScoreDB.completeness_score).label('avg_completeness'),
                func.avg(QualityScoreDB.clarity_score).label('avg_clarity'),
                func.avg(QualityScoreDB.accuracy_score).label('avg_accuracy')
            )
            .group_by(DocumentationJob.team_id)
            .order_by(desc('avg_score'))
            .all()
        )
        
        rankings = []
        for i, stat in enumerate(team_stats, 1):
            # Calculate trend (compare with previous period)
            prev_cutoff = cutoff_date - timedelta(days=time_period_days)
            prev_avg = (
                self.db.query(func.avg(QualityScoreDB.overall_score))
                .join(DocumentationJob)
                .filter(
                    and_(
                        DocumentationJob.team_id == stat.team_id,
                        QualityScoreDB.created_at >= prev_cutoff,
                        QualityScoreDB.created_at < cutoff_date
                    )
                )
                .scalar()
            )
            
            trend = "stable"
            if prev_avg:
                diff = stat.avg_score - prev_avg
                if diff > 5:
                    trend = "improving"
                elif diff < -5:
                    trend = "declining"
            
            rankings.append({
                "rank": i,
                "team_id": stat.team_id,
                "average_score": round(stat.avg_score, 1),
                "total_docs": stat.total_docs,
                "last_updated": stat.last_updated,
                "trend": trend,
                "metrics": {
                    "completeness": round(stat.avg_completeness, 1),
                    "clarity": round(stat.avg_clarity, 1),
                    "accuracy": round(stat.avg_accuracy, 1)
                }
            })
        
        # Get poor quality services
        poor_services = self.get_poor_quality_services(
            threshold=60, 
            time_period_days=time_period_days
        )
        
        return {
            "rankings": rankings,
            "poor_quality_services": poor_services,
            "period_days": time_period_days,
            "generated_at": datetime.utcnow().isoformat()
        }
    
    def get_quality_distribution(self, time_period_days: int = 30) -> Dict[str, int]:
        """
        Get distribution of quality scores.
        
        Args:
            time_period_days: Number of days to look back
            
        Returns:
            Dictionary with score distribution
        """
        cutoff_date = datetime.utcnow() - timedelta(days=time_period_days)
        
        scores = (
            self.db.query(QualityScoreDB.overall_score)
            .filter(QualityScoreDB.created_at >= cutoff_date)
            .all()
        )
        
        distribution = {
            "excellent": 0,  # 90-100
            "good": 0,       # 70-89
            "fair": 0,       # 50-69
            "poor": 0        # 0-49
        }
        
        for score_tuple in scores:
            score = score_tuple[0]
            if score >= 90:
                distribution["excellent"] += 1
            elif score >= 70:
                distribution["good"] += 1
            elif score >= 50:
                distribution["fair"] += 1
            else:
                distribution["poor"] += 1
        
        return distribution


class DocumentationJobRepository(BaseRepository[DocumentationJob]):
    """Repository for documentation job database operations."""
    
    def create_job(
        self,
        job_id: UUID,
        team_id: str,
        service_name: str,
        spec_format: str,
        specification_hash: Optional[str] = None
    ) -> DocumentationJob:
        """
        Create a new documentation job record.
        
        Args:
            job_id: Unique job identifier
            team_id: Team identifier
            service_name: Service name
            spec_format: Specification format
            specification_hash: Hash of the specification content
            
        Returns:
            Created DocumentationJob instance
        """
        self.logger.info(f"Creating documentation job {job_id} for {team_id}/{service_name}")
        
        job = DocumentationJob(
            id=job_id,
            team_id=team_id,
            service_name=service_name,
            spec_format=spec_format,
            status="queued",
            specification_hash=specification_hash
        )
        
        try:
            self.db.add(job)
            self._commit_or_rollback()
            self.db.refresh(job)
            return job
        except SQLAlchemyError as e:
            self._handle_db_error("create_job", e)
    
    def update_job_status(self, job_id: UUID, status: str) -> Optional[DocumentationJob]:
        """
        Update job status.
        
        Args:
            job_id: Job identifier
            status: New status
            
        Returns:
            Updated DocumentationJob instance or None
        """
        job = self.db.query(DocumentationJob).filter(
            DocumentationJob.id == job_id
        ).first()
        
        if job:
            job.status = status
            if status in ["completed", "failed"]:
                job.completed_at = datetime.utcnow()
            
            try:
                self._commit_or_rollback()
                self.db.refresh(job)
            except SQLAlchemyError as e:
                self._handle_db_error("update_job_status", e)
        
        return job
    
    def get_job_by_id(self, job_id: UUID) -> Optional[DocumentationJob]:
        """
        Get job by ID.
        
        Args:
            job_id: Job identifier
            
        Returns:
            DocumentationJob instance or None
        """
        return self.db.query(DocumentationJob).filter(
            DocumentationJob.id == job_id
        ).first()
    
    def get_jobs_by_team(
        self, 
        team_id: str, 
        limit: int = 50,
        status_filter: Optional[str] = None
    ) -> List[DocumentationJob]:
        """
        Get jobs by team ID.
        
        Args:
            team_id: Team identifier
            limit: Maximum number of jobs to return
            status_filter: Optional status filter
            
        Returns:
            List of DocumentationJob instances
        """
        query = self.db.query(DocumentationJob).filter(
            DocumentationJob.team_id == team_id
        )
        
        if status_filter:
            query = query.filter(DocumentationJob.status == status_filter)
        
        return query.order_by(desc(DocumentationJob.created_at)).limit(limit).all()
    
    def get_jobs_by_service(
        self, 
        team_id: str, 
        service_name: str,
        limit: int = 20
    ) -> List[DocumentationJob]:
        """
        Get jobs for a specific service.
        
        Args:
            team_id: Team identifier
            service_name: Service name
            limit: Maximum number of jobs to return
            
        Returns:
            List of DocumentationJob instances
        """
        return (
            self.db.query(DocumentationJob)
            .filter(
                and_(
                    DocumentationJob.team_id == team_id,
                    DocumentationJob.service_name == service_name
                )
            )
            .order_by(desc(DocumentationJob.created_at))
            .limit(limit)
            .all()
        )
    
    def get_active_jobs(self) -> List[DocumentationJob]:
        """
        Get all active (queued or processing) jobs.
        
        Returns:
            List of active DocumentationJob instances
        """
        return self.db.query(DocumentationJob).filter(
            DocumentationJob.status.in_(["queued", "processing"])
        ).order_by(DocumentationJob.created_at).all()
    
    def get_job_statistics(self, time_period_days: int = 30) -> Dict[str, Any]:
        """
        Get job statistics for the specified time period.
        
        Args:
            time_period_days: Number of days to look back
            
        Returns:
            Dictionary with job statistics
        """
        cutoff_date = datetime.utcnow() - timedelta(days=time_period_days)
        
        total_jobs = self.db.query(func.count(DocumentationJob.id)).filter(
            DocumentationJob.created_at >= cutoff_date
        ).scalar()
        
        completed_jobs = self.db.query(func.count(DocumentationJob.id)).filter(
            and_(
                DocumentationJob.created_at >= cutoff_date,
                DocumentationJob.status == "completed"
            )
        ).scalar()
        
        failed_jobs = self.db.query(func.count(DocumentationJob.id)).filter(
            and_(
                DocumentationJob.created_at >= cutoff_date,
                DocumentationJob.status == "failed"
            )
        ).scalar()
        
        active_jobs = self.db.query(func.count(DocumentationJob.id)).filter(
            DocumentationJob.status.in_(["queued", "processing"])
        ).scalar()
        
        return {
            "total_jobs": total_jobs or 0,
            "completed_jobs": completed_jobs or 0,
            "failed_jobs": failed_jobs or 0,
            "active_jobs": active_jobs or 0,
            "success_rate": round((completed_jobs / total_jobs * 100) if total_jobs > 0 else 0, 1)
        }