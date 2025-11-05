"""
Celery tasks for async documentation generation and processing.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any
from uuid import UUID

from celery import Task
from celery.exceptions import Retry

from app.jobs.celery_app import celery_app
from app.jobs.models import JobStatus, JobRequest, JobProgress, SpecFormat, OutputFormat
from app.services.documentation_generator import DocumentationGenerator
from app.services.quality_service import QualityService
from app.parsers.parser_factory import ParserFactory

logger = logging.getLogger(__name__)


class CallbackTask(Task):
    """Base task class with callback support for job status updates."""
    
    def on_success(self, retval, task_id, args, kwargs):
        """Called when task succeeds."""
        logger.info(f"Task {task_id} completed successfully")
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when task fails."""
        logger.error(f"Task {task_id} failed: {exc}")
        
        # Update job status to failed
        job_id = kwargs.get('job_id') or (args[0] if args else None)
        if job_id:
            from app.jobs.job_manager import job_manager
            import asyncio
            
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            loop.run_until_complete(
                job_manager.update_job_status(
                    UUID(job_id),
                    JobStatus.FAILED,
                    error_message=str(exc)
                )
            )


@celery_app.task(bind=True, base=CallbackTask, name="app.jobs.tasks.generate_documentation")
def generate_documentation(self, job_id: str, job_request: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate documentation from specification using GenAI.
    
    Args:
        job_id: Unique job identifier
        job_request: Job request data
        
    Returns:
        Dictionary with generated documentation and metadata
    """
    from app.jobs.job_manager import job_manager
    import asyncio
    
    try:
        # Set up async event loop
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        job_uuid = UUID(job_id)
        request = JobRequest(**job_request)
        
        logger.info(f"Starting documentation generation for job {job_id}")
        
        # Update job status to processing
        loop.run_until_complete(
            job_manager.update_job_status(
                job_uuid,
                JobStatus.PROCESSING,
                JobProgress(
                    current_step="Parsing specification",
                    total_steps=5,
                    completed_steps=1,
                    estimated_completion=datetime.utcnow() + timedelta(minutes=4)
                )
            )
        )
        
        # Step 1: Parse specification
        parser_factory = ParserFactory()
        parser = parser_factory.get_parser(request.spec_format)
        
        if isinstance(request.specification, str):
            # Handle string specification (URL or raw content)
            parsed_spec = loop.run_until_complete(
                parser.parse_from_content(request.specification)
            )
        else:
            # Handle dictionary specification
            parsed_spec = loop.run_until_complete(
                parser.parse(request.specification)
            )
        
        # Step 2: Generate documentation
        loop.run_until_complete(
            job_manager.update_job_status(
                job_uuid,
                JobStatus.PROCESSING,
                JobProgress(
                    current_step="Generating documentation content",
                    total_steps=5,
                    completed_steps=2,
                    estimated_completion=datetime.utcnow() + timedelta(minutes=3)
                )
            )
        )
        
        doc_generator = DocumentationGenerator()
        generated_docs = {}
        
        for output_format in request.output_formats:
            content = loop.run_until_complete(
                doc_generator.generate_documentation(
                    parsed_spec,
                    output_format,
                    request.service_name
                )
            )
            generated_docs[output_format.value] = content
        
        # Step 3: Format and store documentation
        loop.run_until_complete(
            job_manager.update_job_status(
                job_uuid,
                JobStatus.PROCESSING,
                JobProgress(
                    current_step="Formatting and storing documentation",
                    total_steps=5,
                    completed_steps=3,
                    estimated_completion=datetime.utcnow() + timedelta(minutes=2)
                )
            )
        )
        
        # Store generated files and get URLs
        file_urls = {}
        for format_type, content in generated_docs.items():
            # In a real implementation, you would store files to disk/cloud storage
            # For now, we'll simulate this
            file_path = f"/storage/{job_id}/{request.service_name}.{format_type}"
            file_urls[f"{format_type}_url"] = f"/api/v1/downloads{file_path}"
        
        # Step 4: Calculate quality score
        loop.run_until_complete(
            job_manager.update_job_status(
                job_uuid,
                JobStatus.PROCESSING,
                JobProgress(
                    current_step="Calculating quality score",
                    total_steps=5,
                    completed_steps=4,
                    estimated_completion=datetime.utcnow() + timedelta(minutes=1)
                )
            )
        )
        
        # Submit quality scoring as separate task
        quality_task = calculate_quality_score.delay(
            job_id=job_id,
            specification=request.specification,
            generated_docs=generated_docs,
            team_id=request.team_id,
            service_name=request.service_name
        )
        
        # Step 5: Finalize job
        loop.run_until_complete(
            job_manager.update_job_status(
                job_uuid,
                JobStatus.PROCESSING,
                JobProgress(
                    current_step="Finalizing documentation",
                    total_steps=5,
                    completed_steps=5,
                    estimated_completion=datetime.utcnow()
                )
            )
        )
        
        # Prepare results
        results = {
            **file_urls,
            "generated_content": generated_docs,
            "quality_task_id": quality_task.id,
            "team_id": request.team_id,
            "service_name": request.service_name,
            "spec_format": request.spec_format.value
        }
        
        # Mark job as completed
        loop.run_until_complete(
            job_manager.update_job_status(
                job_uuid,
                JobStatus.COMPLETED,
                results=results
            )
        )
        
        logger.info(f"Documentation generation completed for job {job_id}")
        return results
        
    except Exception as e:
        logger.error(f"Documentation generation failed for job {job_id}: {e}")
        
        # Update job status to failed
        try:
            loop.run_until_complete(
                job_manager.update_job_status(
                    UUID(job_id),
                    JobStatus.FAILED,
                    error_message=str(e)
                )
            )
        except Exception as update_error:
            logger.error(f"Failed to update job status: {update_error}")
        
        raise


@celery_app.task(bind=True, base=CallbackTask, name="app.jobs.tasks.calculate_quality_score")
def calculate_quality_score(self, job_id: str, specification: Dict[str, Any] | str,
                          generated_docs: Dict[str, str], team_id: str, 
                          service_name: str) -> Dict[str, Any]:
    """
    Calculate quality score for generated documentation.
    
    Args:
        job_id: Job identifier
        specification: Original specification
        generated_docs: Generated documentation content
        team_id: Team identifier
        service_name: Service name
        
    Returns:
        Quality metrics and score
    """
    import asyncio
    
    try:
        # Set up async event loop
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        logger.info(f"Calculating quality score for job {job_id}")
        
        quality_service = QualityService()
        
        # Calculate quality metrics
        quality_metrics = loop.run_until_complete(
            quality_service.calculate_quality_score(
                specification=specification,
                generated_documentation=generated_docs,
                team_id=team_id,
                service_name=service_name
            )
        )
        
        # Store quality score in database
        loop.run_until_complete(
            quality_service.store_quality_score(
                job_id=UUID(job_id),
                quality_metrics=quality_metrics
            )
        )
        
        logger.info(f"Quality score calculated for job {job_id}: {quality_metrics.overall_score}")
        
        return {
            "quality_score": quality_metrics.overall_score,
            "quality_metrics": quality_metrics.dict(),
            "job_id": job_id
        }
        
    except Exception as e:
        logger.error(f"Quality score calculation failed for job {job_id}: {e}")
        raise


@celery_app.task(name="app.jobs.tasks.cleanup_expired_jobs")
def cleanup_expired_jobs(max_age_hours: int = 24) -> int:
    """
    Periodic task to clean up expired job data.
    
    Args:
        max_age_hours: Maximum age of jobs to keep in hours
        
    Returns:
        Number of jobs cleaned up
    """
    from app.jobs.job_manager import job_manager
    import asyncio
    
    try:
        # Set up async event loop
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        cleaned_count = loop.run_until_complete(
            job_manager.cleanup_expired_jobs(max_age_hours)
        )
        
        logger.info(f"Cleanup task completed: {cleaned_count} jobs cleaned")
        return cleaned_count
        
    except Exception as e:
        logger.error(f"Cleanup task failed: {e}")
        raise


# Configure periodic tasks
celery_app.conf.beat_schedule = {
    'cleanup-expired-jobs': {
        'task': 'app.jobs.tasks.cleanup_expired_jobs',
        'schedule': 3600.0,  # Run every hour
        'args': (24,)  # Clean jobs older than 24 hours
    },
}
celery_app.conf.timezone = 'UTC'