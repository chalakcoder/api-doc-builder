"""
REST API endpoints for the Spec Documentation API.
"""
import logging
from typing import Optional, Dict, Any, List
from uuid import UUID
import json
import tempfile
import os

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session
import httpx

from app.jobs.models import (
    JobRequest, JobResult, SpecFormat, OutputFormat, 
    QualityMetrics, DocumentationOutput
)
from app.jobs.job_service import job_service
from app.validators.validators import SpecificationValidator
from app.validators.format_detector import FormatDetector
from app.core.rate_limiter import rate_limiter
from app.services.leaderboard_service import (
    LeaderboardService, TimePeriod, ServiceType, create_leaderboard_service
)
from app.services.quality_monitor import QualityMonitor, create_quality_monitor
from app.db.database import get_db
from app.core.exceptions import (
    ValidationError, 
    SpecificationError, 
    JobProcessingError,
    RateLimitError,
    ErrorContext
)

logger = logging.getLogger(__name__)

# Create API router
router = APIRouter(prefix="/api/v1", tags=["documentation"])

# Request models for different input methods
class SpecificationURLRequest(BaseModel):
    """Request model for URL-based specification submission."""
    specification_url: str
    output_formats: List[OutputFormat] = [OutputFormat.MARKDOWN]
    team_id: str
    service_name: str

class SpecificationJSONRequest(BaseModel):
    """Request model for direct JSON specification submission."""
    specification: Dict[str, Any]
    spec_format: SpecFormat
    output_formats: List[OutputFormat] = [OutputFormat.MARKDOWN]
    team_id: str
    service_name: str

class JobStatusResponse(BaseModel):
    """Response model for job status."""
    job_id: str
    status: str
    created_at: str
    completed_at: Optional[str] = None
    progress: Optional[Dict[str, Any]] = None
    results: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None

# Leaderboard response models
class TeamRankingResponse(BaseModel):
    """Response model for team ranking."""
    team_id: str
    team_name: str
    average_score: float
    total_docs: int
    trend: str
    rank: int
    last_updated: str

class PoorQualityServiceResponse(BaseModel):
    """Response model for poor quality service."""
    service_name: str
    team_id: str
    score: int
    last_updated: str
    improvement_needed: List[str]

class LeaderboardResponse(BaseModel):
    """Response model for leaderboard data."""
    rankings: List[TeamRankingResponse]
    poor_quality_services: List[PoorQualityServiceResponse]
    generated_at: str
    time_period: str
    filters_applied: Dict[str, Any]

class QualityAlertResponse(BaseModel):
    """Response model for quality alerts."""
    service_name: str
    team_id: str
    current_score: int
    previous_score: Optional[int]
    severity: str
    issues_identified: List[str]
    recommended_actions: List[str]
    created_at: str
    alert_id: str

class QualityMonitoringResponse(BaseModel):
    """Response model for quality monitoring report."""
    total_services_monitored: int
    poor_quality_count: int
    alerts_generated: List[QualityAlertResponse]
    trend_analysis: Dict[str, str]
    recommendations: List[str]
    generated_at: str

# Dependency for rate limiting
async def rate_limit_check(request: Request):
    """Rate limiting dependency."""
    rate_limit_info = await rate_limiter.check_rate_limit(request)
    
    # Add rate limit headers to response if available
    if "headers" in rate_limit_info:
        # Note: Headers will be added by middleware or manually in endpoints
        # This is just the check - headers are added in the endpoint responses
        pass
    
    return rate_limit_info

