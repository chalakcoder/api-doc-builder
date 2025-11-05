"""
Database CLI commands for managing migrations and database operations.
"""
import click
import logging
from typing import Optional

from app.db.database import (
    init_db, 
    check_database_connection, 
    run_migrations,
    get_database_info
)
from app.core.config import settings

logger = logging.getLogger(__name__)


@click.group()
def db():
    """Database management commands."""
    pass


@db.command()
def init():
    """Initialize database with migrations."""
    click.echo("Initializing database...")
    
    try:
        init_db()
        click.echo("✅ Database initialized successfully")
    except Exception as e:
        click.echo(f"❌ Database initialization failed: {e}")
        raise click.Abort()


@db.command()
def migrate():
    """Run database migrations."""
    click.echo("Running database migrations...")
    
    try:
        run_migrations()
        click.echo("✅ Migrations completed successfully")
    except Exception as e:
        click.echo(f"❌ Migration failed: {e}")
        raise click.Abort()


@db.command()
def check():
    """Check database connection and status."""
    click.echo("Checking database connection...")
    
    if check_database_connection():
        click.echo("✅ Database connection successful")
        
        # Get database info
        info = get_database_info()
        if info.get("connected"):
            click.echo(f"Database: {info.get('database')}")
            click.echo(f"Version: {info.get('version', 'Unknown')}")
            click.echo(f"URL: {info.get('url')}")
        else:
            click.echo(f"❌ Database info error: {info.get('error')}")
    else:
        click.echo("❌ Database connection failed")
        raise click.Abort()


@db.command()
@click.option('--url', help='Database URL (overrides config)')
def info(url: Optional[str]):
    """Show database information."""
    if url:
        # Temporarily override settings for this command
        original_url = settings.DATABASE_URL
        settings.DATABASE_URL = url
    
    try:
        info = get_database_info()
        
        if info.get("connected"):
            click.echo("Database Information:")
            click.echo(f"  Status: Connected ✅")
            click.echo(f"  Database: {info.get('database')}")
            click.echo(f"  Version: {info.get('version', 'Unknown')}")
            click.echo(f"  URL: {info.get('url')}")
        else:
            click.echo("Database Information:")
            click.echo(f"  Status: Disconnected ❌")
            click.echo(f"  Error: {info.get('error')}")
    
    finally:
        if url:
            # Restore original URL
            settings.DATABASE_URL = original_url


@db.command()
@click.confirmation_option(prompt='Are you sure you want to reset the database?')
def reset():
    """Reset database (WARNING: This will drop all data)."""
    click.echo("Resetting database...")
    
    try:
        from app.db.models import Base
        from app.db.database import engine
        
        # Drop all tables
        Base.metadata.drop_all(bind=engine)
        click.echo("Dropped all tables")
        
        # Recreate tables
        init_db()
        click.echo("✅ Database reset completed")
        
    except Exception as e:
        click.echo(f"❌ Database reset failed: {e}")
        raise click.Abort()


if __name__ == "__main__":
    db()