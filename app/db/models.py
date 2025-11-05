"""
Database models for the Spec Documentation API.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class DocumentationJob(Base):
    """Database model for documentation generation jobs."""
    __tablename__ = "documentation_jobs"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    team_id = Column(String(100), nullable=False, index=True)
    service_name = Column(String(200), nullable=False, index=True)
    spec_format = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime, nullable=True)
    specification_hash = Column(String(64), nullable=True)
    
    # Relationship to quality scores
    quality_scores = relationship("QualityScoreDB", back_populates="job")


class QualityScoreDB(Base):
    """Database model for quality scores."""
    __tablename__ = "quality_scores"
    
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id = Column(PGUUID(as_uuid=True), ForeignKey("documentation_jobs.id"), nullable=False, index=True)
    overall_score = Column(Integer, nullable=False, index=True)
    completeness_score = Column(Integer, nullable=False)
    clarity_score = Column(Integer, nullable=False)
    accuracy_score = Column(Integer, nullable=False)
    feedback_json = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Relationship to job
    job = relationship("DocumentationJob", back_populates="quality_scores")