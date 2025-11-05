# Job Management and Async Processing

This module provides comprehensive job management and async processing capabilities for the Spec Documentation API.

## Components

### Core Components

- **`celery_app.py`**: Celery application configuration and setup
- **`job_manager.py`**: Core job lifecycle management and Redis integration
- **`status_tracker.py`**: Job status tracking and progress monitoring
- **`job_service.py`**: High-level service combining job management and tracking
- **`tasks.py`**: Celery task definitions for documentation generation
- **`models.py`**: Pydantic models for job-related data structures

### Utilities

- **`worker.py`**: Celery worker entry point
- **`cli.py`**: Command-line interface for job management
- **`README.md`**: This documentation file

## Features

### Job Queue System
- Redis-based job queue using Celery
- Background worker processes for job execution
- Support for multiple job types (documentation, quality scoring)
- Configurable concurrency and timeout settings

### Job Status Tracking
- Real-time job progress tracking
- Job lifecycle management (queued → processing → completed/failed)
- Estimated completion times based on queue status and historical data
- Comprehensive job history and statistics

### Monitoring and Management
- CLI tools for job inspection and management
- Health checks for system components
- Queue status monitoring
- Team performance analytics

## Usage

### Starting Workers

```bash
# Start a worker process
make worker

# Start worker in development mode with auto-reload
make worker-dev

# Start beat scheduler for periodic tasks
make beat

# Start Flower monitoring interface
make monitor
```

### Job Management CLI

```bash
# List recent jobs
python -m app.jobs.cli list-jobs

# Show active jobs
python -m app.jobs.cli active

# Get job status
python -m app.jobs.cli status <job-id>

# Cancel a job
python -m app.jobs.cli cancel <job-id>

# Show statistics
python -m app.jobs.cli stats --team-id team-a --days 7

# Check queue status
python -m app.jobs.cli queue

# Health check
python -m app.jobs.cli health
```

### Programmatic Usage

```python
from app.jobs.job_service import job_service
from app.jobs.models import JobRequest, SpecFormat, OutputFormat

# Submit a job
job_request = JobRequest(
    specification={"openapi": "3.0.0", ...},
    spec_format=SpecFormat.OPENAPI,
    output_formats=[OutputFormat.MARKDOWN, OutputFormat.HTML],
    team_id="platform-team",
    service_name="user-api"
)

job_result = await job_service.submit_documentation_job(job_request)

# Check job status
status = await job_service.get_job_status(job_result.job_id)

# Get job history
history = await job_service.get_job_history(team_id="platform-team")
```

## Configuration

Key configuration options in `app/core/config.py`:

- `REDIS_URL`: Redis connection URL for job queue
- `MAX_CONCURRENT_JOBS`: Maximum number of concurrent jobs
- `JOB_TIMEOUT`: Job timeout in seconds
- `GENAI_TIMEOUT`: GenAI request timeout

## Job Flow

1. **Job Submission**: Client submits specification via API
2. **Queue**: Job is queued in Redis with unique ID
3. **Processing**: Worker picks up job and processes in steps:
   - Parse specification
   - Generate documentation using GenAI
   - Format output (Markdown/HTML)
   - Calculate quality score
   - Store results
4. **Completion**: Job marked as completed with results available

## Error Handling

- Automatic retry logic for transient failures
- Comprehensive error logging and reporting
- Graceful degradation when external services are unavailable
- Job cancellation support for long-running tasks

## Monitoring

- Real-time progress tracking with step-by-step updates
- Queue depth and processing time metrics
- System health checks for Redis and database connectivity
- Team performance analytics and quality trends