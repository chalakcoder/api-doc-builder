"""
Job status tracking and lifecycle management service.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from uuid import UUID

import redis
from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models import DocumentationJob, QualityScoreDB
from app.jobs.models import JobStatus, JobResult, JobProgress

logger = logging.getLogger(__name__)


class JobStatusTracker:
    """Tracks job status, progress, and provides lifecycle management."""
    
    def __init__(self):
        """Initialize status tracker with Redis connection."""
        self.redis_client = redis.from_url(settings.REDIS_URL)
        self._progress_prefix = "job_progress:"
        self._metadata_prefix = "job_metadata:"
        self._stats_prefix = "job_stats:"
    
    async def get_job_history(self, team_id: Optional[str] = None, 
                            service_name: Optional[str] = None,
                            limit: int = 50) -> List[JobResult]:
        """
        Get job history with optional filtering.
        
        Args:
            team_id: Filter by team ID
            service_name: Filter by service name
            limit: Maximum number of jobs to return
            
        Returns:
            List of job results ordered by creation time (newest first)
        """
        db = SessionLocal()
        try:
            query = db.query(DocumentationJob)
            
            # Apply filters
            if team_id:
                query = query.filter(DocumentationJob.team_id == team_id)
            if service_name:
                query = query.filter(DocumentationJob.service_name == service_name)
            
            # Order by creation time and limit
            jobs = query.order_by(desc(DocumentationJob.created_at)).limit(limit).all()
            
            # Convert to JobResult objects
            job_results = []
            for job in jobs:
                # Get progress from Redis if available
                progress = self._get_job_progress_from_redis(job.id)
                
                # Get quality score if available
                quality_score = None
                if job.quality_scores:
                    latest_score = max(job.quality_scores, key=lambda x: x.created_at)
                    quality_score = {
                        "overall_score": latest_score.overall_score,
                        "completeness": latest_score.completeness_score,
                        "clarity": latest_score.clarity_score,
                        "accuracy": latest_score.accuracy_score,
                        "feedback": latest_score.feedback_json
                    }
                
                job_result = JobResult(
                    job_id=job.id,
                    status=JobStatus(job.status),
                    created_at=job.created_at,
                    completed_at=job.completed_at,
                    progress=progress,
                    results={"quality_metrics": quality_score} if quality_score else None
                )
                job_results.append(job_result)
            
            return job_results
            
        except Exception as e:
            logger.error(f"Failed to get job history: {e}")
            return []
        finally:
            db.close()
    
    async def get_active_jobs(self) -> List[JobResult]:
        """
        Get all currently active (queued or processing) jobs.
        
        Returns:
            List of active job results
        """
        db = SessionLocal()
        try:
            active_jobs = db.query(DocumentationJob).filter(
                DocumentationJob.status.in_([JobStatus.QUEUED.value, JobStatus.PROCESSING.value])
            ).order_by(DocumentationJob.created_at).all()
            
            job_results = []
            for job in active_jobs:
                progress = self._get_job_progress_from_redis(job.id)
                
                job_result = JobResult(
                    job_id=job.id,
                    status=JobStatus(job.status),
                    created_at=job.created_at,
                    progress=progress
                )
                job_results.append(job_result)
            
            return job_results
            
        except Exception as e:
            logger.error(f"Failed to get active jobs: {e}")
            return []
        finally:
            db.close()
    
    async def get_job_statistics(self, team_id: Optional[str] = None,
                               days: int = 7) -> Dict[str, Any]:
        """
        Get job statistics for the specified period.
        
        Args:
            team_id: Filter by team ID
            days: Number of days to include in statistics
            
        Returns:
            Dictionary with job statistics
        """
        db = SessionLocal()
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            query = db.query(DocumentationJob).filter(
                DocumentationJob.created_at >= cutoff_date
            )
            
            if team_id:
                query = query.filter(DocumentationJob.team_id == team_id)
            
            jobs = query.all()
            
            # Calculate statistics
            total_jobs = len(jobs)
            completed_jobs = len([j for j in jobs if j.status == JobStatus.COMPLETED.value])
            failed_jobs = len([j for j in jobs if j.status == JobStatus.FAILED.value])
            processing_jobs = len([j for j in jobs if j.status == JobStatus.PROCESSING.value])
            queued_jobs = len([j for j in jobs if j.status == JobStatus.QUEUED.value])
            
            # Calculate average processing time for completed jobs
            completed_with_times = [
                j for j in jobs 
                if j.status == JobStatus.COMPLETED.value and j.completed_at
            ]
            
            avg_processing_time = None
            if completed_with_times:
                processing_times = [
                    (j.completed_at - j.created_at).total_seconds()
                    for j in completed_with_times
                ]
                avg_processing_time = sum(processing_times) / len(processing_times)
            
            # Get quality score statistics
            quality_stats = self._get_quality_statistics(jobs, db)
            
            return {
                "period_days": days,
                "total_jobs": total_jobs,
                "completed_jobs": completed_jobs,
                "failed_jobs": failed_jobs,
                "processing_jobs": processing_jobs,
                "queued_jobs": queued_jobs,
                "success_rate": (completed_jobs / total_jobs * 100) if total_jobs > 0 else 0,
                "average_processing_time_seconds": avg_processing_time,
                "quality_statistics": quality_stats
            }
            
        except Exception as e:
            logger.error(f"Failed to get job statistics: {e}")
            return {}
        finally:
            db.close()
    
    def _get_job_progress_from_redis(self, job_id: UUID) -> Optional[JobProgress]:
        """Get job progress from Redis cache."""
        try:
            progress_data = self.redis_client.hgetall(f"{self._progress_prefix}{job_id}")
            
            if not progress_data:
                return None
            
            progress_dict = {k.decode(): v.decode() for k, v in progress_data.items()}
            
            return JobProgress(
                current_step=progress_dict["current_step"],
                total_steps=int(progress_dict["total_steps"]),
                completed_steps=int(progress_dict["completed_steps"]),
                estimated_completion=datetime.fromisoformat(progress_dict["estimated_completion"])
                    if progress_dict.get("estimated_completion") else None
            )
            
        except Exception as e:
            logger.error(f"Failed to get progress for job {job_id}: {e}")
            return None
    
    def _get_quality_statistics(self, jobs: List[DocumentationJob], 
                              db: Session) -> Dict[str, Any]:
        """Calculate quality score statistics for given jobs."""
        try:
            job_ids = [job.id for job in jobs]
            
            if not job_ids:
                return {}
            
            quality_scores = db.query(QualityScoreDB).filter(
                QualityScoreDB.job_id.in_(job_ids)
            ).all()
            
            if not quality_scores:
                return {}
            
            overall_scores = [score.overall_score for score in quality_scores]
            completeness_scores = [score.completeness_score for score in quality_scores]
            clarity_scores = [score.clarity_score for score in quality_scores]
            accuracy_scores = [score.accuracy_score for score in quality_scores]
            
            return {
                "total_scored_jobs": len(quality_scores),
                "average_overall_score": sum(overall_scores) / len(overall_scores),
                "average_completeness": sum(completeness_scores) / len(completeness_scores),
                "average_clarity": sum(clarity_scores) / len(clarity_scores),
                "average_accuracy": sum(accuracy_scores) / len(accuracy_scores),
                "min_score": min(overall_scores),
                "max_score": max(overall_scores)
            }
            
        except Exception as e:
            logger.error(f"Failed to calculate quality statistics: {e}")
            return {}
    
    async def estimate_completion_time(self, job_id: UUID) -> Optional[datetime]:
        """
        Estimate completion time for a job based on current queue and historical data.
        
        Args:
            job_id: Job identifier
            
        Returns:
            Estimated completion time or None if cannot estimate
        """
        try:
            # Get current job status
            db = SessionLocal()
            try:
                job = db.query(DocumentationJob).filter(
                    DocumentationJob.id == job_id
                ).first()
                
                if not job:
                    return None
                
                # If job is already completed or failed, return actual completion time
                if job.status in [JobStatus.COMPLETED.value, JobStatus.FAILED.value]:
                    return job.completed_at
                
                # If job is processing, get progress and estimate based on that
                if job.status == JobStatus.PROCESSING.value:
                    progress = self._get_job_progress_from_redis(job_id)
                    if progress and progress.estimated_completion:
                        return progress.estimated_completion
                
                # For queued jobs, estimate based on queue position and average processing time
                if job.status == JobStatus.QUEUED.value:
                    # Count jobs ahead in queue
                    jobs_ahead = db.query(DocumentationJob).filter(
                        and_(
                            DocumentationJob.status.in_([
                                JobStatus.QUEUED.value, 
                                JobStatus.PROCESSING.value
                            ]),
                            DocumentationJob.created_at < job.created_at
                        )
                    ).count()
                    
                    # Get average processing time from recent completed jobs
                    recent_completed = db.query(DocumentationJob).filter(
                        and_(
                            DocumentationJob.status == JobStatus.COMPLETED.value,
                            DocumentationJob.completed_at >= datetime.utcnow() - timedelta(days=7),
                            DocumentationJob.completed_at.isnot(None)
                        )
                    ).limit(50).all()
                    
                    if recent_completed:
                        processing_times = [
                            (job.completed_at - job.created_at).total_seconds()
                            for job in recent_completed
                        ]
                        avg_processing_time = sum(processing_times) / len(processing_times)
                    else:
                        # Default estimate if no historical data
                        avg_processing_time = 300  # 5 minutes
                    
                    # Estimate completion time
                    estimated_wait = jobs_ahead * avg_processing_time / settings.MAX_CONCURRENT_JOBS
                    estimated_completion = datetime.utcnow() + timedelta(
                        seconds=estimated_wait + avg_processing_time
                    )
                    
                    return estimated_completion
                
                return None
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Failed to estimate completion time for job {job_id}: {e}")
            return None
    
    async def get_queue_status(self) -> Dict[str, Any]:
        """
        Get current queue status and system load information.
        
        Returns:
            Dictionary with queue status information
        """
        try:
            db = SessionLocal()
            try:
                # Count jobs by status
                queued_count = db.query(DocumentationJob).filter(
                    DocumentationJob.status == JobStatus.QUEUED.value
                ).count()
                
                processing_count = db.query(DocumentationJob).filter(
                    DocumentationJob.status == JobStatus.PROCESSING.value
                ).count()
                
                # Get oldest queued job
                oldest_queued = db.query(DocumentationJob).filter(
                    DocumentationJob.status == JobStatus.QUEUED.value
                ).order_by(DocumentationJob.created_at).first()
                
                oldest_queued_age = None
                if oldest_queued:
                    oldest_queued_age = (datetime.utcnow() - oldest_queued.created_at).total_seconds()
                
                # Calculate system load
                system_load = processing_count / settings.MAX_CONCURRENT_JOBS * 100
                
                return {
                    "queued_jobs": queued_count,
                    "processing_jobs": processing_count,
                    "max_concurrent_jobs": settings.MAX_CONCURRENT_JOBS,
                    "system_load_percentage": system_load,
                    "oldest_queued_job_age_seconds": oldest_queued_age,
                    "estimated_queue_wait_minutes": (queued_count * 5) / settings.MAX_CONCURRENT_JOBS
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Failed to get queue status: {e}")
            return {}


# Global status tracker instance
status_tracker = JobStatusTracker()