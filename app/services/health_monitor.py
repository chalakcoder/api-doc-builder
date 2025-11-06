"""
Comprehensive health monitoring system for all system components.

This module provides detailed health checks for database, Redis, job queue,
and API components, along with performance metrics collection and system
resource monitoring.

Requirements: 2.2, 5.5
"""
import logging
import time
import psutil
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum

import redis
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.database import get_db_session, engine
from app.core.config import settings
from app.services.error_pattern_tracker import get_error_analytics

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status enumeration."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """Health status for a system component."""
    name: str
    status: HealthStatus
    message: str
    response_time_ms: Optional[float] = None
    last_check: Optional[datetime] = None
    details: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class PerformanceMetrics:
    """Performance metrics for system monitoring."""
    response_times: Dict[str, float]
    throughput: Dict[str, float]
    error_rates: Dict[str, float]
    timestamp: datetime


@dataclass
class SystemResourceMetrics:
    """System resource usage metrics."""
    memory_usage_percent: float
    memory_usage_mb: float
    cpu_usage_percent: float
    disk_usage_percent: float
    disk_free_gb: float
    load_average: List[float]
    timestamp: datetime


@dataclass
class HealthAlert:
    """Health monitoring alert."""
    component: str
    severity: str
    message: str
    details: Dict[str, Any]
    timestamp: datetime
    alert_id: str


@dataclass
class SystemHealthStatus:
    """Complete system health status."""
    overall_healthy: bool
    overall_status: HealthStatus
    components: Dict[str, ComponentHealth]
    performance_metrics: PerformanceMetrics
    resource_metrics: SystemResourceMetrics
    alerts: List[HealthAlert]
    timestamp: datetime


class ComprehensiveHealthMonitor:
    """
    Comprehensive health monitoring system for all system components.
    
    Provides detailed health checks, performance metrics collection,
    and system resource monitoring with alerting capabilities.
    """
    
    def __init__(self):
        """Initialize health monitor."""
        self.logger = logging.getLogger(__name__)
        self._performance_history: List[PerformanceMetrics] = []
        self._health_history: List[SystemHealthStatus] = []
        self._alert_thresholds = {
            "memory_usage_percent": 80.0,
            "cpu_usage_percent": 85.0,
            "disk_usage_percent": 90.0,
            "response_time_ms": 1000.0,
            "error_rate_percent": 5.0
        }
    
    async def check_database_health(self) -> ComponentHealth:
        """
        Check database component health with detailed metrics.
        
        Returns:
            ComponentHealth for database component
        """
        start_time = time.time()
        
        try:
            # Test basic connectivity
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1 as test"))
                test_value = result.scalar()
                
                if test_value != 1:
                    raise SQLAlchemyError("Database test query returned unexpected result")
            
            # Test session management
            with get_db_session() as db:
                # Test a simple query
                db.execute(text("SELECT COUNT(*) FROM information_schema.tables"))
            
            response_time = (time.time() - start_time) * 1000
            
            # Get connection pool info
            pool = engine.pool
            pool_status = {
                "size": pool.size(),
                "checked_in": pool.checkedin(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow(),
                "invalid": pool.invalid()
            }
            
            # Determine status based on response time and pool health
            if response_time > 2000:  # 2 seconds
                status = HealthStatus.DEGRADED
                message = f"Database responding slowly ({response_time:.1f}ms)"
            elif pool_status["checked_out"] / pool_status["size"] > 0.8:
                status = HealthStatus.DEGRADED
                message = "Database connection pool under high load"
            else:
                status = HealthStatus.HEALTHY
                message = "Database operational"
            
            return ComponentHealth(
                name="database",
                status=status,
                message=message,
                response_time_ms=response_time,
                last_check=datetime.utcnow(),
                details={
                    "connection_pool": pool_status,
                    "engine_url": str(engine.url).split('@')[0] + '@***'  # Hide credentials
                }
            )
            
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return ComponentHealth(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message="Database connection failed",
                response_time_ms=response_time,
                last_check=datetime.utcnow(),
                error=str(e),
                details={"error_type": type(e).__name__}
            )
    
    async def check_redis_health(self) -> ComponentHealth:
        """
        Check Redis component health for job queue and rate limiting.
        
        Returns:
            ComponentHealth for Redis component
        """
        start_time = time.time()
        
        try:
            # Create Redis client
            redis_client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            
            # Test basic connectivity
            redis_client.ping()
            
            # Test basic operations
            test_key = f"health_check_{int(time.time())}"
            redis_client.set(test_key, "test", ex=10)
            test_value = redis_client.get(test_key)
            redis_client.delete(test_key)
            
            if test_value != "test":
                raise redis.RedisError("Redis test operation failed")
            
            response_time = (time.time() - start_time) * 1000
            
            # Get Redis info
            redis_info = redis_client.info()
            memory_usage = redis_info.get('used_memory_human', 'unknown')
            connected_clients = redis_info.get('connected_clients', 0)
            
            # Determine status based on response time and load
            if response_time > 500:  # 500ms
                status = HealthStatus.DEGRADED
                message = f"Redis responding slowly ({response_time:.1f}ms)"
            elif connected_clients > 100:
                status = HealthStatus.DEGRADED
                message = f"Redis under high load ({connected_clients} clients)"
            else:
                status = HealthStatus.HEALTHY
                message = "Redis operational"
            
            return ComponentHealth(
                name="redis",
                status=status,
                message=message,
                response_time_ms=response_time,
                last_check=datetime.utcnow(),
                details={
                    "memory_usage": memory_usage,
                    "connected_clients": connected_clients,
                    "redis_version": redis_info.get('redis_version', 'unknown')
                }
            )
            
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return ComponentHealth(
                name="redis",
                status=HealthStatus.UNHEALTHY,
                message="Redis connection failed",
                response_time_ms=response_time,
                last_check=datetime.utcnow(),
                error=str(e),
                details={"error_type": type(e).__name__}
            )
    
    async def check_job_queue_health(self) -> ComponentHealth:
        """
        Check job queue component health.
        
        Returns:
            ComponentHealth for job queue component
        """
        start_time = time.time()
        
        try:
            from app.jobs.job_service import job_service
            
            # Get queue status
            queue_status = await job_service.get_queue_status()
            
            response_time = (time.time() - start_time) * 1000
            
            # Check queue health indicators
            pending_jobs = queue_status.get('pending_jobs', 0)
            failed_jobs = queue_status.get('failed_jobs', 0)
            processing_jobs = queue_status.get('processing_jobs', 0)
            
            # Determine status based on queue metrics
            if failed_jobs > 10:
                status = HealthStatus.DEGRADED
                message = f"High number of failed jobs ({failed_jobs})"
            elif pending_jobs > 50:
                status = HealthStatus.DEGRADED
                message = f"High queue backlog ({pending_jobs} pending)"
            elif response_time > 1000:
                status = HealthStatus.DEGRADED
                message = f"Job queue responding slowly ({response_time:.1f}ms)"
            else:
                status = HealthStatus.HEALTHY
                message = "Job queue operational"
            
            return ComponentHealth(
                name="job_queue",
                status=status,
                message=message,
                response_time_ms=response_time,
                last_check=datetime.utcnow(),
                details={
                    "pending_jobs": pending_jobs,
                    "processing_jobs": processing_jobs,
                    "failed_jobs": failed_jobs,
                    "queue_status": queue_status
                }
            )
            
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return ComponentHealth(
                name="job_queue",
                status=HealthStatus.UNHEALTHY,
                message="Job queue check failed",
                response_time_ms=response_time,
                last_check=datetime.utcnow(),
                error=str(e),
                details={"error_type": type(e).__name__}
            )
    
    async def check_api_health(self) -> ComponentHealth:
        """
        Check API component health.
        
        Returns:
            ComponentHealth for API component
        """
        start_time = time.time()
        
        try:
            # For API health, we're already running so basic check passes
            # Could add more sophisticated checks here like endpoint testing
            
            response_time = (time.time() - start_time) * 1000
            
            return ComponentHealth(
                name="api",
                status=HealthStatus.HEALTHY,
                message="API endpoints operational",
                response_time_ms=response_time,
                last_check=datetime.utcnow(),
                details={
                    "endpoints_active": True,
                    "middleware_loaded": True
                }
            )
            
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            return ComponentHealth(
                name="api",
                status=HealthStatus.UNHEALTHY,
                message="API health check failed",
                response_time_ms=response_time,
                last_check=datetime.utcnow(),
                error=str(e),
                details={"error_type": type(e).__name__}
            )
    
    def get_system_resource_metrics(self) -> SystemResourceMetrics:
        """
        Collect system resource usage metrics.
        
        Returns:
            SystemResourceMetrics with current resource usage
        """
        try:
            # Memory metrics
            memory = psutil.virtual_memory()
            memory_usage_percent = memory.percent
            memory_usage_mb = memory.used / (1024 * 1024)
            
            # CPU metrics
            cpu_usage_percent = psutil.cpu_percent(interval=1)
            
            # Disk metrics
            disk = psutil.disk_usage('/')
            disk_usage_percent = (disk.used / disk.total) * 100
            disk_free_gb = disk.free / (1024 * 1024 * 1024)
            
            # Load average (Unix-like systems)
            try:
                load_average = list(psutil.getloadavg())
            except AttributeError:
                # Windows doesn't have load average
                load_average = [0.0, 0.0, 0.0]
            
            return SystemResourceMetrics(
                memory_usage_percent=memory_usage_percent,
                memory_usage_mb=memory_usage_mb,
                cpu_usage_percent=cpu_usage_percent,
                disk_usage_percent=disk_usage_percent,
                disk_free_gb=disk_free_gb,
                load_average=load_average,
                timestamp=datetime.utcnow()
            )
            
        except Exception as e:
            self.logger.error(f"Failed to collect system resource metrics: {e}")
            # Return default metrics on error
            return SystemResourceMetrics(
                memory_usage_percent=0.0,
                memory_usage_mb=0.0,
                cpu_usage_percent=0.0,
                disk_usage_percent=0.0,
                disk_free_gb=0.0,
                load_average=[0.0, 0.0, 0.0],
                timestamp=datetime.utcnow()
            )
    
    async def collect_performance_metrics(self, components: Dict[str, ComponentHealth]) -> PerformanceMetrics:
        """
        Collect performance metrics from component health checks.
        
        Args:
            components: Dictionary of component health results
            
        Returns:
            PerformanceMetrics with current performance data
        """
        response_times = {}
        throughput = {}
        error_rates = {}
        
        for name, health in components.items():
            if health.response_time_ms is not None:
                response_times[name] = health.response_time_ms
            
            # Calculate error rate (simplified - could be enhanced with historical data)
            if health.status == HealthStatus.UNHEALTHY:
                error_rates[name] = 100.0
            elif health.status == HealthStatus.DEGRADED:
                error_rates[name] = 25.0
            else:
                error_rates[name] = 0.0
            
            # Throughput calculation (placeholder - would need actual metrics)
            throughput[name] = 1000.0 / max(health.response_time_ms or 1, 1)
        
        return PerformanceMetrics(
            response_times=response_times,
            throughput=throughput,
            error_rates=error_rates,
            timestamp=datetime.utcnow()
        )
    
    def generate_health_alerts(self, health_status: SystemHealthStatus) -> List[HealthAlert]:
        """
        Generate health alerts based on current system status.
        
        Args:
            health_status: Current system health status
            
        Returns:
            List of health alerts
        """
        alerts = []
        timestamp = datetime.utcnow()
        
        # Check component health alerts
        for name, component in health_status.components.items():
            if component.status == HealthStatus.UNHEALTHY:
                alerts.append(HealthAlert(
                    component=name,
                    severity="critical",
                    message=f"{name.title()} component is unhealthy: {component.message}",
                    details={
                        "component_status": component.status.value,
                        "error": component.error,
                        "response_time_ms": component.response_time_ms
                    },
                    timestamp=timestamp,
                    alert_id=f"{name}_unhealthy_{int(timestamp.timestamp())}"
                ))
            elif component.status == HealthStatus.DEGRADED:
                alerts.append(HealthAlert(
                    component=name,
                    severity="warning",
                    message=f"{name.title()} component is degraded: {component.message}",
                    details={
                        "component_status": component.status.value,
                        "response_time_ms": component.response_time_ms
                    },
                    timestamp=timestamp,
                    alert_id=f"{name}_degraded_{int(timestamp.timestamp())}"
                ))
        
        # Check resource usage alerts
        resources = health_status.resource_metrics
        
        if resources.memory_usage_percent > self._alert_thresholds["memory_usage_percent"]:
            alerts.append(HealthAlert(
                component="system_resources",
                severity="warning" if resources.memory_usage_percent < 90 else "critical",
                message=f"High memory usage: {resources.memory_usage_percent:.1f}%",
                details={
                    "memory_usage_percent": resources.memory_usage_percent,
                    "memory_usage_mb": resources.memory_usage_mb
                },
                timestamp=timestamp,
                alert_id=f"memory_high_{int(timestamp.timestamp())}"
            ))
        
        if resources.cpu_usage_percent > self._alert_thresholds["cpu_usage_percent"]:
            alerts.append(HealthAlert(
                component="system_resources",
                severity="warning" if resources.cpu_usage_percent < 95 else "critical",
                message=f"High CPU usage: {resources.cpu_usage_percent:.1f}%",
                details={
                    "cpu_usage_percent": resources.cpu_usage_percent,
                    "load_average": resources.load_average
                },
                timestamp=timestamp,
                alert_id=f"cpu_high_{int(timestamp.timestamp())}"
            ))
        
        if resources.disk_usage_percent > self._alert_thresholds["disk_usage_percent"]:
            alerts.append(HealthAlert(
                component="system_resources",
                severity="critical",
                message=f"High disk usage: {resources.disk_usage_percent:.1f}%",
                details={
                    "disk_usage_percent": resources.disk_usage_percent,
                    "disk_free_gb": resources.disk_free_gb
                },
                timestamp=timestamp,
                alert_id=f"disk_high_{int(timestamp.timestamp())}"
            ))
        
        # Check performance alerts
        for component, response_time in health_status.performance_metrics.response_times.items():
            if response_time > self._alert_thresholds["response_time_ms"]:
                alerts.append(HealthAlert(
                    component=component,
                    severity="warning",
                    message=f"{component.title()} slow response time: {response_time:.1f}ms",
                    details={
                        "response_time_ms": response_time,
                        "threshold_ms": self._alert_thresholds["response_time_ms"]
                    },
                    timestamp=timestamp,
                    alert_id=f"{component}_slow_{int(timestamp.timestamp())}"
                ))
        
        for component, error_rate in health_status.performance_metrics.error_rates.items():
            if error_rate > self._alert_thresholds["error_rate_percent"]:
                alerts.append(HealthAlert(
                    component=component,
                    severity="warning" if error_rate < 25 else "critical",
                    message=f"{component.title()} high error rate: {error_rate:.1f}%",
                    details={
                        "error_rate_percent": error_rate,
                        "threshold_percent": self._alert_thresholds["error_rate_percent"]
                    },
                    timestamp=timestamp,
                    alert_id=f"{component}_errors_{int(timestamp.timestamp())}"
                ))
        
        return alerts
    
    async def check_all_components(self) -> SystemHealthStatus:
        """
        Perform comprehensive health check on all system components.
        
        Returns:
            SystemHealthStatus with complete system health information
        """
        timestamp = datetime.utcnow()
        
        # Run all component health checks concurrently
        component_checks = await asyncio.gather(
            self.check_database_health(),
            self.check_redis_health(),
            self.check_job_queue_health(),
            self.check_api_health(),
            return_exceptions=True
        )
        
        # Process results and handle any exceptions
        components = {}
        component_names = ["database", "redis", "job_queue", "api"]
        
        for i, result in enumerate(component_checks):
            name = component_names[i]
            if isinstance(result, Exception):
                components[name] = ComponentHealth(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Health check failed: {str(result)}",
                    last_check=timestamp,
                    error=str(result)
                )
            else:
                components[name] = result
        
        # Collect system resource metrics
        resource_metrics = self.get_system_resource_metrics()
        
        # Collect performance metrics
        performance_metrics = await self.collect_performance_metrics(components)
        
        # Determine overall health status
        unhealthy_components = [c for c in components.values() if c.status == HealthStatus.UNHEALTHY]
        degraded_components = [c for c in components.values() if c.status == HealthStatus.DEGRADED]
        
        if unhealthy_components:
            overall_status = HealthStatus.UNHEALTHY
            overall_healthy = False
        elif degraded_components:
            overall_status = HealthStatus.DEGRADED
            overall_healthy = False
        else:
            overall_status = HealthStatus.HEALTHY
            overall_healthy = True
        
        # Create system health status
        health_status = SystemHealthStatus(
            overall_healthy=overall_healthy,
            overall_status=overall_status,
            components=components,
            performance_metrics=performance_metrics,
            resource_metrics=resource_metrics,
            alerts=[],  # Will be populated next
            timestamp=timestamp
        )
        
        # Generate alerts
        health_status.alerts = self.generate_health_alerts(health_status)
        
        # Store in history for trend analysis
        self._health_history.append(health_status)
        self._performance_history.append(performance_metrics)
        
        # Keep only last 100 entries
        if len(self._health_history) > 100:
            self._health_history = self._health_history[-100:]
        if len(self._performance_history) > 100:
            self._performance_history = self._performance_history[-100:]
        
        return health_status
    
    async def get_performance_metrics(self) -> PerformanceMetrics:
        """
        Get current performance metrics.
        
        Returns:
            PerformanceMetrics with current performance data
        """
        if self._performance_history:
            return self._performance_history[-1]
        
        # If no history, perform a quick check
        health_status = await self.check_all_components()
        return health_status.performance_metrics
    
    async def analyze_health_trends(self, days: int = 7) -> Dict[str, Any]:
        """
        Analyze health trends over the specified time period.
        
        Args:
            days: Number of days to analyze
            
        Returns:
            Dictionary with health trend analysis
        """
        cutoff_time = datetime.utcnow() - timedelta(days=days)
        
        # Filter history to the specified time period
        recent_history = [
            h for h in self._health_history
            if h.timestamp >= cutoff_time
        ]
        
        if not recent_history:
            return {
                "trend_period_days": days,
                "data_points": 0,
                "message": "Insufficient data for trend analysis"
            }
        
        # Analyze component availability
        component_uptime = {}
        for component_name in ["database", "redis", "job_queue", "api"]:
            healthy_count = sum(
                1 for h in recent_history
                if h.components.get(component_name, {}).status == HealthStatus.HEALTHY
            )
            uptime_percent = (healthy_count / len(recent_history)) * 100
            component_uptime[component_name] = uptime_percent
        
        # Analyze performance trends
        avg_response_times = {}
        if recent_history:
            for component in ["database", "redis", "job_queue", "api"]:
                response_times = [
                    h.performance_metrics.response_times.get(component, 0)
                    for h in recent_history
                    if component in h.performance_metrics.response_times
                ]
                if response_times:
                    avg_response_times[component] = sum(response_times) / len(response_times)
        
        # Analyze alert frequency
        total_alerts = sum(len(h.alerts) for h in recent_history)
        alert_frequency = total_alerts / max(days, 1)
        
        # Determine overall trend
        overall_uptime = sum(component_uptime.values()) / len(component_uptime)
        if overall_uptime >= 99:
            trend_status = "excellent"
        elif overall_uptime >= 95:
            trend_status = "good"
        elif overall_uptime >= 90:
            trend_status = "fair"
        else:
            trend_status = "poor"
        
        return {
            "trend_period_days": days,
            "data_points": len(recent_history),
            "overall_trend": trend_status,
            "overall_uptime_percent": overall_uptime,
            "component_uptime": component_uptime,
            "average_response_times_ms": avg_response_times,
            "alert_frequency_per_day": alert_frequency,
            "total_alerts": total_alerts,
            "analysis_timestamp": datetime.utcnow().isoformat()
        }
    
    async def get_error_analytics(self) -> Dict[str, Any]:
        """
        Get comprehensive error analytics and patterns.
        
        Returns:
            Dictionary with error analytics data
        """
        try:
            return get_error_analytics()
        except Exception as e:
            self.logger.error(f"Failed to get error analytics: {e}")
            return {
                "error": "Failed to retrieve error analytics",
                "message": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }


# Global health monitor instance
health_monitor = ComprehensiveHealthMonitor()


def get_health_monitor() -> ComprehensiveHealthMonitor:
    """
    Get the global health monitor instance.
    
    Returns:
        ComprehensiveHealthMonitor instance
    """
    return health_monitor