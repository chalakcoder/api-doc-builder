"""
Error pattern tracking and analysis system for monitoring API reliability.
"""
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from threading import Lock
import asyncio

from app.core.logging import get_logger, EnhancedLoggerMixin

logger = get_logger(__name__)


@dataclass
class ErrorPattern:
    """Represents an error pattern with tracking information."""
    error_type: str
    endpoint: str
    error_code: str
    count: int = 0
    first_seen: datetime = field(default_factory=datetime.utcnow)
    last_seen: datetime = field(default_factory=datetime.utcnow)
    recent_occurrences: deque = field(default_factory=lambda: deque(maxlen=100))
    correlation_ids: List[str] = field(default_factory=list)
    
    def add_occurrence(self, correlation_id: str = None) -> None:
        """Add a new occurrence of this error pattern."""
        self.count += 1
        self.last_seen = datetime.utcnow()
        self.recent_occurrences.append(datetime.utcnow())
        
        if correlation_id and len(self.correlation_ids) < 50:  # Limit stored correlation IDs
            self.correlation_ids.append(correlation_id)
    
    def get_rate_per_minute(self, minutes: int = 5) -> float:
        """Calculate error rate per minute over the specified time window."""
        cutoff_time = datetime.utcnow() - timedelta(minutes=minutes)
        recent_count = sum(1 for occurrence in self.recent_occurrences if occurrence > cutoff_time)
        return recent_count / minutes if minutes > 0 else 0.0
    
    def is_trending_up(self, window_minutes: int = 10) -> bool:
        """Check if error pattern is trending upward."""
        if len(self.recent_occurrences) < 4:
            return False
        
        cutoff_time = datetime.utcnow() - timedelta(minutes=window_minutes)
        recent_errors = [occ for occ in self.recent_occurrences if occ > cutoff_time]
        
        if len(recent_errors) < 4:
            return False
        
        # Check if the second half has more errors than the first half
        mid_point = len(recent_errors) // 2
        first_half = recent_errors[:mid_point]
        second_half = recent_errors[mid_point:]
        
        return len(second_half) > len(first_half) * 1.5


