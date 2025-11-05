"""
Celery application configuration for async job processing.
"""
import logging
from celery import Celery
from app.core.config import settings

logger = logging.getLogger(__name__)

# Create Celery app instance
celery_app = Celery(
    "spec_documentation_api",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.jobs.tasks"]
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    # Worker settings
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    worker_disable_rate_limits=False,
    
    # Task routing and execution
    task_routes={
        "app.jobs.tasks.generate_documentation": {"queue": "documentation"},
        "app.jobs.tasks.calculate_quality_score": {"queue": "quality"},
    },
    
    # Result backend settings
    result_expires=3600,  # 1 hour
    result_backend_transport_options={
        "master_name": "mymaster",
        "visibility_timeout": 3600,
    },
    
    # Task execution settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=settings.JOB_TIMEOUT,
    task_soft_time_limit=settings.JOB_TIMEOUT - 60,
    
    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,
)

# Configure logging for Celery
celery_app.conf.worker_log_format = "[%(asctime)s: %(levelname)s/%(processName)s] %(message)s"
celery_app.conf.worker_task_log_format = "[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s"

logger.info("Celery app configured successfully")