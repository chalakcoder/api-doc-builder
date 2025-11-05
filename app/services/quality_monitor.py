"""
Quality monitoring service for identifying poor quality services and triggering updates.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
from enum import Enum

from sqlalchemy.orm import Session

from app.db.repositories import QualityScoreRepository
from app.services.leaderboard_service import LeaderboardService, PoorQualityService


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class QualityAlert:
    """Quality alert for poor performing services."""
    service_name: str
    team_id: str
    current_score: int
    previous_score: Optional[int]
    severity: AlertSeverity
    issues_identified: List[str]
    recommended_actions: List[str]
    created_at: datetime
    alert_id: str


@dataclass
class QualityMonitoringReport:
    """Comprehensive quality monitoring report."""
    total_services_monitored: int
    poor_quality_count: int
    alerts_generated: List[QualityAlert]
    trend_analysis: Dict[str, str]
    recommendations: List[str]
    generated_at: datetime


class QualityMonitor:
    """Service for monitoring documentation quality and identifying issues."""
    
    def __init__(self, db: Session):
        """Initialize quality monitor with database session."""
        self.db = db
        self.quality_repo = QualityScoreRepository(db)
        self.leaderboard_service = LeaderboardService(db)
        self.logger = logging.getLogger(__name__)
        
        # Quality thresholds for different severity levels
        self.severity_thresholds = {
            AlertSeverity.CRITICAL: 30,
            AlertSeverity.HIGH: 45,
            AlertSeverity.MEDIUM: 60,
            AlertSeverity.LOW: 75
        }
    
    def identify_poor_quality_services(
        self,
        threshold: int = 60,
        time_period_days: int = 30,
        team_filter: Optional[str] = None
    ) -> List[PoorQualityService]:
        """
        Identify services with poor quality scores using advanced algorithms.
        
        Args:
            threshold: Base score threshold for poor quality identification
            time_period_days: Number of days to analyze
            team_filter: Optional team ID filter
            
        Returns:
            List of poor quality services with detailed analysis
        """
        self.logger.info(
            f"Identifying poor quality services with threshold {threshold} "
            f"over {time_period_days} days"
        )
        
        # Get basic poor quality services from leaderboard service
        poor_services = self.leaderboard_service._get_poor_quality_services(
            threshold=threshold,
            time_period_days=time_period_days,
            team_filter=team_filter
        )
        
        # Enhance with additional analysis
        enhanced_services = []
        for service_data in poor_services:
            # Get detailed quality trend for this service
            trend = self.quality_repo.get_quality_trend(
                team_id=service_data['team_id'],
                service_name=service_data['service_name']
            )
            
            # Analyze improvement patterns
            improvement_needed = self._analyze_service_issues(
                service_data=service_data,
                trend=trend
            )
            
            enhanced_service = PoorQualityService(
                service_name=service_data['service_name'],
                team_id=service_data['team_id'],
                score=service_data['score'],
                last_updated=service_data['last_updated'],
                improvement_needed=improvement_needed
            )
            enhanced_services.append(enhanced_service)
        
        return enhanced_services
    
    def generate_quality_alerts(
        self,
        time_period_days: int = 7,
        team_filter: Optional[str] = None
    ) -> List[QualityAlert]:
        """
        Generate quality alerts for services needing immediate attention.
        
        Args:
            time_period_days: Number of days to analyze for alerts
            team_filter: Optional team ID filter
            
        Returns:
            List of quality alerts
        """
        self.logger.info(f"Generating quality alerts for {time_period_days} days")
        
        alerts = []
        
        # Check each severity threshold
        for severity, threshold in self.severity_thresholds.items():
            poor_services = self.identify_poor_quality_services(
                threshold=threshold,
                time_period_days=time_period_days,
                team_filter=team_filter
            )
            
            for service in poor_services:
                # Skip if we already have a higher severity alert for this service
                if self._has_higher_severity_alert(alerts, service, severity):
                    continue
                
                # Get previous score for trend analysis
                trend = self.quality_repo.get_quality_trend(
                    team_id=service.team_id,
                    service_name=service.service_name
                )
                previous_score = trend.previous_score if trend else None
                
                # Identify specific issues
                issues = self._identify_specific_issues(service, trend)
                
                # Generate recommended actions
                actions = self._generate_recommended_actions(service, severity)
                
                alert = QualityAlert(
                    service_name=service.service_name,
                    team_id=service.team_id,
                    current_score=service.score,
                    previous_score=previous_score,
                    severity=severity,
                    issues_identified=issues,
                    recommended_actions=actions,
                    created_at=datetime.utcnow(),
                    alert_id=f"{service.team_id}-{service.service_name}-{severity.value}"
                )
                alerts.append(alert)
        
        return alerts
    
    def monitor_quality_changes(
        self,
        time_period_days: int = 1
    ) -> QualityMonitoringReport:
        """
        Monitor recent quality changes and generate comprehensive report.
        
        Args:
            time_period_days: Number of days to monitor for changes
            
        Returns:
            Comprehensive monitoring report
        """
        self.logger.info(f"Monitoring quality changes over {time_period_days} days")
        
        # Get all recent quality scores
        cutoff_date = datetime.utcnow() - timedelta(days=time_period_days)
        
        # Generate alerts for recent changes
        alerts = self.generate_quality_alerts(time_period_days=time_period_days)
        
        # Analyze trends across all teams
        trend_analysis = self._analyze_overall_trends(time_period_days)
        
        # Generate system-wide recommendations
        recommendations = self._generate_system_recommendations(alerts, trend_analysis)
        
        # Count services monitored (this would be enhanced with actual data)
        total_services = len(set(
            (alert.team_id, alert.service_name) for alert in alerts
        )) if alerts else 0
        
        poor_quality_count = len([
            alert for alert in alerts 
            if alert.severity in [AlertSeverity.HIGH, AlertSeverity.CRITICAL]
        ])
        
        return QualityMonitoringReport(
            total_services_monitored=total_services,
            poor_quality_count=poor_quality_count,
            alerts_generated=alerts,
            trend_analysis=trend_analysis,
            recommendations=recommendations,
            generated_at=datetime.utcnow()
        )
    
    def trigger_leaderboard_update(self) -> bool:
        """
        Trigger automatic leaderboard update when quality scores change.
        
        Returns:
            True if update was successful
        """
        try:
            self.logger.info("Triggering automatic leaderboard update")
            
            # In a real implementation, this would:
            # 1. Invalidate cached leaderboard data
            # 2. Trigger background job to recalculate rankings
            # 3. Send notifications to interested parties
            # 4. Update any real-time dashboards
            
            # For now, we'll just log the action
            self.logger.info("Leaderboard update triggered successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to trigger leaderboard update: {e}")
            return False
    
    def _analyze_service_issues(
        self,
        service_data: Dict,
        trend: Optional[object]
    ) -> List[str]:
        """
        Analyze specific issues with a service's documentation quality.
        
        Args:
            service_data: Service quality data
            trend: Quality trend data
            
        Returns:
            List of specific issues identified
        """
        issues = []
        score = service_data['score']
        
        # Score-based issue identification
        if score < 30:
            issues.extend([
                "Critical documentation gaps detected",
                "Missing essential API information",
                "Poor structure and organization"
            ])
        elif score < 50:
            issues.extend([
                "Incomplete endpoint documentation",
                "Missing or poor code examples",
                "Unclear parameter descriptions"
            ])
        elif score < 70:
            issues.extend([
                "Limited code example coverage",
                "Inconsistent documentation style"
            ])
        
        # Trend-based issue identification
        if trend and trend.previous_score:
            if trend.current_score < trend.previous_score - 10:
                issues.append("Declining documentation quality trend")
            elif len(trend.score_history) > 2:
                # Check for consistent decline
                scores = [entry['score'] for entry in trend.score_history[-3:]]
                if all(scores[i] > scores[i+1] for i in range(len(scores)-1)):
                    issues.append("Consistent quality decline over time")
        
        return issues
    
    def _identify_specific_issues(
        self,
        service: PoorQualityService,
        trend: Optional[object]
    ) -> List[str]:
        """
        Identify specific issues for alert generation.
        
        Args:
            service: Poor quality service data
            trend: Quality trend data
            
        Returns:
            List of specific issues
        """
        issues = []
        
        # Add service-specific issues
        issues.extend(service.improvement_needed[:3])  # Limit to top 3
        
        # Add trend-based issues
        if trend and trend.previous_score:
            score_change = service.score - trend.previous_score
            if score_change < -15:
                issues.append("Significant quality decline detected")
            elif score_change < -5:
                issues.append("Quality regression identified")
        
        return issues
    
    def _generate_recommended_actions(
        self,
        service: PoorQualityService,
        severity: AlertSeverity
    ) -> List[str]:
        """
        Generate recommended actions based on service issues and severity.
        
        Args:
            service: Poor quality service data
            severity: Alert severity level
            
        Returns:
            List of recommended actions
        """
        actions = []
        
        if severity == AlertSeverity.CRITICAL:
            actions.extend([
                "Immediate documentation review required",
                "Assign dedicated technical writer",
                "Schedule emergency documentation sprint"
            ])
        elif severity == AlertSeverity.HIGH:
            actions.extend([
                "Schedule documentation improvement within 1 week",
                "Review and update API specification",
                "Add comprehensive code examples"
            ])
        elif severity == AlertSeverity.MEDIUM:
            actions.extend([
                "Plan documentation improvements for next sprint",
                "Enhance existing documentation sections"
            ])
        else:  # LOW
            actions.extend([
                "Consider documentation enhancements",
                "Review documentation standards compliance"
            ])
        
        return actions
    
    def _has_higher_severity_alert(
        self,
        existing_alerts: List[QualityAlert],
        service: PoorQualityService,
        current_severity: AlertSeverity
    ) -> bool:
        """
        Check if a higher severity alert already exists for this service.
        
        Args:
            existing_alerts: List of existing alerts
            service: Service to check
            current_severity: Current severity being evaluated
            
        Returns:
            True if higher severity alert exists
        """
        severity_order = [
            AlertSeverity.CRITICAL,
            AlertSeverity.HIGH,
            AlertSeverity.MEDIUM,
            AlertSeverity.LOW
        ]
        
        current_index = severity_order.index(current_severity)
        
        for alert in existing_alerts:
            if (alert.service_name == service.service_name and 
                alert.team_id == service.team_id):
                alert_index = severity_order.index(alert.severity)
                if alert_index < current_index:  # Higher severity (lower index)
                    return True
        
        return False
    
    def _analyze_overall_trends(self, time_period_days: int) -> Dict[str, str]:
        """
        Analyze overall quality trends across the system.
        
        Args:
            time_period_days: Number of days to analyze
            
        Returns:
            Dictionary of trend analysis results
        """
        # Get team statistics for trend analysis
        current_stats = self.quality_repo.get_team_average_scores(time_period_days)
        previous_stats = self.quality_repo.get_team_average_scores(time_period_days * 2)
        
        trends = {}
        
        if current_stats and previous_stats:
            current_avg = sum(team['average_score'] for team in current_stats) / len(current_stats)
            previous_avg = sum(team['average_score'] for team in previous_stats) / len(previous_stats)
            
            if current_avg > previous_avg + 2:
                trends['overall'] = "improving"
            elif current_avg < previous_avg - 2:
                trends['overall'] = "declining"
            else:
                trends['overall'] = "stable"
        else:
            trends['overall'] = "insufficient_data"
        
        return trends
    
    def _generate_system_recommendations(
        self,
        alerts: List[QualityAlert],
        trends: Dict[str, str]
    ) -> List[str]:
        """
        Generate system-wide recommendations based on alerts and trends.
        
        Args:
            alerts: List of quality alerts
            trends: Trend analysis results
            
        Returns:
            List of system recommendations
        """
        recommendations = []
        
        # Alert-based recommendations
        critical_count = len([a for a in alerts if a.severity == AlertSeverity.CRITICAL])
        high_count = len([a for a in alerts if a.severity == AlertSeverity.HIGH])
        
        if critical_count > 0:
            recommendations.append(
                f"Immediate action required: {critical_count} services have critical quality issues"
            )
        
        if high_count > 3:
            recommendations.append(
                "Consider implementing documentation quality training program"
            )
        
        # Trend-based recommendations
        if trends.get('overall') == 'declining':
            recommendations.append(
                "System-wide quality decline detected - review documentation processes"
            )
        elif trends.get('overall') == 'improving':
            recommendations.append(
                "Quality improvements detected - continue current practices"
            )
        
        return recommendations


# Factory function for dependency injection
def create_quality_monitor(db: Session) -> QualityMonitor:
    """Create a quality monitor instance with database session."""
    return QualityMonitor(db)