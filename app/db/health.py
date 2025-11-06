"""
Database health check utilities.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.database import get_db_session, engine, health_monitor, get_comprehensive_database_status
from app.db.models import DocumentationJob, QualityScoreDB

logger = logging.getLogger(__name__)


class DatabaseHealthChecker:
    """Database health monitoring and diagnostics."""
    
    def __init__(self):
        """Initialize health checker."""
        self.logger = logging.getLogger(__name__)
    
    def check_connection(self) -> Dict[str, Any]:
        """
        Check basic database connectivity.
        
        Returns:
            Dictionary with connection status
        """
        try:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1 as test"))
                test_value = result.scalar()
                
                return {
                    "status": "healthy",
                    "connected": True,
                    "test_query": test_value == 1,
                    "timestamp": datetime.utcnow().isoformat()
                }
        except SQLAlchemyError as e:
            return {
                "status": "unhealthy",
                "connected": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    def check_tables(self) -> Dict[str, Any]:
        """
        Check if required tables exist and are accessible.
        
        Returns:
            Dictionary with table status
        """
        tables_status = {}
        
        try:
            with get_db_session() as db:
                # Check documentation_jobs table
                try:
                    job_count = db.query(DocumentationJob).count()
                    tables_status["documentation_jobs"] = {
                        "exists": True,
                        "accessible": True,
                        "record_count": job_count
                    }
                except Exception as e:
                    tables_status["documentation_jobs"] = {
                        "exists": False,
                        "accessible": False,
                        "error": str(e)
                    }
                
                # Check quality_scores table
                try:
                    score_count = db.query(QualityScoreDB).count()
                    tables_status["quality_scores"] = {
                        "exists": True,
                        "accessible": True,
                        "record_count": score_count
                    }
                except Exception as e:
                    tables_status["quality_scores"] = {
                        "exists": False,
                        "accessible": False,
                        "error": str(e)
                    }
                
                return {
                    "status": "healthy" if all(t.get("accessible", False) for t in tables_status.values()) else "unhealthy",
                    "tables": tables_status,
                    "timestamp": datetime.utcnow().isoformat()
                }
        
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    def check_performance(self) -> Dict[str, Any]:
        """
        Check database performance metrics.
        
        Returns:
            Dictionary with performance metrics
        """
        try:
            with get_db_session() as db:
                start_time = datetime.utcnow()
                
                # Simple query performance test
                db.execute(text("SELECT COUNT(*) FROM documentation_jobs"))
                query_time = (datetime.utcnow() - start_time).total_seconds()
                
                # Check recent activity
                recent_cutoff = datetime.utcnow() - timedelta(hours=24)
                recent_jobs = db.query(DocumentationJob).filter(
                    DocumentationJob.created_at >= recent_cutoff
                ).count()
                
                recent_scores = db.query(QualityScoreDB).filter(
                    QualityScoreDB.created_at >= recent_cutoff
                ).count()
                
                return {
                    "status": "healthy" if query_time < 1.0 else "slow",
                    "query_response_time": round(query_time, 3),
                    "recent_activity": {
                        "jobs_24h": recent_jobs,
                        "scores_24h": recent_scores
                    },
                    "timestamp": datetime.utcnow().isoformat()
                }
        
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    def get_comprehensive_health(self) -> Dict[str, Any]:
        """
        Get comprehensive database health report combining legacy and new monitoring.
        
        Returns:
            Complete health status dictionary
        """
        # Get enhanced database status from new monitoring system
        enhanced_status = get_comprehensive_database_status()
        
        # Get legacy health checks for backward compatibility
        connection_health = self.check_connection()
        tables_health = self.check_tables()
        performance_health = self.check_performance()
        
        # Combine legacy status determination with enhanced monitoring
        legacy_statuses = [
            connection_health.get("status"),
            tables_health.get("status"),
            performance_health.get("status")
        ]
        
        if all(status == "healthy" for status in legacy_statuses):
            legacy_overall_status = "healthy"
        elif any(status == "unhealthy" for status in legacy_statuses):
            legacy_overall_status = "unhealthy"
        else:
            legacy_overall_status = "degraded"
        
        # Combine enhanced and legacy health information
        return {
            "overall_status": legacy_overall_status,
            "enhanced_monitoring": enhanced_status,
            "legacy_checks": {
                "connection": connection_health,
                "tables": tables_health,
                "performance": performance_health
            },
            "timestamp": datetime.utcnow().isoformat()
        }


# Global health checker instance
health_checker = DatabaseHealthChecker()


def get_database_health() -> Dict[str, Any]:
    """
    Get database health status.
    
    Returns:
        Database health dictionary
    """
    return health_checker.get_comprehensive_health()


def is_database_healthy() -> bool:
    """
    Check if database is healthy.
    
    Returns:
        True if database is healthy, False otherwise
    """
    health = get_database_health()
    return health.get("overall_status") == "healthy"