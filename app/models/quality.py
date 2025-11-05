"""
Quality scoring models for documentation evaluation.
"""
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, validator


class QualityMetricType(str, Enum):
    """Types of quality metrics."""
    COMPLETENESS = "completeness"
    CLARITY = "clarity"
    ACCURACY = "accuracy"


class QualityFeedback(BaseModel):
    """Detailed feedback for quality improvements."""
    metric_type: QualityMetricType
    score: int = Field(..., ge=0, le=100, description="Score from 0-100")
    suggestions: List[str] = Field(default_factory=list, description="Improvement suggestions")
    details: Dict[str, str] = Field(default_factory=dict, description="Additional details")


class QualityMetrics(BaseModel):
    """Complete quality assessment for documentation."""
    completeness: int = Field(..., ge=0, le=100, description="Completeness score 0-100")
    clarity: int = Field(..., ge=0, le=100, description="Clarity score 0-100")
    accuracy: int = Field(..., ge=0, le=100, description="Accuracy score 0-100")
    overall_score: int = Field(..., ge=0, le=100, description="Overall score 0-100")
    feedback: List[QualityFeedback] = Field(default_factory=list, description="Detailed feedback")
    
    @validator('overall_score', always=True)
    def calculate_overall_score(cls, v, values):
        """Calculate overall score from individual metrics."""
        if 'completeness' in values and 'clarity' in values and 'accuracy' in values:
            # Weighted average: completeness 40%, clarity 30%, accuracy 30%
            return int(
                values['completeness'] * 0.4 +
                values['clarity'] * 0.3 +
                values['accuracy'] * 0.3
            )
        return v


class QualityScore(BaseModel):
    """Quality score record with metadata."""
    id: UUID = Field(default_factory=uuid4)
    job_id: UUID
    team_id: str
    service_name: str
    spec_format: str
    metrics: QualityMetrics
    created_at: datetime = Field(default_factory=datetime.utcnow)
    specification_hash: Optional[str] = None
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: str
        }


class QualityTrend(BaseModel):
    """Quality trend data for a service."""
    service_name: str
    team_id: str
    current_score: int
    previous_score: Optional[int] = None
    trend_direction: str = Field(default="stable")  # "improving", "declining", "stable"
    score_history: List[Dict[str, any]] = Field(default_factory=list)
    
    @validator('trend_direction', always=True)
    def calculate_trend(cls, v, values):
        """Calculate trend direction from current and previous scores."""
        if 'current_score' in values and 'previous_score' in values:
            current = values['current_score']
            previous = values.get('previous_score')
            
            if previous is None:
                return "stable"
            
            diff = current - previous
            if diff > 5:
                return "improving"
            elif diff < -5:
                return "declining"
            else:
                return "stable"
        return v