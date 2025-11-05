"""
Leaderboard service for aggregating and ranking team documentation quality.
"""
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.repositories import QualityScoreRepository


class TimePeriod(str, Enum):
    """Time period options for leaderboard filtering."""
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"


class ServiceType(str, Enum):
    """Service type options for filtering."""
    REST = "openapi"
    GRAPHQL = "graphql"
    JSON_SCHEMA = "json_schema"


@dataclass
class TeamRanking:
    """Team ranking data for leaderboard."""
    team_id: str
    team_name: str
    average_score: float
    total_docs: int
    trend: str
    rank: int
    last_updated: datetime


@dataclass
class PoorQualityService:
    """Poor quality service data."""
    service_name: str
    team_id: str
    score: int
    last_updated: datetime
    improvement_needed: List[str]


@dataclass
class LeaderboardData:
    """Complete leaderboard data structure."""
    rankings: List[TeamRanking]
    poor_quality_services: List[PoorQualityService]
    generated_at: datetime
    time_period: str
    filters_applied: Dict[str, Any]


class LeaderboardService:
    """Service for generating leaderboard data and rankings."""
    
    def __init__(self, db: Session):
        """Initialize leaderboard service with database session."""
        self.db = db
        self.quality_repo = QualityScoreRepository(db)
        self.logger = logging.getLogger(__name__)
    
    def get_leaderboard_data(
        self,
        time_period: TimePeriod = TimePeriod.MONTH,
        team_filter: Optional[str] = None,
        service_type: Optional[ServiceType] = None,
        poor_quality_threshold: int = 60
    ) -> LeaderboardData:
        """
        Generate complete leaderboard data with rankings and poor quality services.
        
        Args:
            time_period: Time period for data aggregation
            team_filter: Optional team ID filter
            service_type: Optional service type filter
            poor_quality_threshold: Score threshold for poor quality identification
            
        Returns:
            Complete leaderboard data
        """
        self.logger.info(
            f"Generating leaderboard data for period: {time_period}, "
            f"team_filter: {team_filter}, service_type: {service_type}"
        )
        
        # Convert time period to days
        time_period_days = self._get_time_period_days(time_period)
        
        # Get team rankings
        rankings = self._get_team_rankings(
            time_period_days=time_period_days,
            team_filter=team_filter,
            service_type=service_type
        )
        
        # Get poor quality services
        poor_quality_services = self._get_poor_quality_services(
            threshold=poor_quality_threshold,
            time_period_days=time_period_days,
            team_filter=team_filter,
            service_type=service_type
        )
        
        # Build filters applied info
        filters_applied = {
            "time_period": time_period.value,
            "team_filter": team_filter,
            "service_type": service_type.value if service_type else None,
            "poor_quality_threshold": poor_quality_threshold
        }
        
        return LeaderboardData(
            rankings=rankings,
            poor_quality_services=poor_quality_services,
            generated_at=datetime.utcnow(),
            time_period=time_period.value,
            filters_applied=filters_applied
        )
    
    def _get_team_rankings(
        self,
        time_period_days: int,
        team_filter: Optional[str] = None,
        service_type: Optional[ServiceType] = None
    ) -> List[TeamRanking]:
        """
        Calculate team rankings based on quality scores.
        
        Args:
            time_period_days: Number of days to look back
            team_filter: Optional team ID filter
            service_type: Optional service type filter
            
        Returns:
            List of team rankings
        """
        # Get team statistics from repository with filters
        team_stats = self._get_filtered_team_stats(
            time_period_days=time_period_days,
            team_filter=team_filter,
            service_type=service_type
        )
        
        rankings = []
        for rank, stats in enumerate(team_stats, 1):
            # Calculate trend
            trend = self._calculate_team_trend(
                team_id=stats['team_id'],
                current_score=stats['average_score'],
                time_period_days=time_period_days
            )
            
            # Generate team name (in real implementation, this would come from a team service)
            team_name = self._get_team_name(stats['team_id'])
            
            ranking = TeamRanking(
                team_id=stats['team_id'],
                team_name=team_name,
                average_score=stats['average_score'],
                total_docs=stats['total_docs'],
                trend=trend,
                rank=rank,
                last_updated=stats['last_updated']
            )
            rankings.append(ranking)
        
        return rankings
    
    def _get_poor_quality_services(
        self,
        threshold: int,
        time_period_days: int,
        team_filter: Optional[str] = None,
        service_type: Optional[ServiceType] = None
    ) -> List[PoorQualityService]:
        """
        Identify services with poor quality scores.
        
        Args:
            threshold: Score threshold below which services are considered poor quality
            time_period_days: Number of days to look back
            team_filter: Optional team ID filter
            service_type: Optional service type filter
            
        Returns:
            List of poor quality services
        """
        # Get poor quality services from repository with filters
        poor_services_data = self._get_filtered_poor_services(
            threshold=threshold,
            time_period_days=time_period_days,
            team_filter=team_filter,
            service_type=service_type
        )
        
        poor_services = []
        for service_data in poor_services_data:
            # Generate improvement suggestions based on score
            improvement_needed = self._generate_improvement_suggestions(
                score=service_data['score']
            )
            
            poor_service = PoorQualityService(
                service_name=service_data['service_name'],
                team_id=service_data['team_id'],
                score=service_data['score'],
                last_updated=service_data['last_updated'],
                improvement_needed=improvement_needed
            )
            poor_services.append(poor_service)
        
        return poor_services
    
    def _get_filtered_team_stats(
        self,
        time_period_days: int,
        team_filter: Optional[str] = None,
        service_type: Optional[ServiceType] = None
    ) -> List[Dict[str, Any]]:
        """
        Get team statistics with optional filters applied.
        
        Args:
            time_period_days: Number of days to look back
            team_filter: Optional team ID filter
            service_type: Optional service type filter
            
        Returns:
            List of team statistics
        """
        # For now, use the existing repository method
        # In a full implementation, this would be enhanced to support filtering
        team_stats = self.quality_repo.get_team_average_scores(time_period_days)
        
        # Apply team filter if specified
        if team_filter:
            team_stats = [
                stats for stats in team_stats 
                if stats['team_id'] == team_filter
            ]
        
        # Note: Service type filtering would require repository method enhancement
        # to join with job data and filter by spec_format
        
        return team_stats
    
    def _get_filtered_poor_services(
        self,
        threshold: int,
        time_period_days: int,
        team_filter: Optional[str] = None,
        service_type: Optional[ServiceType] = None
    ) -> List[Dict[str, Any]]:
        """
        Get poor quality services with optional filters applied.
        
        Args:
            threshold: Score threshold
            time_period_days: Number of days to look back
            team_filter: Optional team ID filter
            service_type: Optional service type filter
            
        Returns:
            List of poor quality service data
        """
        # For now, use the existing repository method
        poor_services = self.quality_repo.get_poor_quality_services(
            threshold=threshold,
            time_period_days=time_period_days
        )
        
        # Apply team filter if specified
        if team_filter:
            poor_services = [
                service for service in poor_services 
                if service['team_id'] == team_filter
            ]
        
        # Note: Service type filtering would require repository method enhancement
        
        return poor_services
    
    def _calculate_team_trend(
        self,
        team_id: str,
        current_score: float,
        time_period_days: int
    ) -> str:
        """
        Calculate trend direction for a team.
        
        Args:
            team_id: Team identifier
            current_score: Current average score
            time_period_days: Time period for comparison
            
        Returns:
            Trend direction: "improving", "declining", or "stable"
        """
        # Get previous period data for comparison
        previous_period_days = time_period_days * 2  # Look back twice as far
        previous_stats = self.quality_repo.get_team_average_scores(previous_period_days)
        
        # Find previous score for this team
        previous_score = None
        for stats in previous_stats:
            if stats['team_id'] == team_id:
                previous_score = stats['average_score']
                break
        
        if previous_score is None:
            return "stable"  # No previous data
        
        # Calculate trend based on score difference
        score_diff = current_score - previous_score
        
        if score_diff > 5:  # Significant improvement
            return "improving"
        elif score_diff < -5:  # Significant decline
            return "declining"
        else:
            return "stable"
    
    def _generate_improvement_suggestions(self, score: int) -> List[str]:
        """
        Generate improvement suggestions based on quality score.
        
        Args:
            score: Quality score
            
        Returns:
            List of improvement suggestions
        """
        suggestions = []
        
        if score < 30:
            suggestions.extend([
                "Add comprehensive API endpoint descriptions",
                "Include detailed parameter documentation",
                "Provide response schema examples",
                "Add error handling documentation"
            ])
        elif score < 50:
            suggestions.extend([
                "Improve code example quality",
                "Add more detailed parameter descriptions",
                "Include authentication documentation"
            ])
        elif score < 70:
            suggestions.extend([
                "Add more code examples in different languages",
                "Improve error response documentation"
            ])
        
        return suggestions
    
    def _get_team_name(self, team_id: str) -> str:
        """
        Get human-readable team name from team ID.
        
        Args:
            team_id: Team identifier
            
        Returns:
            Team name (for now, just formats the ID)
        """
        # In a real implementation, this would query a team service or database
        return team_id.replace("-", " ").title() + " Team"
    
    def _get_time_period_days(self, time_period: TimePeriod) -> int:
        """
        Convert time period enum to number of days.
        
        Args:
            time_period: Time period enum
            
        Returns:
            Number of days
        """
        if time_period == TimePeriod.WEEK:
            return 7
        elif time_period == TimePeriod.MONTH:
            return 30
        elif time_period == TimePeriod.QUARTER:
            return 90
        else:
            return 30  # Default to month


# Factory function for dependency injection
def create_leaderboard_service(db: Session) -> LeaderboardService:
    """Create a leaderboard service instance with database session."""
    return LeaderboardService(db)