@router.post("/generate-docs/file", response_model=JobStatusResponse)
async def generate_documentation_from_file(
    request: Request,
    specification_file: UploadFile = File(...),
    output_formats: Optional[str] = Form(None),
    team_id: str = Form(...),
    service_name: str = Form(...),
    _: None = Depends(rate_limit_check)
):
    """
    Generate documentation from uploaded file.
    
    Requirements: 1.1, 1.4, 1.5
    """
    with ErrorContext("generate_documentation_from_file", 
                     method=request.method, 
                     path=str(request.url.path)):
        try:
            # Parse output formats from form data
            formats = [OutputFormat.MARKDOWN]  # default
            if output_formats:
                # Handle both JSON array and comma-separated string formats
                try:
                    # First try to parse as JSON array
                    format_list = json.loads(output_formats)
                    if isinstance(format_list, list):
                        formats = [OutputFormat(f) for f in format_list]
                    else:
                        # Single format as string
                        formats = [OutputFormat(format_list)]
                except json.JSONDecodeError:
                    # If JSON parsing fails, try comma-separated string
                    try:
                        format_strings = [f.strip() for f in output_formats.split(',')]
                        formats = [OutputFormat(f) for f in format_strings if f]
                    except ValueError as e:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Invalid output_formats. Expected JSON array like [\"markdown\", \"html\"] or comma-separated string like \"markdown,html\". Error: {e}"
                        )
                except ValueError as e:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid output format value: {e}"
                    )
            
            # Rest of the function remains the same...
            # Read and validate file
            if specification_file.size and specification_file.size > 10 * 1024 * 1024:  # 10MB limit
                raise ValidationError(
                    message="File size exceeds 10MB limit",
                    field="specification_file",
                    details={"file_size": specification_file.size, "max_size": 10 * 1024 * 1024}
                )
            
            file_content = await specification_file.read()
            
            # Detect format and validate
            format_detector = FormatDetector()
            detected_format = format_detector.detect_format(
                content=file_content.decode('utf-8'),
                filename=specification_file.filename
            )
            
            if not detected_format:
                raise SpecificationError(
                    message="Unable to detect specification format. Supported formats: OpenAPI, GraphQL, JSON Schema",
                    details={
                        "filename": specification_file.filename,
                        "supported_formats": ["OpenAPI", "GraphQL", "JSON Schema"]
                    }
                )
            
            # Validate specification
            validator = SpecificationValidator()
            validation_result = validator.validate_specification(
                content=file_content.decode('utf-8'),
                spec_format=detected_format
            )
            
            if not validation_result.is_valid:
                raise SpecificationError(
                    message=f"Specification validation failed: {'; '.join(validation_result.errors)}",
                    spec_format=detected_format.value,
                    details={
                        "validation_errors": validation_result.errors,
                        "filename": specification_file.filename
                    }
                )
            
            # Create job request
            job_request = JobRequest(
                specification=file_content.decode('utf-8'),
                spec_format=detected_format,
                output_formats=formats,
                team_id=team_id,
                service_name=service_name
            )
            
            # Submit job
            job_result = await job_service.submit_documentation_job(job_request)
            
            # Convert to response model
            response = JobStatusResponse(
                job_id=str(job_result.job_id),
                status=job_result.status.value,
                created_at=job_result.created_at.isoformat(),
                completed_at=job_result.completed_at.isoformat() if job_result.completed_at else None,
                progress=job_result.progress.dict() if job_result.progress else None,
                results=job_result.results,
                error_message=job_result.error_message
            )
            
            logger.info(f"Documentation generation job {job_result.job_id} submitted successfully from file")
            return response
            
        except (ValidationError, SpecificationError, JobProcessingError):
            raise
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in generate_documentation_from_file: {e}", exc_info=True)
            raise

@router.post("/generate-docs/url", response_model=JobStatusResponse)
async def generate_documentation_from_url(
    request: Request,
    json_request: SpecificationURLRequest,
    _: None = Depends(rate_limit_check)
):
    """
    Generate documentation from URL reference.
    
    Requirements: 1.1, 1.4, 1.5
    """
    with ErrorContext("generate_documentation_from_url", 
                     method=request.method, 
                     path=str(request.url.path)):
        try:
            # Fetch specification from URL
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(json_request.specification_url, timeout=30.0)
                    response.raise_for_status()
                    spec_content = response.text
            except httpx.RequestError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to fetch specification from URL: {e}"
                )
            except httpx.HTTPStatusError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"HTTP error fetching specification: {e.response.status_code}"
                )
            
            # Detect format
            format_detector = FormatDetector()
            detected_format = format_detector.detect_format(
                content=spec_content,
                url=json_request.specification_url
            )
            
            if not detected_format:
                raise HTTPException(
                    status_code=400,
                    detail="Unable to detect specification format from URL content"
                )
            
            # Validate specification
            validator = SpecificationValidator()
            validation_result = validator.validate_specification(
                content=spec_content,
                spec_format=detected_format
            )
            
            if not validation_result.is_valid:
                raise HTTPException(
                    status_code=400,
                    detail=f"Specification validation failed: {'; '.join(validation_result.errors)}"
                )
            
            # Create job request
            job_request = JobRequest(
                specification=spec_content,
                spec_format=detected_format,
                output_formats=json_request.output_formats,
                team_id=json_request.team_id,
                service_name=json_request.service_name
            )
            
            # Submit job
            job_result = await job_service.submit_documentation_job(job_request)
            
            # Convert to response model
            response = JobStatusResponse(
                job_id=str(job_result.job_id),
                status=job_result.status.value,
                created_at=job_result.created_at.isoformat(),
                completed_at=job_result.completed_at.isoformat() if job_result.completed_at else None,
                progress=job_result.progress.dict() if job_result.progress else None,
                results=job_result.results,
                error_message=job_result.error_message
            )
            
            logger.info(f"Documentation generation job {job_result.job_id} submitted successfully from URL")
            return response
            
        except (ValidationError, SpecificationError, JobProcessingError):
            raise
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in generate_documentation_from_url: {e}", exc_info=True)
            raise