@dataclass
class ErrorAlert:
    """Represents an error alert that should be triggered."""
    alert_type: str
    message: str
    severity: str  # 'low', 'medium', 'high', 'critical'
    error_pattern: ErrorPattern
    threshold_exceeded: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary for logging/notification."""
        return {
            "alert_type": self.alert_type,
            "message": self.message,
            "severity": self.severity,
            "error_type": self.error_pattern.error_type,
            "endpoint": self.error_pattern.endpoint,
            "error_code": self.error_pattern.error_code,
            "error_count": self.error_pattern.count,
            "error_rate_per_minute": self.error_pattern.get_rate_per_minute(),
            "threshold_exceeded": self.threshold_exceeded,
            "timestamp": self.timestamp.isoformat(),
            "correlation_ids": self.error_pattern.correlation_ids[-5:]  # Last 5 correlation IDs
        }


class ErrorPatternTracker(EnhancedLoggerMixin):
    """
    Tracks error patterns and provides analysis for proactive issue detection.
    """
    
    def __init__(self):
        self.patterns: Dict[str, ErrorPattern] = {}
        self.lock = Lock()
        self.alert_thresholds = {
            "error_rate_per_minute": {
                "low": 1.0,
                "medium": 5.0,
                "high": 10.0,
                "critical": 20.0
            },
            "total_errors": {
                "low": 10,
                "medium": 50,
                "high": 100,
                "critical": 200
            },
            "trending_threshold": 5  # Minimum errors needed to check trending
        }
        self.recent_alerts: deque = deque(maxlen=1000)  # Store recent alerts
        self.last_cleanup = datetime.utcnow()
    
    def _get_pattern_key(self, error_type: str, endpoint: str, error_code: str) -> str:
        """Generate a unique key for an error pattern."""
        return f"{error_type}:{endpoint}:{error_code}"
    
    def track_error(
        self,
        error_type: str,
        endpoint: str,
        error_code: str,
        correlation_id: str = None,
        additional_context: Dict[str, Any] = None
    ) -> None:
        """
        Track an error occurrence and update patterns.
        
        Args:
            error_type: Type of error (e.g., 'ValidationError', 'DatabaseError')
            endpoint: API endpoint where error occurred
            error_code: Specific error code
            correlation_id: Request correlation ID for tracing
            additional_context: Additional context information
        """
        pattern_key = self._get_pattern_key(error_type, endpoint, error_code)
        
        with self.lock:
            if pattern_key not in self.patterns:
                self.patterns[pattern_key] = ErrorPattern(
                    error_type=error_type,
                    endpoint=endpoint,
                    error_code=error_code
                )
            
            pattern = self.patterns[pattern_key]
            pattern.add_occurrence(correlation_id)
            
            # Log the error tracking
            self.logger.debug(
                "Error pattern tracked",
                pattern_key=pattern_key,
                error_count=pattern.count,
                error_rate=pattern.get_rate_per_minute(),
                correlation_id=correlation_id,
                additional_context=additional_context
            )
            
            # Check for alerts
            alerts = self._check_alert_conditions(pattern)
            for alert in alerts:
                self._trigger_alert(alert)
    
    def _check_alert_conditions(self, pattern: ErrorPattern) -> List[ErrorAlert]:
        """Check if error pattern meets alert conditions."""
        alerts = []
        
        # Check error rate thresholds
        current_rate = pattern.get_rate_per_minute()
        for severity, threshold in self.alert_thresholds["error_rate_per_minute"].items():
            if current_rate >= threshold:
                alerts.append(ErrorAlert(
                    alert_type="high_error_rate",
                    message=f"High error rate detected: {current_rate:.2f} errors/minute for {pattern.error_type} on {pattern.endpoint}",
                    severity=severity,
                    error_pattern=pattern,
                    threshold_exceeded={"error_rate_per_minute": current_rate, "threshold": threshold}
                ))
                break  # Only trigger the highest severity alert
        
        # Check total error count thresholds
        for severity, threshold in self.alert_thresholds["total_errors"].items():
            if pattern.count >= threshold:
                alerts.append(ErrorAlert(
                    alert_type="high_error_count",
                    message=f"High error count detected: {pattern.count} total errors for {pattern.error_type} on {pattern.endpoint}",
                    severity=severity,
                    error_pattern=pattern,
                    threshold_exceeded={"total_errors": pattern.count, "threshold": threshold}
                ))
                break  # Only trigger the highest severity alert
        
        # Check for trending errors
        if (pattern.count >= self.alert_thresholds["trending_threshold"] and 
            pattern.is_trending_up()):
            alerts.append(ErrorAlert(
                alert_type="trending_errors",
                message=f"Trending error pattern detected: {pattern.error_type} on {pattern.endpoint} is increasing",
                severity="medium",
                error_pattern=pattern,
                threshold_exceeded={"trending": True, "recent_rate": current_rate}
            ))
        
        return alerts
    
    def _trigger_alert(self, alert: ErrorAlert) -> None:
        """Trigger an alert by logging and storing it."""
        # Store alert
        self.recent_alerts.append(alert)
        
        # Log alert based on severity
        alert_data = alert.to_dict()
        
        if alert.severity == "critical":
            self.logger.critical("Critical error pattern alert", **alert_data)
        elif alert.severity == "high":
            self.logger.error("High severity error pattern alert", **alert_data)
        elif alert.severity == "medium":
            self.logger.warning("Medium severity error pattern alert", **alert_data)
        else:
            self.logger.info("Low severity error pattern alert", **alert_data)
    
    def get_error_patterns(
        self,
        limit: int = 50,
        sort_by: str = "count",
        time_window_hours: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Get error patterns sorted by specified criteria.
        
        Args:
            limit: Maximum number of patterns to return
            sort_by: Sort criteria ('count', 'rate', 'last_seen')
            time_window_hours: Only include patterns seen within this time window
            
        Returns:
            List of error pattern dictionaries
        """
        cutoff_time = datetime.utcnow() - timedelta(hours=time_window_hours)
        
        with self.lock:
            # Filter patterns by time window
            filtered_patterns = [
                pattern for pattern in self.patterns.values()
                if pattern.last_seen > cutoff_time
            ]
            
            # Sort patterns
            if sort_by == "rate":
                filtered_patterns.sort(key=lambda p: p.get_rate_per_minute(), reverse=True)
            elif sort_by == "last_seen":
                filtered_patterns.sort(key=lambda p: p.last_seen, reverse=True)
            else:  # Default to count
                filtered_patterns.sort(key=lambda p: p.count, reverse=True)
            
            # Convert to dictionaries and limit results
            return [
                {
                    "error_type": pattern.error_type,
                    "endpoint": pattern.endpoint,
                    "error_code": pattern.error_code,
                    "count": pattern.count,
                    "rate_per_minute": pattern.get_rate_per_minute(),
                    "first_seen": pattern.first_seen.isoformat(),
                    "last_seen": pattern.last_seen.isoformat(),
                    "is_trending": pattern.is_trending_up(),
                    "recent_correlation_ids": pattern.correlation_ids[-3:]  # Last 3 correlation IDs
                }
                for pattern in filtered_patterns[:limit]
            ]
    
    def get_error_trends(self, hours: int = 24) -> Dict[str, Any]:
        """
        Analyze error trends over the specified time period.
        
        Args:
            hours: Time window for trend analysis
            
        Returns:
            Dictionary containing trend analysis
        """
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        
        with self.lock:
            active_patterns = [
                pattern for pattern in self.patterns.values()
                if pattern.last_seen > cutoff_time
            ]
            
            total_errors = sum(pattern.count for pattern in active_patterns)
            trending_patterns = [pattern for pattern in active_patterns if pattern.is_trending_up()]
            
            # Group by error type
            error_type_counts = defaultdict(int)
            endpoint_counts = defaultdict(int)
            
            for pattern in active_patterns:
                error_type_counts[pattern.error_type] += pattern.count
                endpoint_counts[pattern.endpoint] += pattern.count
            
            return {
                "time_window_hours": hours,
                "total_error_patterns": len(active_patterns),
                "total_errors": total_errors,
                "trending_patterns": len(trending_patterns),
                "top_error_types": dict(sorted(error_type_counts.items(), key=lambda x: x[1], reverse=True)[:10]),
                "top_endpoints": dict(sorted(endpoint_counts.items(), key=lambda x: x[1], reverse=True)[:10]),
                "trending_pattern_details": [
                    {
                        "error_type": pattern.error_type,
                        "endpoint": pattern.endpoint,
                        "error_code": pattern.error_code,
                        "count": pattern.count,
                        "rate_per_minute": pattern.get_rate_per_minute()
                    }
                    for pattern in trending_patterns[:5]  # Top 5 trending patterns
                ]
            }
    
    def get_recent_alerts(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent alerts."""
        with self.lock:
            return [alert.to_dict() for alert in list(self.recent_alerts)[-limit:]]
    
    def cleanup_old_patterns(self, days: int = 7) -> int:
        """
        Clean up old error patterns to prevent memory bloat.
        
        Args:
            days: Remove patterns older than this many days
            
        Returns:
            Number of patterns removed
        """
        cutoff_time = datetime.utcnow() - timedelta(days=days)
        removed_count = 0
        
        with self.lock:
            patterns_to_remove = [
                key for key, pattern in self.patterns.items()
                if pattern.last_seen < cutoff_time
            ]
            
            for key in patterns_to_remove:
                del self.patterns[key]
                removed_count += 1
            
            self.last_cleanup = datetime.utcnow()
        
        if removed_count > 0:
            self.logger.info(f"Cleaned up {removed_count} old error patterns")
        
        return removed_count
    
    async def periodic_cleanup(self, cleanup_interval_hours: int = 24) -> None:
        """Run periodic cleanup of old patterns."""
        while True:
            try:
                await asyncio.sleep(cleanup_interval_hours * 3600)  # Convert hours to seconds
                self.cleanup_old_patterns()
            except Exception as e:
                self.logger.error(f"Error during periodic cleanup: {e}")


# Global error pattern tracker instance
error_pattern_tracker = ErrorPatternTracker()


def track_error_pattern(
    error_type: str,
    endpoint: str,
    error_code: str,
    correlation_id: str = None,
    additional_context: Dict[str, Any] = None
) -> None:
    """
    Convenience function to track error patterns.
    
    Args:
        error_type: Type of error
        endpoint: API endpoint
        error_code: Error code
        correlation_id: Request correlation ID
        additional_context: Additional context
    """
    error_pattern_tracker.track_error(
        error_type=error_type,
        endpoint=endpoint,
        error_code=error_code,
        correlation_id=correlation_id,
        additional_context=additional_context
    )


def get_error_analytics() -> Dict[str, Any]:
    """Get comprehensive error analytics."""
    return {
        "patterns": error_pattern_tracker.get_error_patterns(limit=20),
        "trends": error_pattern_tracker.get_error_trends(hours=24),
        "recent_alerts": error_pattern_tracker.get_recent_alerts(limit=10)
    }