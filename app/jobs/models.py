"""
Job-related data models and enums.
"""
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List
from uuid import UUID

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Job status enumeration."""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SpecFormat(str, Enum):
    """Specification format enumeration."""
    OPENAPI = "openapi"
    GRAPHQL = "graphql"
    JSON_SCHEMA = "json_schema"


class OutputFormat(str, Enum):
    """Output format enumeration."""
    MARKDOWN = "markdown"
    HTML = "html"


class JobRequest(BaseModel):
    """Job request model for documentation generation."""
    specification: Dict[str, Any] | str
    spec_format: SpecFormat
    output_formats: List[OutputFormat]
    team_id: str
    service_name: str
    
    class Config:
        json_encoders = {
            Enum: lambda v: v.value
        }


class JobProgress(BaseModel):
    """Job progress tracking model."""
    current_step: str
    total_steps: int
    completed_steps: int
    estimated_completion: Optional[datetime] = None
    
    @property
    def progress_percentage(self) -> float:
        """Calculate progress percentage."""
        if self.total_steps == 0:
            return 0.0
        return (self.completed_steps / self.total_steps) * 100


class JobResult(BaseModel):
    """Job result model."""
    job_id: UUID
    status: JobStatus
    created_at: datetime
    completed_at: Optional[datetime] = None
    progress: Optional[JobProgress] = None
    results: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    
    class Config:
        json_encoders = {
            UUID: str,
            datetime: lambda v: v.isoformat(),
            Enum: lambda v: v.value
        }


class QualityMetrics(BaseModel):
    """Quality metrics model."""
    completeness: int = Field(ge=0, le=100)
    clarity: int = Field(ge=0, le=100)
    accuracy: int = Field(ge=0, le=100)
    overall_score: int = Field(ge=0, le=100)
    suggestions: List[str] = Field(default_factory=list)


class DocumentationOutput(BaseModel):
    """Documentation generation output model."""
    markdown_content: Optional[str] = None
    html_content: Optional[str] = None
    markdown_url: Optional[str] = None
    html_url: Optional[str] = None
    quality_metrics: Optional[QualityMetrics] = None