@router.post("/generate-docs/json", response_model=JobStatusResponse)
async def generate_documentation_from_json(
    request: Request,
    json_request: SpecificationJSONRequest,
    _: None = Depends(rate_limit_check)
):
    """
    Generate documentation from direct JSON payload.
    
    Requirements: 1.1, 1.4, 1.5
    """
    with ErrorContext("generate_documentation_from_json", 
                     method=request.method, 
                     path=str(request.url.path)):
        try:
            # Validate specification
            validator = SpecificationValidator()
            validation_result = validator.validate_specification(
                content=json.dumps(json_request.specification) if isinstance(json_request.specification, dict) else json_request.specification,
                spec_format=json_request.spec_format
            )
            
            if not validation_result.is_valid:
                raise HTTPException(
                    status_code=400,
                    detail=f"Specification validation failed: {'; '.join(validation_result.errors)}"
                )
            
            # Create job request
            job_request = JobRequest(
                specification=json_request.specification,
                spec_format=json_request.spec_format,
                output_formats=json_request.output_formats,
                team_id=json_request.team_id,
                service_name=json_request.service_name
            )
            
            # Submit job
            job_result = await job_service.submit_documentation_job(job_request)
            
            # Convert to response model
            response = JobStatusResponse(
                job_id=str(job_result.job_id),
                status=job_result.status.value,
                created_at=job_result.created_at.isoformat(),
                completed_at=job_result.completed_at.isoformat() if job_result.completed_at else None,
                progress=job_result.progress.dict() if job_result.progress else None,
                results=job_result.results,
                error_message=job_result.error_message
            )
            
            logger.info(f"Documentation generation job {job_result.job_id} submitted successfully from JSON")
            return response
            
        except (ValidationError, SpecificationError, JobProcessingError):
            raise
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in generate_documentation_from_json: {e}", exc_info=True)
            raise

