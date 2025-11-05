"""
Command-line interface for job management operations.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

import click
from app.jobs.job_service import job_service
from app.core.logging import setup_logging

# Set up logging
setup_logging()
logger = logging.getLogger(__name__)


@click.group()
def cli():
    """Job management CLI for Spec Documentation API."""
    pass


@cli.command()
@click.option("--team-id", help="Filter by team ID")
@click.option("--service-name", help="Filter by service name")
@click.option("--limit", default=20, help="Maximum number of jobs to show")
def list_jobs(team_id: Optional[str], service_name: Optional[str], limit: int):
    """List recent jobs with optional filtering."""
    async def _list_jobs():
        jobs = await job_service.get_job_history(
            team_id=team_id,
            service_name=service_name,
            limit=limit
        )
        
        if not jobs:
            click.echo("No jobs found.")
            return
        
        click.echo(f"{'Job ID':<36} {'Status':<12} {'Team':<15} {'Service':<20} {'Created':<20}")
        click.echo("-" * 110)
        
        for job in jobs:
            created_str = job.created_at.strftime("%Y-%m-%d %H:%M:%S")
            team_id_display = (job.results.get("team_id", "N/A") if job.results else "N/A")[:14]
            service_display = (job.results.get("service_name", "N/A") if job.results else "N/A")[:19]
            
            click.echo(
                f"{str(job.job_id):<36} {job.status.value:<12} "
                f"{team_id_display:<15} {service_display:<20} {created_str:<20}"
            )
    
    asyncio.run(_list_jobs())


@cli.command()
def active():
    """Show currently active (queued or processing) jobs."""
    async def _active_jobs():
        jobs = await job_service.get_active_jobs()
        
        if not jobs:
            click.echo("No active jobs.")
            return
        
        click.echo(f"{'Job ID':<36} {'Status':<12} {'Progress':<15} {'Created':<20}")
        click.echo("-" * 90)
        
        for job in jobs:
            created_str = job.created_at.strftime("%Y-%m-%d %H:%M:%S")
            progress_str = "N/A"
            
            if job.progress:
                progress_str = f"{job.progress.completed_steps}/{job.progress.total_steps}"
            
            click.echo(
                f"{str(job.job_id):<36} {job.status.value:<12} "
                f"{progress_str:<15} {created_str:<20}"
            )
    
    asyncio.run(_active_jobs())


@cli.command()
@click.argument("job_id")
def status(job_id: str):
    """Get detailed status of a specific job."""
    async def _job_status():
        try:
            job_uuid = UUID(job_id)
            job = await job_service.get_job_status(job_uuid)
            
            if not job:
                click.echo(f"Job {job_id} not found.")
                return
            
            click.echo(f"Job ID: {job.job_id}")
            click.echo(f"Status: {job.status.value}")
            click.echo(f"Created: {job.created_at}")
            
            if job.completed_at:
                click.echo(f"Completed: {job.completed_at}")
                duration = job.completed_at - job.created_at
                click.echo(f"Duration: {duration}")
            
            if job.progress:
                click.echo(f"Progress: {job.progress.completed_steps}/{job.progress.total_steps}")
                click.echo(f"Current Step: {job.progress.current_step}")
                if job.progress.estimated_completion:
                    click.echo(f"Estimated Completion: {job.progress.estimated_completion}")
            
            if job.results:
                click.echo("Results:")
                for key, value in job.results.items():
                    if key != "generated_content":  # Skip large content
                        click.echo(f"  {key}: {value}")
            
            if job.error_message:
                click.echo(f"Error: {job.error_message}")
                
        except ValueError:
            click.echo(f"Invalid job ID format: {job_id}")
    
    asyncio.run(_job_status())


@cli.command()
@click.argument("job_id")
def cancel(job_id: str):
    """Cancel a running or queued job."""
    async def _cancel_job():
        try:
            job_uuid = UUID(job_id)
            success = await job_service.cancel_job(job_uuid)
            
            if success:
                click.echo(f"Job {job_id} cancelled successfully.")
            else:
                click.echo(f"Failed to cancel job {job_id}.")
                
        except ValueError:
            click.echo(f"Invalid job ID format: {job_id}")
    
    asyncio.run(_cancel_job())


@cli.command()
@click.option("--team-id", help="Filter by team ID")
@click.option("--days", default=7, help="Number of days to analyze")
def stats(team_id: Optional[str], days: int):
    """Show job statistics."""
    async def _job_stats():
        stats_data = await job_service.get_job_statistics(team_id=team_id, days=days)
        
        if not stats_data:
            click.echo("No statistics available.")
            return
        
        click.echo(f"Job Statistics (Last {days} days)")
        if team_id:
            click.echo(f"Team: {team_id}")
        click.echo("-" * 40)
        
        click.echo(f"Total Jobs: {stats_data.get('total_jobs', 0)}")
        click.echo(f"Completed: {stats_data.get('completed_jobs', 0)}")
        click.echo(f"Failed: {stats_data.get('failed_jobs', 0)}")
        click.echo(f"Processing: {stats_data.get('processing_jobs', 0)}")
        click.echo(f"Queued: {stats_data.get('queued_jobs', 0)}")
        click.echo(f"Success Rate: {stats_data.get('success_rate', 0):.1f}%")
        
        if stats_data.get('average_processing_time_seconds'):
            avg_time = stats_data['average_processing_time_seconds']
            click.echo(f"Average Processing Time: {avg_time:.1f} seconds")
        
        quality_stats = stats_data.get('quality_statistics', {})
        if quality_stats:
            click.echo("\nQuality Statistics:")
            click.echo(f"  Average Score: {quality_stats.get('average_overall_score', 0):.1f}")
            click.echo(f"  Min Score: {quality_stats.get('min_score', 0)}")
            click.echo(f"  Max Score: {quality_stats.get('max_score', 0)}")
    
    asyncio.run(_job_stats())


@cli.command()
def queue():
    """Show current queue status."""
    async def _queue_status():
        queue_data = await job_service.get_queue_status()
        
        if not queue_data:
            click.echo("Unable to get queue status.")
            return
        
        click.echo("Queue Status")
        click.echo("-" * 20)
        click.echo(f"Queued Jobs: {queue_data.get('queued_jobs', 0)}")
        click.echo(f"Processing Jobs: {queue_data.get('processing_jobs', 0)}")
        click.echo(f"Max Concurrent: {queue_data.get('max_concurrent_jobs', 0)}")
        click.echo(f"System Load: {queue_data.get('system_load_percentage', 0):.1f}%")
        
        if queue_data.get('oldest_queued_job_age_seconds'):
            age_minutes = queue_data['oldest_queued_job_age_seconds'] / 60
            click.echo(f"Oldest Queued Job: {age_minutes:.1f} minutes ago")
        
        estimated_wait = queue_data.get('estimated_queue_wait_minutes', 0)
        click.echo(f"Estimated Wait Time: {estimated_wait:.1f} minutes")
    
    asyncio.run(_queue_status())


@cli.command()
def health():
    """Check system health."""
    async def _health_check():
        health_data = await job_service.health_check()
        
        overall_status = "HEALTHY" if health_data.get('healthy') else "UNHEALTHY"
        click.echo(f"System Status: {overall_status}")
        click.echo("-" * 30)
        
        redis_status = "OK" if health_data.get('redis_healthy') else "FAILED"
        click.echo(f"Redis: {redis_status}")
        
        db_status = "OK" if health_data.get('database_healthy') else "FAILED"
        click.echo(f"Database: {db_status}")
        
        if health_data.get('error'):
            click.echo(f"Error: {health_data['error']}")
        
        click.echo(f"Timestamp: {health_data.get('timestamp', 'N/A')}")
    
    asyncio.run(_health_check())


if __name__ == "__main__":
    cli()