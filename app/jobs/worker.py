"""
Celery worker entry point for running background job processing.
"""
import logging
import sys
from app.jobs.celery_app import celery_app
from app.core.logging import setup_logging

# Set up logging
setup_logging()
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info("Starting Celery worker for documentation generation")
    
    # Configure worker options
    worker_options = [
        "worker",
        "--loglevel=info",
        "--concurrency=4",
        "--queues=documentation,quality",
        "--hostname=worker@%h",
        "--max-tasks-per-child=1000",
        "--time-limit=600",
        "--soft-time-limit=540"
    ]
    
    # Add any command line arguments
    if len(sys.argv) > 1:
        worker_options.extend(sys.argv[1:])
    
    # Start worker
    celery_app.worker_main(worker_options)