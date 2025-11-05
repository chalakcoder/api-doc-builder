"""
High-level job service that combines job management and status tracking.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from uuid import UUID

from app.jobs.job_manager import job_manager
from app.jobs.status_tracker import status_tracker
from app.jobs.models import JobRequest, JobResult, JobStatus
from app.core.exceptions import (
    JobProcessingError, 
    DatabaseError, 
    handle_service_errors,
    ErrorContext
)

logger = logging.getLogger(__name__)


class JobService:
    """
    High-level service for managing documentation generation jobs.
    
    This service provides a unified interface for job submission, tracking,
    and management operations.
    """
    
    def __init__(self):
        """Initialize job service."""
        self.job_manager = job_manager
        self.status_tracker = status_tracker
    
    @handle_service_errors("job submission")
    async def submit_documentation_job(self, job_request: JobRequest) -> JobResult:
        """
        Submit a new documentation generation job.
        
        Args:
            job_request: Job request with specification and parameters
            
        Returns:
            JobResult with job ID and initial status
            
        Raises:
            JobProcessingError: If job submission fails
        """
        with ErrorContext("submit_documentation_job", 
                         service_name=job_request.service_name, 
                         team_id=job_request.team_id):
            
            logger.info(
                f"Submitting documentation job for {job_request.service_name} "
                f"(team: {job_request.team_id})"
            )
            
            try:
                # Submit job through job manager
                job_result = await self.job_manager.submit_job(job_request)
                
                # Update estimated completion time based on queue status
                estimated_completion = await self.status_tracker.estimate_completion_time(
                    job_result.job_id
                )
                
                if estimated_completion and job_result.progress:
                    job_result.progress.estimated_completion = estimated_completion
                
                logger.info(f"Job {job_result.job_id} submitted successfully")
                return job_result
                
            except Exception as e:
                raise JobProcessingError(
                    message=f"Failed to submit documentation job: {str(e)}",
                    details={
                        "service_name": job_request.service_name,
                        "team_id": job_request.team_id,
                        "spec_format": job_request.spec_format.value
                    }
                )
    
    @handle_service_errors("get job status")
    async def get_job_status(self, job_id: UUID) -> Optional[JobResult]:
        """
        Get current status and details of a job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            JobResult with current status and progress, or None if not found
            
        Raises:
            JobProcessingError: If status retrieval fails
        """
        with ErrorContext("get_job_status", job_id=str(job_id)):
            try:
                job_result = await self.job_manager.get_job_status(job_id)
                
                if job_result and job_result.status in [JobStatus.QUEUED, JobStatus.PROCESSING]:
                    # Update estimated completion time for active jobs
                    estimated_completion = await self.status_tracker.estimate_completion_time(job_id)
                    if estimated_completion and job_result.progress:
                        job_result.progress.estimated_completion = estimated_completion
                
                return job_result
                
            except Exception as e:
                # For job status retrieval, we don't want to raise exceptions for not found
                # Instead, log the error and return None
                logger.warning(f"Failed to get job status for {job_id}: {e}")
                return None
    
    @handle_service_errors("cancel job")
    async def cancel_job(self, job_id: UUID) -> bool:
        """
        Cancel a running or queued job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            True if job was cancelled successfully
            
        Raises:
            JobProcessingError: If cancellation fails
        """
        with ErrorContext("cancel_job", job_id=str(job_id)):
            try:
                logger.info(f"Cancelling job {job_id}")
                success = await self.job_manager.cancel_job(job_id)
                
                if success:
                    logger.info(f"Job {job_id} cancelled successfully")
                else:
                    logger.warning(f"Failed to cancel job {job_id}")
                    raise JobProcessingError(
                        message=f"Job {job_id} could not be cancelled",
                        job_id=str(job_id),
                        details={"reason": "Job may not exist or is already completed"}
                    )
                
                return success
                
            except JobProcessingError:
                raise
            except Exception as e:
                raise JobProcessingError(
                    message=f"Failed to cancel job {job_id}: {str(e)}",
                    job_id=str(job_id),
                    details={"original_error": str(e)}
                )
    
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
        try:
            return await self.status_tracker.get_job_history(
                team_id=team_id,
                service_name=service_name,
                limit=limit
            )
            
        except Exception as e:
            logger.error(f"Failed to get job history: {e}")
            return []
    
    async def get_active_jobs(self) -> List[JobResult]:
        """
        Get all currently active (queued or processing) jobs.
        
        Returns:
            List of active job results
        """
        try:
            return await self.status_tracker.get_active_jobs()
            
        except Exception as e:
            logger.error(f"Failed to get active jobs: {e}")
            return []
    
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
        try:
            return await self.status_tracker.get_job_statistics(
                team_id=team_id,
                days=days
            )
            
        except Exception as e:
            logger.error(f"Failed to get job statistics: {e}")
            return {}
    
    async def get_queue_status(self) -> Dict[str, Any]:
        """
        Get current queue status and system load information.
        
        Returns:
            Dictionary with queue status information
        """
        try:
            return await self.status_tracker.get_queue_status()
            
        except Exception as e:
            logger.error(f"Failed to get queue status: {e}")
            return {}
    
    async def get_team_performance(self, team_id: str, days: int = 30) -> Dict[str, Any]:
        """
        Get performance metrics for a specific team.
        
        Args:
            team_id: Team identifier
            days: Number of days to analyze
            
        Returns:
            Dictionary with team performance metrics
        """
        try:
            # Get team-specific statistics
            team_stats = await self.get_job_statistics(team_id=team_id, days=days)
            
            # Get team job history
            team_jobs = await self.get_job_history(team_id=team_id, limit=100)
            
            # Calculate additional team metrics
            recent_jobs = [
                job for job in team_jobs
                if job.created_at >= datetime.utcnow() - timedelta(days=days)
            ]
            
            services_documented = len(set(
                job.results.get("service_name") for job in recent_jobs
                if job.results and job.results.get("service_name")
            ))
            
            # Calculate quality trend
            quality_scores = []
            for job in recent_jobs:
                if (job.results and job.results.get("quality_metrics") and
                    job.results["quality_metrics"].get("overall_score")):
                    quality_scores.append({
                        "score": job.results["quality_metrics"]["overall_score"],
                        "date": job.created_at
                    })
            
            quality_trend = "stable"
            if len(quality_scores) >= 2:
                recent_avg = sum(s["score"] for s in quality_scores[-5:]) / min(5, len(quality_scores))
                older_avg = sum(s["score"] for s in quality_scores[:-5]) / max(1, len(quality_scores) - 5)
                
                if recent_avg > older_avg + 5:
                    quality_trend = "improving"
                elif recent_avg < older_avg - 5:
                    quality_trend = "declining"
            
            return {
                **team_stats,
                "team_id": team_id,
                "services_documented": services_documented,
                "quality_trend": quality_trend,
                "recent_quality_scores": quality_scores[-10:],  # Last 10 scores
            }
            
        except Exception as e:
            logger.error(f"Failed to get team performance for {team_id}: {e}")
            return {}
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on job processing system.
        
        Returns:
            Dictionary with health status information
        """
        try:
            # Check Redis connectivity
            redis_healthy = False
            try:
                self.job_manager.redis_client.ping()
                redis_healthy = True
            except Exception as e:
                logger.error(f"Redis health check failed: {e}")
            
            # Check database connectivity
            db_healthy = False
            try:
                from app.db.database import SessionLocal
                db = SessionLocal()
                db.execute("SELECT 1")
                db.close()
                db_healthy = True
            except Exception as e:
                logger.error(f"Database health check failed: {e}")
            
            # Get queue status
            queue_status = await self.get_queue_status()
            
            # Determine overall health
            overall_healthy = redis_healthy and db_healthy
            
            return {
                "healthy": overall_healthy,
                "redis_healthy": redis_healthy,
                "database_healthy": db_healthy,
                "queue_status": queue_status,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "healthy": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }


# Global job service instance
job_service = JobService()