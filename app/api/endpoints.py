"""
REST API endpoints for the Spec Documentation API.
"""
import logging
from typing import Optional, Dict, Any, List
from uuid import UUID
import json
import tempfile
import os
from datetime import datetime

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
from app.services.file_handler import get_file_handler, ProcessedFile
from app.services.resource_manager import get_resource_manager
from app.services.file_error_handler import get_file_error_handler
from app.db.database import get_db
from app.core.exceptions import (
    ValidationError, 
    SpecificationError, 
    JobProcessingError,
    RateLimitError,
    ErrorContext,
    create_error_response
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
    Generate documentation from uploaded file with enhanced error handling and streaming processing.
    
    Requirements: 4.1, 4.2, 4.4, 4.5
    """
    correlation_id = getattr(request.state, 'correlation_id', None)
    
    with ErrorContext("generate_documentation_from_file", 
                     method=request.method, 
                     path=str(request.url.path)):
        
        # Get service instances
        file_handler = get_file_handler()
        resource_manager = get_resource_manager()
        error_handler = get_file_error_handler()
        
        # Track resource usage for this operation
        async with resource_manager.track_operation("file_upload_processing") as tracker:
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
                            raise ValidationError(
                                message=f"Invalid output_formats. Expected JSON array like [\"markdown\", \"html\"] or comma-separated string like \"markdown,html\"",
                                field="output_formats",
                                details={
                                    "provided_value": output_formats,
                                    "expected_formats": ["markdown", "html"],
                                    "error": str(e)
                                }
                            )
                    except ValueError as e:
                        raise ValidationError(
                            message="Invalid output format value",
                            field="output_formats",
                            details={
                                "provided_value": output_formats,
                                "error": str(e),
                                "valid_formats": ["markdown", "html"]
                            }
                        )
                
                # Process file with robust handler (streaming, validation, etc.)
                try:
                    processed_file: ProcessedFile = await file_handler.process_upload_stream(specification_file)
                    
                    # Register temp files with resource tracker
                    for temp_file in processed_file.temp_files:
                        tracker.add_temp_file(temp_file)
                    
                    logger.info(
                        f"File processed successfully: {processed_file.file_info.filename}, "
                        f"size: {processed_file.file_info.size} bytes, "
                        f"format: {processed_file.detected_format}"
                    )
                    
                except Exception as e:
                    # Handle file processing errors with detailed error responses
                    if isinstance(e, SpecificationError):
                        error_response = error_handler.handle_specification_error(e, correlation_id)
                        raise HTTPException(
                            status_code=422,
                            detail=error_response.dict()
                        )
                    else:
                        error_response = error_handler.handle_file_validation_error(
                            e, 
                            specification_file.filename,
                            correlation_id
                        )
                        raise HTTPException(
                            status_code=400,
                            detail=error_response.dict()
                        )
                
                # Create job request using processed file data
                from app.validators.validators import SpecFormat
                spec_format = SpecFormat(processed_file.detected_format)
                
                job_request = JobRequest(
                    specification=processed_file.content,
                    spec_format=spec_format,
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
                
                # Log successful processing with resource metrics
                memory_info = file_handler.get_memory_usage_info()
                logger.info(
                    f"Documentation generation job {job_result.job_id} submitted successfully from file. "
                    f"Memory usage: {memory_info.get('rss_mb', 0):.1f}MB, "
                    f"Temp files: {memory_info.get('temp_files_count', 0)}"
                )
                
                return response
                
            except (ValidationError, SpecificationError, JobProcessingError):
                raise
            except HTTPException:
                raise
            except Exception as e:
                # Handle unexpected errors with resource context
                resource_info = resource_manager.get_system_resource_info()
                error_response = error_handler.handle_resource_error(e, resource_info, correlation_id)
                
                logger.error(
                    f"Unexpected error in generate_documentation_from_file: {e}. "
                    f"Resource info: {resource_info}",
                    exc_info=True
                )
                
                raise HTTPException(
                    status_code=500,
                    detail=error_response.dict()
                )

@router.post("/generate-docs/url", response_model=JobStatusResponse)
async def generate_documentation_from_url(
    request: Request,
    json_request: SpecificationURLRequest,
    _: None = Depends(rate_limit_check)
):
    """
    Generate documentation from URL reference with enhanced error handling.
    
    Requirements: 1.1, 1.2, 4.5
    """
    correlation_id = getattr(request.state, 'correlation_id', None)
    
    with ErrorContext("generate_documentation_from_url", 
                     method=request.method, 
                     path=str(request.url.path)):
        
        # Get service instances for resource management
        resource_manager = get_resource_manager()
        
        # Track resource usage for this operation
        async with resource_manager.track_operation("url_processing") as tracker:
            try:
                # Fetch specification from URL with enhanced error handling
                try:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        response = await client.get(json_request.specification_url)
                        response.raise_for_status()
                        spec_content = response.text
                        
                        # Track content size for resource monitoring
                        content_size = len(spec_content.encode('utf-8'))
                        tracker.add_metric("content_size_bytes", content_size)
                        
                        logger.info(
                            f"Successfully fetched specification from URL: {json_request.specification_url}, "
                            f"size: {content_size} bytes"
                        )
                        
                except httpx.TimeoutException as e:
                    raise ValidationError(
                        message="Timeout while fetching specification from URL",
                        field="specification_url",
                        details={
                            "url": json_request.specification_url,
                            "timeout_seconds": 30,
                            "error": str(e),
                            "retry_guidance": "The URL took too long to respond. Try again or check if the URL is accessible.",
                            "suggested_action": "Verify the URL is correct and the server is responsive"
                        }
                    )
                except httpx.RequestError as e:
                    raise ValidationError(
                        message="Failed to fetch specification from URL",
                        field="specification_url",
                        details={
                            "url": json_request.specification_url,
                            "error": str(e),
                            "error_type": type(e).__name__,
                            "retry_guidance": "Verify the URL is accessible and try again",
                            "suggested_action": "Check network connectivity and URL validity"
                        }
                    )
                except httpx.HTTPStatusError as e:
                    # Provide specific guidance based on HTTP status code
                    retry_guidance = "Check if the URL is correct and accessible"
                    suggested_action = "Verify the URL and try again"
                    
                    if e.response.status_code == 404:
                        retry_guidance = "The specification file was not found at the provided URL"
                        suggested_action = "Verify the URL path is correct"
                    elif e.response.status_code == 403:
                        retry_guidance = "Access to the specification file is forbidden"
                        suggested_action = "Check if authentication is required or if the file is publicly accessible"
                    elif e.response.status_code >= 500:
                        retry_guidance = "The server is experiencing issues"
                        suggested_action = "Try again later or contact the server administrator"
                    
                    raise ValidationError(
                        message=f"HTTP {e.response.status_code} error fetching specification from URL",
                        field="specification_url",
                        details={
                            "url": json_request.specification_url,
                            "status_code": e.response.status_code,
                            "error": str(e),
                            "retry_guidance": retry_guidance,
                            "suggested_action": suggested_action
                        }
                    )
                
                # Detect format with enhanced error handling
                try:
                    format_detector = FormatDetector()
                    detected_format = format_detector.detect_format(
                        content=spec_content,
                        url=json_request.specification_url
                    )
                    
                    if not detected_format:
                        raise SpecificationError(
                            message="Unable to detect specification format from URL content",
                            details={
                                "url": json_request.specification_url,
                                "content_preview": spec_content[:200] + "..." if len(spec_content) > 200 else spec_content,
                                "supported_formats": ["OpenAPI", "GraphQL", "JSON Schema"],
                                "retry_guidance": "Ensure the URL returns a valid specification file",
                                "suggested_action": "Verify the file format is supported (OpenAPI, GraphQL, or JSON Schema)"
                            }
                        )
                    
                    logger.info(f"Detected format: {detected_format.value} for URL: {json_request.specification_url}")
                    
                except Exception as e:
                    raise SpecificationError(
                        message="Error during format detection",
                        details={
                            "url": json_request.specification_url,
                            "error": str(e),
                            "retry_guidance": "The content may not be a valid specification file",
                            "suggested_action": "Verify the URL points to a valid OpenAPI, GraphQL, or JSON Schema file"
                        }
                    )
                
                # Validate specification with enhanced error handling
                try:
                    validator = SpecificationValidator()
                    validation_result = validator.validate_specification(
                        content=spec_content,
                        spec_format=detected_format
                    )
                    
                    if not validation_result.is_valid:
                        raise SpecificationError(
                            message="Specification validation failed",
                            spec_format=detected_format.value,
                            details={
                                "url": json_request.specification_url,
                                "validation_errors": validation_result.errors[:10],  # Limit to first 10 errors
                                "total_errors": len(validation_result.errors),
                                "retry_guidance": "Fix the specification errors and try again",
                                "suggested_action": "Review and correct the specification file at the provided URL"
                            }
                        )
                    
                    logger.info(f"Specification validation passed for URL: {json_request.specification_url}")
                    
                except SpecificationError:
                    raise
                except Exception as e:
                    raise SpecificationError(
                        message="Error during specification validation",
                        spec_format=detected_format.value if detected_format else "unknown",
                        details={
                            "url": json_request.specification_url,
                            "error": str(e),
                            "retry_guidance": "The specification file may be corrupted or invalid",
                            "suggested_action": "Verify the specification file is valid and accessible"
                        }
                    )
                
                # Create job request
                job_request = JobRequest(
                    specification=spec_content,
                    spec_format=detected_format,
                    output_formats=json_request.output_formats,
                    team_id=json_request.team_id,
                    service_name=json_request.service_name
                )
                
                # Submit job with enhanced error handling
                try:
                    job_result = await job_service.submit_documentation_job(job_request)
                    
                    logger.info(
                        f"Documentation generation job {job_result.job_id} submitted successfully from URL. "
                        f"Team: {json_request.team_id}, Service: {json_request.service_name}"
                    )
                    
                except Exception as e:
                    raise JobProcessingError(
                        message="Failed to submit documentation generation job",
                        details={
                            "url": json_request.specification_url,
                            "team_id": json_request.team_id,
                            "service_name": json_request.service_name,
                            "error": str(e),
                            "retry_guidance": "The job service may be temporarily unavailable",
                            "suggested_action": "Try again in a few moments"
                        }
                    )
                
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
                
            except (ValidationError, SpecificationError, JobProcessingError):
                raise
            except HTTPException:
                raise
            except Exception as e:
                # Handle unexpected errors with resource context
                resource_info = resource_manager.get_system_resource_info()
                
                logger.error(
                    f"Unexpected error in generate_documentation_from_url: {e}. "
                    f"URL: {json_request.specification_url}, Resource info: {resource_info}",
                    exc_info=True
                )
                
                raise HTTPException(
                    status_code=500,
                    detail=create_error_response(
                        SpecDocumentationAPIError(
                            message="Internal server error during URL processing",
                            error_code="URL_PROCESSING_ERROR",
                            details={
                                "url": json_request.specification_url,
                                "resource_info": resource_info,
                                "retry_guidance": "This appears to be a temporary server issue",
                                "suggested_action": "Try again in a few moments"
                            }
                        ),
                        status_code=500,
                        request=request,
                        correlation_id=correlation_id
                    ).body
                )


@router.post("/generate-docs/json", response_model=JobStatusResponse)
async def generate_documentation_from_json(
    request: Request,
    json_request: SpecificationJSONRequest,
    _: None = Depends(rate_limit_check)
):
    """
    Generate documentation from direct JSON payload with enhanced error handling.
    
    Requirements: 1.1, 1.2, 4.5
    """
    correlation_id = getattr(request.state, 'correlation_id', None)
    
    with ErrorContext("generate_documentation_from_json", 
                     method=request.method, 
                     path=str(request.url.path)):
        
        # Get service instances for resource management
        resource_manager = get_resource_manager()
        
        # Track resource usage for this operation
        async with resource_manager.track_operation("json_processing") as tracker:
            try:
                # Prepare specification content for validation
                try:
                    if isinstance(json_request.specification, dict):
                        spec_content = json.dumps(json_request.specification)
                        content_size = len(spec_content.encode('utf-8'))
                    else:
                        spec_content = json_request.specification
                        content_size = len(str(spec_content).encode('utf-8'))
                    
                    # Track content size for resource monitoring
                    tracker.add_metric("content_size_bytes", content_size)
                    
                    logger.info(
                        f"Processing JSON specification: format={json_request.spec_format.value}, "
                        f"size={content_size} bytes, team={json_request.team_id}, "
                        f"service={json_request.service_name}"
                    )
                    
                except Exception as e:
                    raise ValidationError(
                        message="Failed to process specification content",
                        field="specification",
                        details={
                            "error": str(e),
                            "spec_format": json_request.spec_format.value,
                            "retry_guidance": "Ensure the specification is valid JSON",
                            "suggested_action": "Verify the specification format and content"
                        }
                    )
                
                # Validate specification with enhanced error handling
                try:
                    validator = SpecificationValidator()
                    validation_result = validator.validate_specification(
                        content=spec_content,
                        spec_format=json_request.spec_format
                    )
                    
                    if not validation_result.is_valid:
                        raise SpecificationError(
                            message="Specification validation failed",
                            spec_format=json_request.spec_format.value,
                            details={
                                "validation_errors": validation_result.errors[:10],  # Limit to first 10 errors
                                "total_errors": len(validation_result.errors),
                                "spec_format": json_request.spec_format.value,
                                "retry_guidance": "Fix the specification errors and try again",
                                "suggested_action": f"Review and correct the {json_request.spec_format.value} specification"
                            }
                        )
                    
                    logger.info(f"Specification validation passed for {json_request.spec_format.value} format")
                    
                except SpecificationError:
                    raise
                except Exception as e:
                    raise SpecificationError(
                        message="Error during specification validation",
                        spec_format=json_request.spec_format.value,
                        details={
                            "error": str(e),
                            "spec_format": json_request.spec_format.value,
                            "retry_guidance": "The specification may be corrupted or invalid",
                            "suggested_action": f"Verify the {json_request.spec_format.value} specification is valid"
                        }
                    )
                
                # Validate output formats
                try:
                    if not json_request.output_formats:
                        json_request.output_formats = [OutputFormat.MARKDOWN]  # Default format
                    
                    # Ensure all output formats are valid
                    for output_format in json_request.output_formats:
                        if not isinstance(output_format, OutputFormat):
                            raise ValidationError(
                                message="Invalid output format specified",
                                field="output_formats",
                                details={
                                    "invalid_format": str(output_format),
                                    "valid_formats": [f.value for f in OutputFormat],
                                    "retry_guidance": "Use valid output format values",
                                    "suggested_action": "Choose from supported output formats"
                                }
                            )
                    
                    logger.info(f"Output formats validated: {[f.value for f in json_request.output_formats]}")
                    
                except ValidationError:
                    raise
                except Exception as e:
                    raise ValidationError(
                        message="Error validating output formats",
                        field="output_formats",
                        details={
                            "error": str(e),
                            "retry_guidance": "Check the output_formats field",
                            "suggested_action": "Ensure output_formats is a valid array"
                        }
                    )
                
                # Create job request
                job_request = JobRequest(
                    specification=json_request.specification,
                    spec_format=json_request.spec_format,
                    output_formats=json_request.output_formats,
                    team_id=json_request.team_id,
                    service_name=json_request.service_name
                )
                
                # Submit job with enhanced error handling
                try:
                    job_result = await job_service.submit_documentation_job(job_request)
                    
                    logger.info(
                        f"Documentation generation job {job_result.job_id} submitted successfully from JSON. "
                        f"Format: {json_request.spec_format.value}, Team: {json_request.team_id}, "
                        f"Service: {json_request.service_name}"
                    )
                    
                except Exception as e:
                    raise JobProcessingError(
                        message="Failed to submit documentation generation job",
                        details={
                            "spec_format": json_request.spec_format.value,
                            "team_id": json_request.team_id,
                            "service_name": json_request.service_name,
                            "error": str(e),
                            "retry_guidance": "The job service may be temporarily unavailable",
                            "suggested_action": "Try again in a few moments"
                        }
                    )
                
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
                
            except (ValidationError, SpecificationError, JobProcessingError):
                raise
            except HTTPException:
                raise
            except Exception as e:
                # Handle unexpected errors with resource context
                resource_info = resource_manager.get_system_resource_info()
                
                logger.error(
                    f"Unexpected error in generate_documentation_from_json: {e}. "
                    f"Format: {json_request.spec_format.value}, Resource info: {resource_info}",
                    exc_info=True
                )
                
                raise HTTPException(
                    status_code=500,
                    detail=create_error_response(
                        SpecDocumentationAPIError(
                            message="Internal server error during JSON processing",
                            error_code="JSON_PROCESSING_ERROR",
                            details={
                                "spec_format": json_request.spec_format.value,
                                "resource_info": resource_info,
                                "retry_guidance": "This appears to be a temporary server issue",
                                "suggested_action": "Try again in a few moments"
                            }
                        ),
                        status_code=500,
                        request=request,
                        correlation_id=correlation_id
                    ).body
                )

@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    request: Request,
    job_id: str,
    _: None = Depends(rate_limit_check)
):
    """
    Get the status and results of a documentation generation job with enhanced error handling.
    
    Requirements: 1.2, 2.1, 3.1
    """
    correlation_id = getattr(request.state, 'correlation_id', None)
    
    with ErrorContext("get_job_status", 
                     method=request.method, 
                     path=str(request.url.path),
                     job_id=job_id):
        try:
            # Parse and validate job ID
            try:
                job_uuid = UUID(job_id)
                logger.info(f"Getting status for job: {job_id}")
            except ValueError as e:
                raise ValidationError(
                    message="Invalid job ID format",
                    field="job_id",
                    details={
                        "provided_value": job_id,
                        "expected_format": "UUID (e.g., 123e4567-e89b-12d3-a456-426614174000)",
                        "error": str(e),
                        "retry_guidance": "Provide a valid UUID format for the job ID",
                        "suggested_action": "Check the job ID format and ensure it's a valid UUID"
                    }
                )
            
            # Get job status with enhanced error handling
            try:
                job_result = await job_service.get_job_status(job_uuid)
            except Exception as e:
                logger.error(f"Error retrieving job status for {job_id}: {e}", exc_info=True)
                raise JobProcessingError(
                    message="Failed to retrieve job status",
                    job_id=job_id,
                    details={
                        "error": str(e),
                        "retry_guidance": "The job service may be temporarily unavailable",
                        "suggested_action": "Try again in a few moments"
                    }
                )
            
            if not job_result:
                raise JobProcessingError(
                    message="Job not found",
                    job_id=job_id,
                    details={
                        "retry_guidance": "Verify the job ID is correct and the job exists",
                        "suggested_action": "Check if the job ID was copied correctly or if the job has been deleted"
                    }
                )
            
            # Convert to response model with error context
            try:
                response = JobStatusResponse(
                    job_id=str(job_result.job_id),
                    status=job_result.status.value,
                    created_at=job_result.created_at.isoformat(),
                    completed_at=job_result.completed_at.isoformat() if job_result.completed_at else None,
                    progress=job_result.progress.dict() if job_result.progress else None,
                    results=job_result.results,
                    error_message=job_result.error_message
                )
                
                logger.info(
                    f"Job status retrieved successfully: {job_id}, status: {job_result.status.value}"
                )
                
                return response
                
            except Exception as e:
                logger.error(f"Error converting job result to response: {e}", exc_info=True)
                raise JobProcessingError(
                    message="Error formatting job status response",
                    job_id=job_id,
                    details={
                        "error": str(e),
                        "retry_guidance": "This appears to be a temporary formatting issue",
                        "suggested_action": "Try again in a few moments"
                    }
                )
            
        except (ValidationError, JobProcessingError):
            raise
        except Exception as e:
            logger.error(f"Unexpected error in get_job_status for {job_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=create_error_response(
                    JobProcessingError(
                        message="Internal server error while retrieving job status",
                        job_id=job_id,
                        details={
                            "error": str(e),
                            "retry_guidance": "This appears to be a temporary server issue",
                            "suggested_action": "Try again in a few moments"
                        }
                    ),
                    status_code=500,
                    request=request,
                    correlation_id=correlation_id
                ).body
            )


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
            raise ValidationError(
                message="Invalid job ID format",
                field="job_id",
                details={
                    "provided_value": job_id,
                    "expected_format": "UUID (e.g., 123e4567-e89b-12d3-a456-426614174000)",
                    "retry_guidance": "Provide a valid UUID format for the job ID"
                }
            )
        
        # Validate format
        if format not in ["markdown", "html"]:
            raise ValidationError(
                message="Invalid format specified",
                field="format",
                details={
                    "provided_value": format,
                    "valid_formats": ["markdown", "html"],
                    "retry_guidance": "Use 'markdown' or 'html' as the format parameter"
                }
            )
        
        # Get job status
        job_result = await job_service.get_job_status(job_uuid)
        
        if not job_result:
            raise JobProcessingError(
                message="Job not found",
                job_id=job_id,
                details={
                    "retry_guidance": "Verify the job ID is correct and the job exists"
                }
            )
        
        if job_result.status.value != "completed":
            raise JobProcessingError(
                message="Job is not completed",
                job_id=job_id,
                details={
                    "current_status": job_result.status.value,
                    "retry_guidance": "Wait for the job to complete before downloading results"
                }
            )
        
        if not job_result.results:
            raise JobProcessingError(
                message="No results available for this job",
                job_id=job_id,
                details={
                    "retry_guidance": "The job may have failed or not produced results"
                }
            )
        
        # Get file content from results
        content_key = f"{format}_content"
        if content_key not in job_result.results:
            raise JobProcessingError(
                message=f"{format.title()} format not available",
                job_id=job_id,
                details={
                    "requested_format": format,
                    "available_formats": [key.replace("_content", "") for key in job_result.results.keys() if key.endswith("_content")],
                    "retry_guidance": "Try downloading in an available format"
                }
            )
        
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
        
    except (ValidationError, JobProcessingError):
        raise
    except Exception as e:
        logger.error(f"Unexpected error in download_documentation: {e}", exc_info=True)
        raise


@router.get("/jobs", response_model=List[JobStatusResponse])
async def list_jobs(
    request: Request,
    team_id: Optional[str] = None,
    service_name: Optional[str] = None,
    limit: int = 50,
    _: None = Depends(rate_limit_check)
):
    """
    List jobs with optional filtering by team and service with enhanced error handling.
    
    Requirements: 1.2, 2.1, 3.1
    """
    correlation_id = getattr(request.state, 'correlation_id', None)
    
    with ErrorContext("list_jobs", 
                     method=request.method, 
                     path=str(request.url.path),
                     team_id=team_id,
                     service_name=service_name,
                     limit=limit):
        try:
            # Validate and sanitize parameters
            try:
                # Validate limit parameter
                if limit < 1:
                    raise ValidationError(
                        message="Limit must be a positive integer",
                        field="limit",
                        details={
                            "provided_value": limit,
                            "minimum_value": 1,
                            "retry_guidance": "Provide a positive integer for the limit parameter",
                            "suggested_action": "Use a limit value between 1 and 100"
                        }
                    )
                
                if limit > 100:
                    limit = 100  # Cap at 100 for performance
                    logger.info(f"Limit capped at 100 for performance (requested: {limit})")
                
                # Validate team_id if provided
                if team_id and len(team_id.strip()) == 0:
                    raise ValidationError(
                        message="Team ID cannot be empty",
                        field="team_id",
                        details={
                            "retry_guidance": "Provide a valid team ID or omit the parameter",
                            "suggested_action": "Use a non-empty team ID or remove the filter"
                        }
                    )
                
                # Validate service_name if provided
                if service_name and len(service_name.strip()) == 0:
                    raise ValidationError(
                        message="Service name cannot be empty",
                        field="service_name",
                        details={
                            "retry_guidance": "Provide a valid service name or omit the parameter",
                            "suggested_action": "Use a non-empty service name or remove the filter"
                        }
                    )
                
                logger.info(
                    f"Listing jobs with filters - team_id: {team_id}, "
                    f"service_name: {service_name}, limit: {limit}"
                )
                
            except ValidationError:
                raise
            except Exception as e:
                raise ValidationError(
                    message="Error validating request parameters",
                    details={
                        "error": str(e),
                        "retry_guidance": "Check the request parameters",
                        "suggested_action": "Verify all parameters are valid"
                    }
                )
            
            # Get job history with enhanced error handling
            try:
                job_results = await job_service.get_job_history(
                    team_id=team_id,
                    service_name=service_name,
                    limit=limit
                )
                
                logger.info(f"Retrieved {len(job_results)} jobs from history")
                
            except Exception as e:
                logger.error(f"Error retrieving job history: {e}", exc_info=True)
                raise JobProcessingError(
                    message="Failed to retrieve job history",
                    details={
                        "error": str(e),
                        "filters": {
                            "team_id": team_id,
                            "service_name": service_name,
                            "limit": limit
                        },
                        "retry_guidance": "The job service may be temporarily unavailable",
                        "suggested_action": "Try again in a few moments"
                    }
                )
            
            # Convert to response models with error handling
            try:
                responses = []
                for job_result in job_results:
                    try:
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
                    except Exception as e:
                        logger.warning(
                            f"Error converting job {job_result.job_id} to response format: {e}",
                            exc_info=True
                        )
                        # Continue with other jobs instead of failing completely
                        continue
                
                logger.info(f"Successfully converted {len(responses)} jobs to response format")
                return responses
                
            except Exception as e:
                logger.error(f"Error converting job results to response format: {e}", exc_info=True)
                raise JobProcessingError(
                    message="Error formatting job list response",
                    details={
                        "error": str(e),
                        "retry_guidance": "This appears to be a temporary formatting issue",
                        "suggested_action": "Try again in a few moments"
                    }
                )
            
        except (ValidationError, JobProcessingError):
            raise
        except Exception as e:
            logger.error(f"Unexpected error in list_jobs: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=create_error_response(
                    JobProcessingError(
                        message="Internal server error while listing jobs",
                        details={
                            "error": str(e),
                            "filters": {
                                "team_id": team_id,
                                "service_name": service_name,
                                "limit": limit
                            },
                            "retry_guidance": "This appears to be a temporary server issue",
                            "suggested_action": "Try again in a few moments"
                        }
                    ),
                    status_code=500,
                    request=request,
                    correlation_id=correlation_id
                ).body
            )


@router.delete("/jobs/{job_id}")
async def cancel_job(
    request: Request,
    job_id: str,
    _: None = Depends(rate_limit_check)
):
    """
    Cancel a running or queued job with enhanced error handling.
    
    Requirements: 1.2, 2.1, 3.1
    """
    correlation_id = getattr(request.state, 'correlation_id', None)
    
    with ErrorContext("cancel_job", 
                     method=request.method, 
                     path=str(request.url.path),
                     job_id=job_id):
        try:
            # Parse and validate job ID
            try:
                job_uuid = UUID(job_id)
                logger.info(f"Attempting to cancel job: {job_id}")
            except ValueError as e:
                raise ValidationError(
                    message="Invalid job ID format",
                    field="job_id",
                    details={
                        "provided_value": job_id,
                        "expected_format": "UUID (e.g., 123e4567-e89b-12d3-a456-426614174000)",
                        "error": str(e),
                        "retry_guidance": "Provide a valid UUID format for the job ID",
                        "suggested_action": "Check the job ID format and ensure it's a valid UUID"
                    }
                )
            
            # Check if job exists before attempting cancellation
            try:
                job_result = await job_service.get_job_status(job_uuid)
                if not job_result:
                    raise JobProcessingError(
                        message="Job not found",
                        job_id=job_id,
                        details={
                            "retry_guidance": "Verify the job ID is correct and the job exists",
                            "suggested_action": "Check if the job ID was copied correctly"
                        }
                    )
                
                # Check if job is in a cancellable state
                if job_result.status.value in ["completed", "failed", "cancelled"]:
                    raise JobProcessingError(
                        message=f"Job cannot be cancelled - current status: {job_result.status.value}",
                        job_id=job_id,
                        details={
                            "current_status": job_result.status.value,
                            "retry_guidance": "Only queued or processing jobs can be cancelled",
                            "suggested_action": "Check the job status before attempting cancellation"
                        }
                    )
                
                logger.info(f"Job {job_id} is in {job_result.status.value} status, proceeding with cancellation")
                
            except JobProcessingError:
                raise
            except Exception as e:
                logger.error(f"Error checking job status before cancellation: {e}", exc_info=True)
                raise JobProcessingError(
                    message="Failed to verify job status before cancellation",
                    job_id=job_id,
                    details={
                        "error": str(e),
                        "retry_guidance": "The job service may be temporarily unavailable",
                        "suggested_action": "Try again in a few moments"
                    }
                )
            
            # Attempt to cancel job
            try:
                success = await job_service.cancel_job(job_uuid)
                
                if not success:
                    raise JobProcessingError(
                        message="Job could not be cancelled",
                        job_id=job_id,
                        details={
                            "retry_guidance": "The job may have already completed or been cancelled",
                            "suggested_action": "Check the current job status"
                        }
                    )
                
                logger.info(f"Job {job_id} cancelled successfully")
                
                return {
                    "message": "Job cancelled successfully",
                    "job_id": job_id,
                    "timestamp": datetime.utcnow().isoformat()
                }
                
            except JobProcessingError:
                raise
            except Exception as e:
                logger.error(f"Error during job cancellation: {e}", exc_info=True)
                raise JobProcessingError(
                    message="Failed to cancel job",
                    job_id=job_id,
                    details={
                        "error": str(e),
                        "retry_guidance": "The job service may be experiencing issues",
                        "suggested_action": "Try again in a few moments"
                    }
                )
            
        except (ValidationError, JobProcessingError):
            raise
        except Exception as e:
            logger.error(f"Unexpected error in cancel_job for {job_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=create_error_response(
                    JobProcessingError(
                        message="Internal server error while cancelling job",
                        job_id=job_id,
                        details={
                            "error": str(e),
                            "retry_guidance": "This appears to be a temporary server issue",
                            "suggested_action": "Try again in a few moments"
                        }
                    ),
                    status_code=500,
                    request=request,
                    correlation_id=correlation_id
                ).body
            )


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
            raise ValidationError(
                message="Invalid job ID format",
                field="job_id",
                details={
                    "provided_value": job_id,
                    "expected_format": "UUID (e.g., 123e4567-e89b-12d3-a456-426614174000)",
                    "retry_guidance": "Provide a valid UUID format for the job ID"
                }
            )
        
        # Get job status
        job_result = await job_service.get_job_status(job_uuid)
        
        if not job_result:
            raise JobProcessingError(
                message="Job not found",
                job_id=job_id,
                details={
                    "retry_guidance": "Verify the job ID is correct and the job exists"
                }
            )
        
        if job_result.status.value != "completed":
            raise JobProcessingError(
                message="Job is not completed",
                job_id=job_id,
                details={
                    "current_status": job_result.status.value,
                    "retry_guidance": "Wait for the job to complete before accessing quality metrics"
                }
            )
        
        if not job_result.results or "quality_metrics" not in job_result.results:
            raise JobProcessingError(
                message="Quality metrics not available for this job",
                job_id=job_id,
                details={
                    "retry_guidance": "Quality metrics may not have been generated for this job"
                }
            )
        
        return job_result.results["quality_metrics"]
        
    except (ValidationError, JobProcessingError):
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_job_quality_metrics: {e}", exc_info=True)
        raise


# Leaderboard and quality monitoring endpoints
@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(
    request: Request,
    time_period: TimePeriod = TimePeriod.MONTH,
    team_filter: Optional[str] = None,
    service_type: Optional[ServiceType] = None,
    poor_quality_threshold: int = 60,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_check)
):
    """
    Get team leaderboard with rankings and poor quality services with enhanced error handling.
    
    Query Parameters:
    - time_period: "week", "month", or "quarter" (default: "month")
    - team_filter: Optional team ID to filter results
    - service_type: Optional service type filter ("openapi", "graphql", "json_schema")
    - poor_quality_threshold: Score threshold for poor quality identification (default: 60)
    
    Requirements: 2.1, 3.1, 5.1
    """
    correlation_id = getattr(request.state, 'correlation_id', None)
    
    with ErrorContext("get_leaderboard", 
                     method=request.method, 
                     path=str(request.url.path),
                     time_period=time_period.value,
                     team_filter=team_filter,
                     service_type=service_type.value if service_type else None,
                     poor_quality_threshold=poor_quality_threshold):
        try:
            # Validate parameters
            try:
                # Validate poor_quality_threshold
                if poor_quality_threshold < 0 or poor_quality_threshold > 100:
                    raise ValidationError(
                        message="Poor quality threshold must be between 0 and 100",
                        field="poor_quality_threshold",
                        details={
                            "provided_value": poor_quality_threshold,
                            "valid_range": "0-100",
                            "retry_guidance": "Provide a threshold value between 0 and 100",
                            "suggested_action": "Use a value like 60 for moderate quality threshold"
                        }
                    )
                
                # Validate team_filter if provided
                if team_filter and len(team_filter.strip()) == 0:
                    raise ValidationError(
                        message="Team filter cannot be empty",
                        field="team_filter",
                        details={
                            "retry_guidance": "Provide a valid team ID or omit the parameter",
                            "suggested_action": "Use a non-empty team ID or remove the filter"
                        }
                    )
                
                logger.info(
                    f"Getting leaderboard - time_period: {time_period.value}, "
                    f"team_filter: {team_filter}, service_type: {service_type.value if service_type else None}, "
                    f"threshold: {poor_quality_threshold}"
                )
                
            except ValidationError:
                raise
            except Exception as e:
                raise ValidationError(
                    message="Error validating leaderboard parameters",
                    details={
                        "error": str(e),
                        "retry_guidance": "Check the request parameters",
                        "suggested_action": "Verify all parameters are valid"
                    }
                )
            
            # Create leaderboard service with database error handling
            try:
                leaderboard_service = create_leaderboard_service(db)
            except Exception as e:
                logger.error(f"Error creating leaderboard service: {e}", exc_info=True)
                raise DatabaseError(
                    message="Failed to initialize leaderboard service",
                    operation="create_leaderboard_service",
                    details={
                        "error": str(e),
                        "retry_guidance": "Database connection may be unavailable",
                        "suggested_action": "Try again in a few moments"
                    }
                )
            
            # Get leaderboard data with enhanced error handling
            try:
                leaderboard_data = leaderboard_service.get_leaderboard_data(
                    time_period=time_period,
                    team_filter=team_filter,
                    service_type=service_type,
                    poor_quality_threshold=poor_quality_threshold
                )
                
                logger.info(
                    f"Retrieved leaderboard data: {len(leaderboard_data.rankings)} teams, "
                    f"{len(leaderboard_data.poor_quality_services)} poor quality services"
                )
                
            except Exception as e:
                logger.error(f"Error retrieving leaderboard data: {e}", exc_info=True)
                raise DatabaseError(
                    message="Failed to retrieve leaderboard data",
                    operation="get_leaderboard_data",
                    details={
                        "error": str(e),
                        "filters": {
                            "time_period": time_period.value,
                            "team_filter": team_filter,
                            "service_type": service_type.value if service_type else None,
                            "poor_quality_threshold": poor_quality_threshold
                        },
                        "retry_guidance": "Database query may have failed",
                        "suggested_action": "Try again in a few moments or adjust filters"
                    }
                )
            
            # Convert to response model with error handling
            try:
                rankings = []
                for ranking in leaderboard_data.rankings:
                    try:
                        rankings.append(TeamRankingResponse(
                            team_id=ranking.team_id,
                            team_name=ranking.team_name,
                            average_score=ranking.average_score,
                            total_docs=ranking.total_docs,
                            trend=ranking.trend,
                            rank=ranking.rank,
                            last_updated=ranking.last_updated.isoformat()
                        ))
                    except Exception as e:
                        logger.warning(
                            f"Error converting ranking for team {ranking.team_id}: {e}",
                            exc_info=True
                        )
                        # Continue with other rankings instead of failing completely
                        continue
                
                poor_services = []
                for service in leaderboard_data.poor_quality_services:
                    try:
                        poor_services.append(PoorQualityServiceResponse(
                            service_name=service.service_name,
                            team_id=service.team_id,
                            score=service.score,
                            last_updated=service.last_updated.isoformat(),
                            improvement_needed=service.improvement_needed
                        ))
                    except Exception as e:
                        logger.warning(
                            f"Error converting poor quality service {service.service_name}: {e}",
                            exc_info=True
                        )
                        # Continue with other services instead of failing completely
                        continue
                
                response = LeaderboardResponse(
                    rankings=rankings,
                    poor_quality_services=poor_services,
                    generated_at=leaderboard_data.generated_at.isoformat(),
                    time_period=leaderboard_data.time_period,
                    filters_applied=leaderboard_data.filters_applied
                )
                
                logger.info(
                    f"Leaderboard response generated successfully with {len(rankings)} teams and "
                    f"{len(poor_services)} poor quality services"
                )
                
                return response
                
            except Exception as e:
                logger.error(f"Error converting leaderboard data to response format: {e}", exc_info=True)
                raise SpecDocumentationAPIError(
                    message="Error formatting leaderboard response",
                    error_code="LEADERBOARD_FORMAT_ERROR",
                    details={
                        "error": str(e),
                        "retry_guidance": "This appears to be a temporary formatting issue",
                        "suggested_action": "Try again in a few moments"
                    }
                )
            
        except (ValidationError, DatabaseError, SpecDocumentationAPIError):
            raise
        except Exception as e:
            logger.error(f"Unexpected error in get_leaderboard: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=create_error_response(
                    DatabaseError(
                        message="Internal server error while retrieving leaderboard",
                        operation="get_leaderboard",
                        details={
                            "error": str(e),
                            "retry_guidance": "This appears to be a temporary server issue",
                            "suggested_action": "Try again in a few moments"
                        }
                    ),
                    status_code=500,
                    request=request,
                    correlation_id=correlation_id
                ).body
            )


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
            raise ValidationError(
                message="Team not found or no data available",
                field="team_id",
                details={
                    "provided_team_id": team_id,
                    "time_period": time_period.value,
                    "retry_guidance": "Verify the team ID is correct and has generated documentation in the specified time period"
                }
            )
        
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
        
    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_team_details: {e}", exc_info=True)
        raise


@router.get("/quality/alerts", response_model=List[QualityAlertResponse])
async def get_quality_alerts(
    request: Request,
    time_period_days: int = 7,
    team_filter: Optional[str] = None,
    severity_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_check)
):
    """
    Get quality alerts for services needing attention with enhanced error handling.
    
    Query Parameters:
    - time_period_days: Number of days to analyze (default: 7)
    - team_filter: Optional team ID to filter alerts
    - severity_filter: Optional severity filter ("low", "medium", "high", "critical")
    
    Requirements: 2.1, 3.1, 5.1
    """
    correlation_id = getattr(request.state, 'correlation_id', None)
    
    with ErrorContext("get_quality_alerts", 
                     method=request.method, 
                     path=str(request.url.path),
                     time_period_days=time_period_days,
                     team_filter=team_filter,
                     severity_filter=severity_filter):
        try:
            # Validate parameters
            try:
                # Validate time_period_days
                if time_period_days < 1 or time_period_days > 365:
                    raise ValidationError(
                        message="Time period must be between 1 and 365 days",
                        field="time_period_days",
                        details={
                            "provided_value": time_period_days,
                            "valid_range": "1-365",
                            "retry_guidance": "Provide a time period between 1 and 365 days",
                            "suggested_action": "Use a value like 7 for weekly alerts or 30 for monthly"
                        }
                    )
                
                # Validate severity_filter if provided
                valid_severities = ["low", "medium", "high", "critical"]
                if severity_filter and severity_filter not in valid_severities:
                    raise ValidationError(
                        message="Invalid severity filter",
                        field="severity_filter",
                        details={
                            "provided_value": severity_filter,
                            "valid_values": valid_severities,
                            "retry_guidance": "Use a valid severity level",
                            "suggested_action": "Choose from: low, medium, high, critical"
                        }
                    )
                
                # Validate team_filter if provided
                if team_filter and len(team_filter.strip()) == 0:
                    raise ValidationError(
                        message="Team filter cannot be empty",
                        field="team_filter",
                        details={
                            "retry_guidance": "Provide a valid team ID or omit the parameter",
                            "suggested_action": "Use a non-empty team ID or remove the filter"
                        }
                    )
                
                logger.info(
                    f"Getting quality alerts - time_period: {time_period_days} days, "
                    f"team_filter: {team_filter}, severity_filter: {severity_filter}"
                )
                
            except ValidationError:
                raise
            except Exception as e:
                raise ValidationError(
                    message="Error validating quality alerts parameters",
                    details={
                        "error": str(e),
                        "retry_guidance": "Check the request parameters",
                        "suggested_action": "Verify all parameters are valid"
                    }
                )
            
            # Create quality monitor with database error handling
            try:
                quality_monitor = create_quality_monitor(db)
            except Exception as e:
                logger.error(f"Error creating quality monitor: {e}", exc_info=True)
                raise DatabaseError(
                    message="Failed to initialize quality monitor",
                    operation="create_quality_monitor",
                    details={
                        "error": str(e),
                        "retry_guidance": "Database connection may be unavailable",
                        "suggested_action": "Try again in a few moments"
                    }
                )
            
            # Generate quality alerts with enhanced error handling
            try:
                alerts = quality_monitor.generate_quality_alerts(
                    time_period_days=time_period_days,
                    team_filter=team_filter
                )
                
                logger.info(f"Generated {len(alerts)} quality alerts from monitor")
                
            except Exception as e:
                logger.error(f"Error generating quality alerts: {e}", exc_info=True)
                raise DatabaseError(
                    message="Failed to generate quality alerts",
                    operation="generate_quality_alerts",
                    details={
                        "error": str(e),
                        "parameters": {
                            "time_period_days": time_period_days,
                            "team_filter": team_filter
                        },
                        "retry_guidance": "Database query may have failed",
                        "suggested_action": "Try again in a few moments or adjust parameters"
                    }
                )
            
            # Apply severity filter if specified
            try:
                if severity_filter:
                    original_count = len(alerts)
                    alerts = [
                        alert for alert in alerts 
                        if alert.severity.value == severity_filter
                    ]
                    logger.info(
                        f"Applied severity filter '{severity_filter}': "
                        f"{len(alerts)} alerts (from {original_count} total)"
                    )
                
            except Exception as e:
                logger.error(f"Error applying severity filter: {e}", exc_info=True)
                raise SpecDocumentationAPIError(
                    message="Error filtering alerts by severity",
                    error_code="ALERT_FILTER_ERROR",
                    details={
                        "error": str(e),
                        "severity_filter": severity_filter,
                        "retry_guidance": "This appears to be a temporary filtering issue",
                        "suggested_action": "Try again without the severity filter"
                    }
                )
            
            # Convert to response models with error handling
            try:
                alert_responses = []
                for alert in alerts:
                    try:
                        alert_responses.append(QualityAlertResponse(
                            service_name=alert.service_name,
                            team_id=alert.team_id,
                            current_score=alert.current_score,
                            previous_score=alert.previous_score,
                            severity=alert.severity.value,
                            issues_identified=alert.issues_identified,
                            recommended_actions=alert.recommended_actions,
                            created_at=alert.created_at.isoformat(),
                            alert_id=alert.alert_id
                        ))
                    except Exception as e:
                        logger.warning(
                            f"Error converting alert {alert.alert_id}: {e}",
                            exc_info=True
                        )
                        # Continue with other alerts instead of failing completely
                        continue
                
                logger.info(f"Successfully converted {len(alert_responses)} quality alerts to response format")
                return alert_responses
                
            except Exception as e:
                logger.error(f"Error converting alerts to response format: {e}", exc_info=True)
                raise SpecDocumentationAPIError(
                    message="Error formatting quality alerts response",
                    error_code="ALERT_FORMAT_ERROR",
                    details={
                        "error": str(e),
                        "retry_guidance": "This appears to be a temporary formatting issue",
                        "suggested_action": "Try again in a few moments"
                    }
                )
            
        except (ValidationError, DatabaseError, SpecDocumentationAPIError):
            raise
        except Exception as e:
            logger.error(f"Unexpected error in get_quality_alerts: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=create_error_response(
                    DatabaseError(
                        message="Internal server error while retrieving quality alerts",
                        operation="get_quality_alerts",
                        details={
                            "error": str(e),
                            "retry_guidance": "This appears to be a temporary server issue",
                            "suggested_action": "Try again in a few moments"
                        }
                    ),
                    status_code=500,
                    request=request,
                    correlation_id=correlation_id
                ).body
            )


@router.get("/quality/monitoring", response_model=QualityMonitoringResponse)
async def get_quality_monitoring_report(
    request: Request,
    time_period_days: int = 1,
    db: Session = Depends(get_db),
    _: None = Depends(rate_limit_check)
):
    """
    Get comprehensive quality monitoring report with enhanced error handling.
    
    Query Parameters:
    - time_period_days: Number of days to monitor (default: 1)
    
    Requirements: 2.1, 3.1, 5.1
    """
    correlation_id = getattr(request.state, 'correlation_id', None)
    
    with ErrorContext("get_quality_monitoring_report", 
                     method=request.method, 
                     path=str(request.url.path),
                     time_period_days=time_period_days):
        try:
            # Validate parameters
            try:
                # Validate time_period_days
                if time_period_days < 1 or time_period_days > 90:
                    raise ValidationError(
                        message="Time period must be between 1 and 90 days",
                        field="time_period_days",
                        details={
                            "provided_value": time_period_days,
                            "valid_range": "1-90",
                            "retry_guidance": "Provide a time period between 1 and 90 days",
                            "suggested_action": "Use a value like 1 for daily reports or 7 for weekly"
                        }
                    )
                
                logger.info(f"Generating quality monitoring report for {time_period_days} days")
                
            except ValidationError:
                raise
            except Exception as e:
                raise ValidationError(
                    message="Error validating monitoring report parameters",
                    details={
                        "error": str(e),
                        "retry_guidance": "Check the request parameters",
                        "suggested_action": "Verify the time_period_days parameter is valid"
                    }
                )
            
            # Create quality monitor with database error handling
            try:
                quality_monitor = create_quality_monitor(db)
            except Exception as e:
                logger.error(f"Error creating quality monitor: {e}", exc_info=True)
                raise DatabaseError(
                    message="Failed to initialize quality monitor",
                    operation="create_quality_monitor",
                    details={
                        "error": str(e),
                        "retry_guidance": "Database connection may be unavailable",
                        "suggested_action": "Try again in a few moments"
                    }
                )
            
            # Generate monitoring report with enhanced error handling
            try:
                report = quality_monitor.monitor_quality_changes(
                    time_period_days=time_period_days
                )
                
                logger.info(
                    f"Generated monitoring report: {report.total_services_monitored} services monitored, "
                    f"{report.poor_quality_count} poor quality, {len(report.alerts_generated)} alerts"
                )
                
            except Exception as e:
                logger.error(f"Error generating quality monitoring report: {e}", exc_info=True)
                raise DatabaseError(
                    message="Failed to generate quality monitoring report",
                    operation="monitor_quality_changes",
                    details={
                        "error": str(e),
                        "time_period_days": time_period_days,
                        "retry_guidance": "Database query may have failed",
                        "suggested_action": "Try again in a few moments or adjust the time period"
                    }
                )
            
            # Convert alerts to response models with error handling
            try:
                alert_responses = []
                for alert in report.alerts_generated:
                    try:
                        alert_responses.append(QualityAlertResponse(
                            service_name=alert.service_name,
                            team_id=alert.team_id,
                            current_score=alert.current_score,
                            previous_score=alert.previous_score,
                            severity=alert.severity.value,
                            issues_identified=alert.issues_identified,
                            recommended_actions=alert.recommended_actions,
                            created_at=alert.created_at.isoformat(),
                            alert_id=alert.alert_id
                        ))
                    except Exception as e:
                        logger.warning(
                            f"Error converting alert {alert.alert_id} in monitoring report: {e}",
                            exc_info=True
                        )
                        # Continue with other alerts instead of failing completely
                        continue
                
                response = QualityMonitoringResponse(
                    total_services_monitored=report.total_services_monitored,
                    poor_quality_count=report.poor_quality_count,
                    alerts_generated=alert_responses,
                    trend_analysis=report.trend_analysis,
                    recommendations=report.recommendations,
                    generated_at=report.generated_at.isoformat()
                )
                
                logger.info(
                    f"Quality monitoring response generated successfully: "
                    f"{report.total_services_monitored} services, {report.poor_quality_count} poor quality, "
                    f"{len(alert_responses)} alerts"
                )
                
                return response
                
            except Exception as e:
                logger.error(f"Error converting monitoring report to response format: {e}", exc_info=True)
                raise SpecDocumentationAPIError(
                    message="Error formatting quality monitoring response",
                    error_code="MONITORING_FORMAT_ERROR",
                    details={
                        "error": str(e),
                        "retry_guidance": "This appears to be a temporary formatting issue",
                        "suggested_action": "Try again in a few moments"
                    }
                )
            
        except (ValidationError, DatabaseError, SpecDocumentationAPIError):
            raise
        except Exception as e:
            logger.error(f"Unexpected error in get_quality_monitoring_report: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=create_error_response(
                    DatabaseError(
                        message="Internal server error while generating quality monitoring report",
                        operation="get_quality_monitoring_report",
                        details={
                            "error": str(e),
                            "retry_guidance": "This appears to be a temporary server issue",
                            "suggested_action": "Try again in a few moments"
                        }
                    ),
                    status_code=500,
                    request=request,
                    correlation_id=correlation_id
                ).body
            )


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
            raise JobProcessingError(
                message="Failed to trigger leaderboard update",
                details={
                    "retry_guidance": "Try again later or check system status"
                }
            )
        
    except JobProcessingError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in trigger_leaderboard_update: {e}", exc_info=True)
        raise


# Health check and system status endpoints
@router.get("/health")
async def health_check():
    """
    Comprehensive health check endpoint with enhanced monitoring.
    
    Requirements: 5.5
    """
    try:
        from app.services.health_monitor import get_health_monitor
        
        # Get comprehensive health status
        health_monitor = get_health_monitor()
        system_health = await health_monitor.check_all_components()
        
        # Convert to API response format
        response = {
            "overall_healthy": system_health.overall_healthy,
            "overall_status": system_health.overall_status.value,
            "components": {
                name: {
                    "healthy": component.status.value == "healthy",
                    "status": component.status.value,
                    "message": component.message,
                    "response_time_ms": component.response_time_ms
                }
                for name, component in system_health.components.items()
            },
            "performance_summary": {
                "avg_response_time_ms": sum(system_health.performance_metrics.response_times.values()) / len(system_health.performance_metrics.response_times) if system_health.performance_metrics.response_times else 0,
                "error_components": [name for name, rate in system_health.performance_metrics.error_rates.items() if rate > 0]
            },
            "resource_usage": {
                "memory_percent": system_health.resource_metrics.memory_usage_percent,
                "cpu_percent": system_health.resource_metrics.cpu_usage_percent,
                "disk_percent": system_health.resource_metrics.disk_usage_percent
            },
            "alerts_count": len(system_health.alerts),
            "timestamp": system_health.timestamp.isoformat()
        }
        
        status_code = 200 if system_health.overall_healthy else 503
        return response
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "overall_healthy": False,
            "overall_status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@router.get("/health/detailed")
async def detailed_health_check():
    """
    Detailed health check with comprehensive component status and performance metrics.
    
    Requirements: 5.5
    """
    try:
        from app.services.health_monitor import get_health_monitor
        
        # Get comprehensive health status
        health_monitor = get_health_monitor()
        system_health = await health_monitor.check_all_components()
        
        # Convert component health to detailed format
        components = {}
        for name, component in system_health.components.items():
            components[name] = {
                "healthy": component.status.value == "healthy",
                "status": component.status.value,
                "message": component.message,
                "response_time_ms": component.response_time_ms,
                "last_check": component.last_check.isoformat() if component.last_check else None,
                "error": component.error,
                "details": component.details or {}
            }
        
        # Format performance metrics
        performance_metrics = {
            "response_times_ms": system_health.performance_metrics.response_times,
            "throughput_rps": system_health.performance_metrics.throughput,
            "error_rates_percent": system_health.performance_metrics.error_rates,
            "metrics_timestamp": system_health.performance_metrics.timestamp.isoformat()
        }
        
        # Format resource metrics
        resource_metrics = {
            "memory": {
                "usage_percent": system_health.resource_metrics.memory_usage_percent,
                "usage_mb": system_health.resource_metrics.memory_usage_mb
            },
            "cpu": {
                "usage_percent": system_health.resource_metrics.cpu_usage_percent,
                "load_average": system_health.resource_metrics.load_average
            },
            "disk": {
                "usage_percent": system_health.resource_metrics.disk_usage_percent,
                "free_gb": system_health.resource_metrics.disk_free_gb
            },
            "metrics_timestamp": system_health.resource_metrics.timestamp.isoformat()
        }
        
        # Format alerts
        alerts = []
        for alert in system_health.alerts:
            alerts.append({
                "alert_id": alert.alert_id,
                "component": alert.component,
                "severity": alert.severity,
                "message": alert.message,
                "details": alert.details,
                "timestamp": alert.timestamp.isoformat()
            })
        
        return {
            "overall_healthy": system_health.overall_healthy,
            "overall_status": system_health.overall_status.value,
            "components": components,
            "performance_metrics": performance_metrics,
            "resource_metrics": resource_metrics,
            "alerts": alerts,
            "timestamp": system_health.timestamp.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Detailed health check failed: {e}")
        return {
            "overall_healthy": False,
            "overall_status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }


@router.get("/health/database")
async def database_health_check():
    """
    Comprehensive database health check endpoint with detailed metrics.
    
    Requirements: 5.5
    """
    try:
        from app.db.health import get_database_health
        from app.db.database import get_comprehensive_database_status
        
        # Get comprehensive database status
        db_status = get_comprehensive_database_status()
        
        return {
            "status": "success",
            "database_health": db_status,
            "timestamp": db_status.get("timestamp")
        }
        
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": "error"
        }


@router.get("/health/error-analytics")
async def get_error_analytics():
    """
    Get comprehensive error analytics and patterns for monitoring API reliability.
    
    This endpoint provides detailed information about error patterns, trends,
    and alerts to help with proactive issue detection and system monitoring.
    
    Requirements: 2.2, 2.3
    """
    try:
        from app.services.health_monitor import get_health_monitor
        
        # Get error analytics from health monitor
        health_monitor = get_health_monitor()
        error_analytics = await health_monitor.get_error_analytics()
        
        return {
            "status": "success",
            "error_analytics": error_analytics,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error analytics retrieval failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "message": "Failed to retrieve error analytics",
            "timestamp": datetime.utcnow().isoformat()
        }


@router.get("/health/error-patterns")
async def get_error_patterns(
    limit: int = 20,
    sort_by: str = "count",
    time_window_hours: int = 24
):
    """
    Get detailed error patterns with filtering and sorting options.
    
    Args:
        limit: Maximum number of patterns to return (default: 20)
        sort_by: Sort criteria - 'count', 'rate', or 'last_seen' (default: 'count')
        time_window_hours: Only include patterns seen within this time window (default: 24)
    
    Requirements: 2.2, 2.3
    """
    try:
        from app.services.error_pattern_tracker import error_pattern_tracker
        
        # Validate parameters
        if limit < 1 or limit > 100:
            raise ValidationError("Limit must be between 1 and 100")
        
        if sort_by not in ["count", "rate", "last_seen"]:
            raise ValidationError("sort_by must be one of: count, rate, last_seen")
        
        if time_window_hours < 1 or time_window_hours > 168:  # Max 1 week
            raise ValidationError("time_window_hours must be between 1 and 168")
        
        # Get error patterns
        patterns = error_pattern_tracker.get_error_patterns(
            limit=limit,
            sort_by=sort_by,
            time_window_hours=time_window_hours
        )
        
        return {
            "status": "success",
            "patterns": patterns,
            "filters": {
                "limit": limit,
                "sort_by": sort_by,
                "time_window_hours": time_window_hours
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error patterns retrieval failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "message": "Failed to retrieve error patterns",
            "timestamp": datetime.utcnow().isoformat()
        }


@router.get("/health/error-trends")
async def get_error_trends(hours: int = 24):
    """
    Get error trend analysis over the specified time period.
    
    Args:
        hours: Time window for trend analysis (default: 24, max: 168)
    
    Requirements: 2.2, 2.3
    """
    try:
        from app.services.error_pattern_tracker import error_pattern_tracker
        
        # Validate parameters
        if hours < 1 or hours > 168:  # Max 1 week
            raise ValidationError("hours must be between 1 and 168")
        
        # Get error trends
        trends = error_pattern_tracker.get_error_trends(hours=hours)
        
        return {
            "status": "success",
            "trends": trends,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error trends retrieval failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "message": "Failed to retrieve error trends",
            "timestamp": datetime.utcnow().isoformat()
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
        logger.error(f"Failed to get rate limit status: {e}", exc_info=True)
        raise


@router.get("/health/performance")
async def get_performance_metrics():
    """
    Get current performance metrics for all system components.
    
    Requirements: 5.5
    """
    try:
        from app.services.health_monitor import get_health_monitor
        
        health_monitor = get_health_monitor()
        performance_metrics = await health_monitor.get_performance_metrics()
        
        return {
            "response_times_ms": performance_metrics.response_times,
            "throughput_rps": performance_metrics.throughput,
            "error_rates_percent": performance_metrics.error_rates,
            "timestamp": performance_metrics.timestamp.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get performance metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve performance metrics")


@router.get("/health/trends")
async def get_health_trends(days: int = 7):
    """
    Get health trend analysis over the specified time period.
    
    Args:
        days: Number of days to analyze (default: 7, max: 30)
    
    Requirements: 5.5
    """
    try:
        from app.services.health_monitor import get_health_monitor
        
        # Limit days to reasonable range
        days = max(1, min(days, 30))
        
        health_monitor = get_health_monitor()
        trends = await health_monitor.analyze_health_trends(days=days)
        
        return trends
        
    except Exception as e:
        logger.error(f"Failed to get health trends: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve health trends")


@router.get("/health/alerts")
async def get_current_alerts():
    """
    Get current system health alerts.
    
    Requirements: 5.5
    """
    try:
        from app.services.health_monitor import get_health_monitor
        
        health_monitor = get_health_monitor()
        system_health = await health_monitor.check_all_components()
        
        alerts = []
        for alert in system_health.alerts:
            alerts.append({
                "alert_id": alert.alert_id,
                "component": alert.component,
                "severity": alert.severity,
                "message": alert.message,
                "details": alert.details,
                "timestamp": alert.timestamp.isoformat()
            })
        
        return {
            "alerts": alerts,
            "total_alerts": len(alerts),
            "critical_alerts": len([a for a in alerts if a["severity"] == "critical"]),
            "warning_alerts": len([a for a in alerts if a["severity"] == "warning"]),
            "timestamp": system_health.timestamp.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to get current alerts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve current alerts")


@router.get("/system/stats")
async def get_system_statistics():
    """
    Get system-wide statistics and metrics with enhanced monitoring.
    
    Requirements: 5.5
    """
    try:
        from app.services.health_monitor import get_health_monitor
        
        # Get queue status
        queue_status = await job_service.get_queue_status()
        
        # Get job statistics
        job_stats = await job_service.get_job_statistics(days=7)
        
        # Get active jobs
        active_jobs = await job_service.get_active_jobs()
        
        # Get system health and resource metrics
        health_monitor = get_health_monitor()
        system_health = await health_monitor.check_all_components()
        
        return {
            "queue_status": queue_status,
            "job_statistics": job_stats,
            "active_jobs_count": len(active_jobs),
            "system_load": {
                "active_jobs": len([j for j in active_jobs if j.status.value == "processing"]),
                "queued_jobs": len([j for j in active_jobs if j.status.value == "queued"])
            },
            "system_health": {
                "overall_healthy": system_health.overall_healthy,
                "unhealthy_components": [
                    name for name, component in system_health.components.items()
                    if component.status.value == "unhealthy"
                ],
                "degraded_components": [
                    name for name, component in system_health.components.items()
                    if component.status.value == "degraded"
                ]
            },
            "resource_usage": {
                "memory_percent": system_health.resource_metrics.memory_usage_percent,
                "cpu_percent": system_health.resource_metrics.cpu_usage_percent,
                "disk_percent": system_health.resource_metrics.disk_usage_percent,
                "load_average": system_health.resource_metrics.load_average
            },
            "performance_summary": {
                "avg_response_time_ms": sum(system_health.performance_metrics.response_times.values()) / len(system_health.performance_metrics.response_times) if system_health.performance_metrics.response_times else 0,
                "components_with_errors": [
                    name for name, rate in system_health.performance_metrics.error_rates.items()
                    if rate > 0
                ]
            },
            "alerts_summary": {
                "total_alerts": len(system_health.alerts),
                "critical_alerts": len([a for a in system_health.alerts if a.severity == "critical"]),
                "warning_alerts": len([a for a in system_health.alerts if a.severity == "warning"])
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get system statistics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve system statistics")