@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    _: None = Depends(rate_limit_check)
):
    """
    Get the status and results of a documentation generation job.
    
    Requirements: 2.4, 3.4
    """
    try:
        # Parse job ID
        try:
            job_uuid = UUID(job_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid job ID format")
        
        # Get job status
        job_result = await job_service.get_job_status(job_uuid)
        
        if not job_result:
            raise HTTPException(status_code=404, detail="Job not found")
        
        # Convert to response model
        response = JobStatusResponse(
            job_id=str(job_result.job_id),
            status=job_result.status.value,
            created_at=job_result.created_at.isoformat(),
            completed_at=job_result.completed_at.isoformat() if job_result.completed_at else None,
            progress=job_result.progress.dict() if job_result.progress else None,
            results=job_result.results,
            error_message=job_result.error_message
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_job_status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/jobs/{job_id}/download/{format}")
async def download_documentation(
    job_id: str,
    format: str,
    _: None = Depends(rate_limit_check)
):
    """
    Download generated documentation file.
    
    Requirements: 2.4
    """
    try:
        # Parse job ID
        try:
            job_uuid = UUID(job_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid job ID format")
        
        # Validate format
        if format not in ["markdown", "html"]:
            raise HTTPException(status_code=400, detail="Format must be 'markdown' or 'html'")
        
        # Get job status
        job_result = await job_service.get_job_status(job_uuid)
        
        if not job_result:
            raise HTTPException(status_code=404, detail="Job not found")
        
        if job_result.status.value != "completed":
            raise HTTPException(status_code=400, detail="Job is not completed")
        
        if not job_result.results:
            raise HTTPException(status_code=404, detail="No results available")
        
        # Get file content from results
        content_key = f"{format}_content"
        if content_key not in job_result.results:
            raise HTTPException(status_code=404, detail=f"{format.title()} format not available")
        
        content = job_result.results[content_key]
        
        # Create temporary file for download
        file_extension = "md" if format == "markdown" else "html"
        media_type = "text/markdown" if format == "markdown" else "text/html"
        
        # Write content to temporary file
        with tempfile.NamedTemporaryFile(
            mode='w', 
            suffix=f'.{file_extension}', 
            delete=False,
            encoding='utf-8'
        ) as temp_file:
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        # Return file response
        filename = f"{job_result.results.get('service_name', 'documentation')}.{file_extension}"
        
        return FileResponse(
            path=temp_file_path,
            media_type=media_type,
            filename=filename,
            background=lambda: os.unlink(temp_file_path)  # Clean up temp file after response
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in download_documentation: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/jobs", response_model=List[JobStatusResponse])
async def list_jobs(
    team_id: Optional[str] = None,
    service_name: Optional[str] = None,
    limit: int = 50,
    _: None = Depends(rate_limit_check)
):
    """
    List jobs with optional filtering by team and service.
    
    Requirements: 3.4
    """
    try:
        if limit > 100:
            limit = 100  # Cap at 100 for performance
        
        job_results = await job_service.get_job_history(
            team_id=team_id,
            service_name=service_name,
            limit=limit
        )
        
        # Convert to response models
        responses = []
        for job_result in job_results:
            response = JobStatusResponse(
                job_id=str(job_result.job_id),
                status=job_result.status.value,
                created_at=job_result.created_at.isoformat(),
                completed_at=job_result.completed_at.isoformat() if job_result.completed_at else None,
                progress=job_result.progress.dict() if job_result.progress else None,
                results=job_result.results,
                error_message=job_result.error_message
            )
            responses.append(response)
        
        return responses
        
    except Exception as e:
        logger.error(f"Unexpected error in list_jobs: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/jobs/{job_id}")
async def cancel_job(
    job_id: str,
    _: None = Depends(rate_limit_check)
):
    """
    Cancel a running or queued job.
    
    Requirements: 2.4
    """
    try:
        # Parse job ID
        try:
            job_uuid = UUID(job_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid job ID format")
        
        # Cancel job
        success = await job_service.cancel_job(job_uuid)
        
        if not success:
            raise HTTPException(status_code=400, detail="Job could not be cancelled")
        
        return {"message": "Job cancelled successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in cancel_job: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/jobs/{job_id}/quality", response_model=Dict[str, Any])
async def get_job_quality_metrics(
    job_id: str,
    _: None = Depends(rate_limit_check)
):
    """
    Get detailed quality metrics for a completed job.
    
    Requirements: 3.4
    """
    try:
        # Parse job ID
        try:
            job_uuid = UUID(job_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid job ID format")
        
        # Get job status
        job_result = await job_service.get_job_status(job_uuid)
        
        if not job_result:
            raise HTTPException(status_code=404, detail="Job not found")
        
        if job_result.status.value != "completed":
            raise HTTPException(status_code=400, detail="Job is not completed")
        
        if not job_result.results or "quality_metrics" not in job_result.results:
            raise HTTPException(status_code=404, detail="Quality metrics not available")
        
        return job_result.results["quality_metrics"]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_job_quality_metrics: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Leaderboard and quality monitoring endpoints
@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(
    time_period: TimePeriod = TimePeriod.MONTH,
    team_filter: Optional[str] = None,
    service_type: Optional[ServiceType] = None,
    poor_quality_threshold: int = 60,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_check)
):
    """
    Get team leaderboard with rankings and poor quality services.
    
    Query Parameters:
    - time_period: "week", "month", or "quarter" (default: "month")
    - team_filter: Optional team ID to filter results
    - service_type: Optional service type filter ("openapi", "graphql", "json_schema")
    - poor_quality_threshold: Score threshold for poor quality identification (default: 60)
    
    Requirements: 4.1, 4.2, 4.4
    """
    try:
        # Create leaderboard service
        leaderboard_service = create_leaderboard_service(db)
        
        # Get leaderboard data
        leaderboard_data = leaderboard_service.get_leaderboard_data(
            time_period=time_period,
            team_filter=team_filter,
            service_type=service_type,
            poor_quality_threshold=poor_quality_threshold
        )
        
        # Convert to response model
        rankings = [
            TeamRankingResponse(
                team_id=ranking.team_id,
                team_name=ranking.team_name,
                average_score=ranking.average_score,
                total_docs=ranking.total_docs,
                trend=ranking.trend,
                rank=ranking.rank,
                last_updated=ranking.last_updated.isoformat()
            )
            for ranking in leaderboard_data.rankings
        ]
        
        poor_services = [
            PoorQualityServiceResponse(
                service_name=service.service_name,
                team_id=service.team_id,
                score=service.score,
                last_updated=service.last_updated.isoformat(),
                improvement_needed=service.improvement_needed
            )
            for service in leaderboard_data.poor_quality_services
        ]
        
        response = LeaderboardResponse(
            rankings=rankings,
            poor_quality_services=poor_services,
            generated_at=leaderboard_data.generated_at.isoformat(),
            time_period=leaderboard_data.time_period,
            filters_applied=leaderboard_data.filters_applied
        )
        
        logger.info(
            f"Leaderboard generated with {len(rankings)} teams and "
            f"{len(poor_services)} poor quality services"
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Unexpected error in get_leaderboard: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/leaderboard/teams/{team_id}")
async def get_team_details(
    team_id: str,
    time_period: TimePeriod = TimePeriod.MONTH,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_check)
):
    """
    Get detailed information for a specific team.
    
    Requirements: 4.1, 4.2
    """
    try:
        # Create leaderboard service
        leaderboard_service = create_leaderboard_service(db)
        
        # Get team-specific leaderboard data
        leaderboard_data = leaderboard_service.get_leaderboard_data(
            time_period=time_period,
            team_filter=team_id
        )
        
        if not leaderboard_data.rankings:
            raise HTTPException(status_code=404, detail="Team not found or no data available")
        
        team_ranking = leaderboard_data.rankings[0]
        
        # Get team's poor quality services
        team_poor_services = [
            service for service in leaderboard_data.poor_quality_services
            if service.team_id == team_id
        ]
        
        return {
            "team_id": team_ranking.team_id,
            "team_name": team_ranking.team_name,
            "ranking": {
                "average_score": team_ranking.average_score,
                "total_docs": team_ranking.total_docs,
                "trend": team_ranking.trend,
                "rank": team_ranking.rank,
                "last_updated": team_ranking.last_updated.isoformat()
            },
            "poor_quality_services": [
                {
                    "service_name": service.service_name,
                    "score": service.score,
                    "last_updated": service.last_updated.isoformat(),
                    "improvement_needed": service.improvement_needed
                }
                for service in team_poor_services
            ],
            "time_period": leaderboard_data.time_period
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_team_details: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/quality/alerts", response_model=List[QualityAlertResponse])
async def get_quality_alerts(
    time_period_days: int = 7,
    team_filter: Optional[str] = None,
    severity_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_check)
):
    """
    Get quality alerts for services needing attention.
    
    Query Parameters:
    - time_period_days: Number of days to analyze (default: 7)
    - team_filter: Optional team ID to filter alerts
    - severity_filter: Optional severity filter ("low", "medium", "high", "critical")
    
    Requirements: 4.3, 4.5
    """
    try:
        # Create quality monitor
        quality_monitor = create_quality_monitor(db)
        
        # Generate quality alerts
        alerts = quality_monitor.generate_quality_alerts(
            time_period_days=time_period_days,
            team_filter=team_filter
        )
        
        # Apply severity filter if specified
        if severity_filter:
            alerts = [
                alert for alert in alerts 
                if alert.severity.value == severity_filter
            ]
        
        # Convert to response models
        alert_responses = [
            QualityAlertResponse(
                service_name=alert.service_name,
                team_id=alert.team_id,
                current_score=alert.current_score,
                previous_score=alert.previous_score,
                severity=alert.severity.value,
                issues_identified=alert.issues_identified,
                recommended_actions=alert.recommended_actions,
                created_at=alert.created_at.isoformat(),
                alert_id=alert.alert_id
            )
            for alert in alerts
        ]
        
        logger.info(f"Generated {len(alert_responses)} quality alerts")
        
        return alert_responses
        
    except Exception as e:
        logger.error(f"Unexpected error in get_quality_alerts: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/quality/monitoring", response_model=QualityMonitoringResponse)
async def get_quality_monitoring_report(
    time_period_days: int = 1,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_check)
):
    """
    Get comprehensive quality monitoring report.
    
    Query Parameters:
    - time_period_days: Number of days to monitor (default: 1)
    
    Requirements: 4.3, 4.5
    """
    try:
        # Create quality monitor
        quality_monitor = create_quality_monitor(db)
        
        # Generate monitoring report
        report = quality_monitor.monitor_quality_changes(
            time_period_days=time_period_days
        )
        
        # Convert alerts to response models
        alert_responses = [
            QualityAlertResponse(
                service_name=alert.service_name,
                team_id=alert.team_id,
                current_score=alert.current_score,
                previous_score=alert.previous_score,
                severity=alert.severity.value,
                issues_identified=alert.issues_identified,
                recommended_actions=alert.recommended_actions,
                created_at=alert.created_at.isoformat(),
                alert_id=alert.alert_id
            )
            for alert in report.alerts_generated
        ]
        
        response = QualityMonitoringResponse(
            total_services_monitored=report.total_services_monitored,
            poor_quality_count=report.poor_quality_count,
            alerts_generated=alert_responses,
            trend_analysis=report.trend_analysis,
            recommendations=report.recommendations,
            generated_at=report.generated_at.isoformat()
        )
        
        logger.info(
            f"Quality monitoring report generated: {report.total_services_monitored} services, "
            f"{report.poor_quality_count} poor quality, {len(alert_responses)} alerts"
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Unexpected error in get_quality_monitoring_report: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/quality/trigger-update")
async def trigger_leaderboard_update(
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_check)
):
    """
    Manually trigger leaderboard update.
    
    Requirements: 4.5
    """
    try:
        # Create quality monitor
        quality_monitor = create_quality_monitor(db)
        
        # Trigger update
        success = quality_monitor.trigger_leaderboard_update()
        
        if success:
            return {"message": "Leaderboard update triggered successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to trigger leaderboard update")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in trigger_leaderboard_update: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Health check and system status endpoints
@router.get("/health")
async def health_check():
    """
    Comprehensive health check endpoint.
    
    Requirements: 5.5
    """
    try:
        # Get health status from job service
        health_status = await job_service.health_check()
        
        # Add API-specific health checks
        health_status["api_healthy"] = True
        health_status["rate_limiter_healthy"] = rate_limiter.redis_client is not None
        
        # Determine overall health
        overall_healthy = (
            health_status.get("healthy", False) and
            health_status.get("api_healthy", False)
        )
        
        status_code = 200 if overall_healthy else 503
        
        return health_status
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "healthy": False,
            "api_healthy": False,
            "error": str(e),
            "timestamp": "error"
        }


@router.get("/health/detailed")
async def detailed_health_check():
    """
    Detailed health check with component status.
    
    Requirements: 5.5
    """
    try:
        # Get comprehensive health status
        health_status = await job_service.health_check()
        
        # Add detailed component checks
        components = {
            "api": {"healthy": True, "message": "API endpoints operational"},
            "rate_limiter": {
                "healthy": rate_limiter.redis_client is not None,
                "message": "Rate limiter operational" if rate_limiter.redis_client else "Rate limiter Redis unavailable"
            },
            "job_queue": {
                "healthy": health_status.get("redis_healthy", False),
                "message": "Job queue operational" if health_status.get("redis_healthy") else "Job queue Redis unavailable"
            },
            "database": {
                "healthy": health_status.get("database_healthy", False),
                "message": "Database operational" if health_status.get("database_healthy") else "Database unavailable"
            }
        }
        
        # Add queue status
        queue_status = health_status.get("queue_status", {})
        
        return {
            "overall_healthy": health_status.get("healthy", False),
            "components": components,
            "queue_status": queue_status,
            "timestamp": health_status.get("timestamp")
        }
        
    except Exception as e:
        logger.error(f"Detailed health check failed: {e}")
        return {
            "overall_healthy": False,
            "error": str(e),
            "timestamp": "error"
        }


@router.get("/rate-limit/status")
async def get_rate_limit_status(request: Request):
    """
    Get current rate limit status for the client.
    
    Requirements: 5.3
    """
    try:
        status = await rate_limiter.get_rate_limit_status(request)
        return status
        
    except Exception as e:
        logger.error(f"Failed to get rate limit status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/system/stats")
async def get_system_statistics():
    """
    Get system-wide statistics and metrics.
    
    Requirements: 5.5
    """
    try:
        # Get queue status
        queue_status = await job_service.get_queue_status()
        
        # Get job statistics
        job_stats = await job_service.get_job_statistics(days=7)
        
        # Get active jobs
        active_jobs = await job_service.get_active_jobs()
        
        return {
            "queue_status": queue_status,
            "job_statistics": job_stats,
            "active_jobs_count": len(active_jobs),
            "system_load": {
                "active_jobs": len([j for j in active_jobs if j.status.value == "processing"]),
                "queued_jobs": len([j for j in active_jobs if j.status.value == "queued"])
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get system statistics: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
