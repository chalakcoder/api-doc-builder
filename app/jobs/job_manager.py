"""
Job management service for handling documentation generation jobs.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from uuid import UUID, uuid4

import redis
from celery.result import AsyncResult
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models import DocumentationJob
from app.jobs.celery_app import celery_app
from app.jobs.models import JobStatus, JobRequest, JobResult, JobProgress

logger = logging.getLogger(__name__)


class JobManager:
    """Manages documentation generation jobs and their lifecycle."""
    
    def __init__(self):
        """Initialize job manager with Redis connection."""
        try:
            self.redis_client = redis.from_url(settings.REDIS_URL)
            # Test the connection
            self.redis_client.ping()
            logger.info("Connected to Redis server")
        except Exception as e:
            logger.warning(f"Redis not available ({e}), using in-memory storage for development")
            from app.core.dev_redis import get_mock_redis_client
            self.redis_client = get_mock_redis_client()
        
        self._job_progress_prefix = "job_progress:"
        self._job_metadata_prefix = "job_metadata:"
    
    async def submit_job(self, job_request: JobRequest) -> JobResult:
        """
        Submit a new documentation generation job.
        
        Args:
            job_request: Job request with specification and parameters
            
        Returns:
            JobResult with job ID and initial status
        """
        job_id = uuid4()
        
        # Store job in database
        db = SessionLocal()
        try:
            db_job = DocumentationJob(
                id=job_id,
                team_id=job_request.team_id,
                service_name=job_request.service_name,
                spec_format=job_request.spec_format.value,
                status=JobStatus.QUEUED.value,
                created_at=datetime.utcnow()
            )
            db.add(db_job)
            db.commit()
            
            # Store job metadata in Redis for quick access
            job_metadata = {
                "job_id": str(job_id),
                "team_id": job_request.team_id,
                "service_name": job_request.service_name,
                "spec_format": job_request.spec_format.value,
                "output_formats": [fmt.value for fmt in job_request.output_formats],
                "created_at": datetime.utcnow().isoformat(),
                "status": JobStatus.QUEUED.value
            }
            
            self.redis_client.hset(
                f"{self._job_metadata_prefix}{job_id}",
                mapping=job_metadata
            )
            self.redis_client.expire(f"{self._job_metadata_prefix}{job_id}", 86400)  # 24 hours
            
            # Initialize job progress
            progress = JobProgress(
                current_step="Queued for processing",
                total_steps=5,  # Parse, Generate, Format, Score, Store
                completed_steps=0,
                estimated_completion=datetime.utcnow() + timedelta(minutes=5)
            )
            
            self._update_job_progress(job_id, progress)
            
            # Submit to Celery
            from app.jobs.tasks import generate_documentation
            celery_result = generate_documentation.delay(
                job_id=str(job_id),
                job_request=job_request.dict()
            )
            
            # Store Celery task ID for tracking
            self.redis_client.hset(
                f"{self._job_metadata_prefix}{job_id}",
                "celery_task_id",
                celery_result.id
            )
            
            logger.info(f"Job {job_id} submitted successfully")
            
            return JobResult(
                job_id=job_id,
                status=JobStatus.QUEUED,
                created_at=datetime.utcnow(),
                progress=progress
            )
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to submit job: {e}")
            raise
        finally:
            db.close()
    
    async def get_job_status(self, job_id: UUID) -> Optional[JobResult]:
        """
        Get current status of a job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            JobResult with current status and progress, or None if not found
        """
        try:
            # Get job metadata from Redis first (faster)
            job_data = self.redis_client.hgetall(f"{self._job_metadata_prefix}{job_id}")
            
            if not job_data:
                # Fallback to database
                db = SessionLocal()
                try:
                    db_job = db.query(DocumentationJob).filter(
                        DocumentationJob.id == job_id
                    ).first()
                    
                    if not db_job:
                        return None
                    
                    return JobResult(
                        job_id=job_id,
                        status=JobStatus(db_job.status),
                        created_at=db_job.created_at,
                        completed_at=db_job.completed_at
                    )
                finally:
                    db.close()
            
            # Decode Redis data
            job_metadata = {k.decode(): v.decode() for k, v in job_data.items()}
            
            # Get progress information
            progress = self._get_job_progress(job_id)
            
            # Get Celery task status if available
            celery_task_id = job_metadata.get("celery_task_id")
            celery_result = None
            if celery_task_id:
                celery_result = AsyncResult(celery_task_id, app=celery_app)
            
            # Determine current status
            current_status = JobStatus(job_metadata["status"])
            
            # Get results if job is completed
            results = None
            if current_status == JobStatus.COMPLETED:
                results = self._get_job_results(job_id)
            
            # Get error message if job failed
            error_message = None
            if current_status == JobStatus.FAILED and celery_result:
                error_message = str(celery_result.info) if celery_result.failed() else None
            
            return JobResult(
                job_id=job_id,
                status=current_status,
                created_at=datetime.fromisoformat(job_metadata["created_at"]),
                completed_at=datetime.fromisoformat(job_metadata["completed_at"]) 
                    if job_metadata.get("completed_at") else None,
                progress=progress,
                results=results,
                error_message=error_message
            )
            
        except Exception as e:
            logger.error(f"Failed to get job status for {job_id}: {e}")
            return None
    
    def _update_job_progress(self, job_id: UUID, progress: JobProgress) -> None:
        """Update job progress in Redis."""
        progress_data = {
            "current_step": progress.current_step,
            "total_steps": progress.total_steps,
            "completed_steps": progress.completed_steps,
            "estimated_completion": progress.estimated_completion.isoformat() 
                if progress.estimated_completion else None
        }
        
        self.redis_client.hset(
            f"{self._job_progress_prefix}{job_id}",
            mapping=progress_data
        )
        self.redis_client.expire(f"{self._job_progress_prefix}{job_id}", 86400)
    
    def _get_job_progress(self, job_id: UUID) -> Optional[JobProgress]:
        """Get job progress from Redis."""
        progress_data = self.redis_client.hgetall(f"{self._job_progress_prefix}{job_id}")
        
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
    
    def _get_job_results(self, job_id: UUID) -> Optional[Dict[str, Any]]:
        """Get job results from Redis."""
        results_key = f"job_results:{job_id}"
        results_data = self.redis_client.get(results_key)
        
        if results_data:
            import json
            return json.loads(results_data.decode())
        
        return None
    
    async def update_job_status(self, job_id: UUID, status: JobStatus, 
                              progress: Optional[JobProgress] = None,
                              results: Optional[Dict[str, Any]] = None,
                              error_message: Optional[str] = None) -> None:
        """
        Update job status and related information.
        
        Args:
            job_id: Job identifier
            status: New job status
            progress: Updated progress information
            results: Job results (for completed jobs)
            error_message: Error message (for failed jobs)
        """
        try:
            # Update database
            db = SessionLocal()
            try:
                db_job = db.query(DocumentationJob).filter(
                    DocumentationJob.id == job_id
                ).first()
                
                if db_job:
                    db_job.status = status.value
                    if status in [JobStatus.COMPLETED, JobStatus.FAILED]:
                        db_job.completed_at = datetime.utcnow()
                    
                    db.commit()
            finally:
                db.close()
            
            # Update Redis metadata
            updates = {"status": status.value}
            if status in [JobStatus.COMPLETED, JobStatus.FAILED]:
                updates["completed_at"] = datetime.utcnow().isoformat()
            
            self.redis_client.hset(
                f"{self._job_metadata_prefix}{job_id}",
                mapping=updates
            )
            
            # Update progress if provided
            if progress:
                self._update_job_progress(job_id, progress)
            
            # Store results if provided
            if results:
                import json
                self.redis_client.set(
                    f"job_results:{job_id}",
                    json.dumps(results),
                    ex=86400  # 24 hours
                )
            
            logger.info(f"Job {job_id} status updated to {status.value}")
            
        except Exception as e:
            logger.error(f"Failed to update job status for {job_id}: {e}")
            raise
    
    async def cancel_job(self, job_id: UUID) -> bool:
        """
        Cancel a running job.
        
        Args:
            job_id: Job identifier
            
        Returns:
            True if job was cancelled successfully
        """
        try:
            # Get Celery task ID
            job_data = self.redis_client.hgetall(f"{self._job_metadata_prefix}{job_id}")
            if not job_data:
                return False
            
            job_metadata = {k.decode(): v.decode() for k, v in job_data.items()}
            celery_task_id = job_metadata.get("celery_task_id")
            
            if celery_task_id:
                # Revoke Celery task
                celery_app.control.revoke(celery_task_id, terminate=True)
            
            # Update job status
            await self.update_job_status(job_id, JobStatus.CANCELLED)
            
            logger.info(f"Job {job_id} cancelled successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to cancel job {job_id}: {e}")
            return False
    
    async def cleanup_expired_jobs(self, max_age_hours: int = 24) -> int:
        """
        Clean up expired job data from Redis.
        
        Args:
            max_age_hours: Maximum age of jobs to keep
            
        Returns:
            Number of jobs cleaned up
        """
        try:
            cutoff_time = datetime.utcnow() - timedelta(hours=max_age_hours)
            
            # Get all job metadata keys
            pattern = f"{self._job_metadata_prefix}*"
            keys = self.redis_client.keys(pattern)
            
            cleaned_count = 0
            for key in keys:
                job_data = self.redis_client.hgetall(key)
                if job_data:
                    job_metadata = {k.decode(): v.decode() for k, v in job_data.items()}
                    created_at = datetime.fromisoformat(job_metadata["created_at"])
                    
                    if created_at < cutoff_time:
                        job_id = job_metadata["job_id"]
                        
                        # Delete all related keys
                        self.redis_client.delete(key)
                        self.redis_client.delete(f"{self._job_progress_prefix}{job_id}")
                        self.redis_client.delete(f"job_results:{job_id}")
                        
                        cleaned_count += 1
            
            logger.info(f"Cleaned up {cleaned_count} expired jobs")
            return cleaned_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup expired jobs: {e}")
            return 0


# Global job manager instance
job_manager = JobManager()