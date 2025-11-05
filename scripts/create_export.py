#!/usr/bin/env python3
"""
Create an export package of the Spec Documentation API for deployment on another machine.
"""
import os
import zipfile
import shutil
from pathlib import Path
from datetime import datetime

def create_export_package():
    """Create a zip file with all necessary files for deployment."""
    
    # Get current timestamp for unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_filename = f"spec-documentation-api-{timestamp}.zip"
    
    print(f"📦 Creating export package: {export_filename}")
    
    # Files and directories to include
    include_patterns = [
        # Core application
        "app/",
        "alembic/",
        "alembic.ini",
        
        # Configuration and setup
        "requirements.txt",
        "requirements-dev.txt",
        ".env.development",
        "docker-compose.yml",
        "activate_env.sh",
        "activate_env.bat",
        
        # Scripts
        "scripts/",
        
        # Documentation
        "README.md",
        
        # Git ignore (useful for deployment)
        ".gitignore",
    ]
    
    # Files and directories to exclude
    exclude_patterns = [
        "__pycache__/",
        "*.pyc",
        "*.pyo",
        "*.pyd",
        ".Python",
        "env/",
        "venv/",
        ".venv/",
        ".env",
        "*.db",
        "*.sqlite",
        "*.sqlite3",
        ".DS_Store",
        "Thumbs.db",
        "storage/",
        ".pytest_cache/",
        ".coverage",
        "htmlcov/",
        ".kiro/",
        "*.log",
        "celerybeat-schedule",
        "celerybeat.pid",
    ]
    
    def should_exclude(file_path):
        """Check if a file should be excluded."""
        path_str = str(file_path)
        for pattern in exclude_patterns:
            if pattern.endswith("/"):
                if f"/{pattern}" in f"/{path_str}/" or path_str.startswith(pattern):
                    return True
            elif pattern.startswith("*."):
                if path_str.endswith(pattern[1:]):
                    return True
            elif pattern in path_str:
                return True
        return False
    
    # Create the zip file
    with zipfile.ZipFile(export_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        
        # Add files based on include patterns
        for pattern in include_patterns:
            path = Path(pattern)
            
            if path.is_file():
                if not should_exclude(path):
                    print(f"  📄 Adding file: {path}")
                    zipf.write(path, path)
            elif path.is_dir():
                for root, dirs, files in os.walk(path):
                    # Filter out excluded directories
                    dirs[:] = [d for d in dirs if not should_exclude(Path(root) / d)]
                    
                    for file in files:
                        file_path = Path(root) / file
                        if not should_exclude(file_path):
                            print(f"  📄 Adding: {file_path}")
                            zipf.write(file_path, file_path)
            else:
                print(f"  ⚠️  Skipping missing: {pattern}")
        
        # Add a deployment guide
        deployment_guide = """# Spec Documentation API - Deployment Guide

## Quick Start

1. **Extract the files:**
   ```bash
   unzip spec-documentation-api-*.zip
   cd spec-documentation-api/
   ```

2. **Choose your setup method:**

   ### Option A: Simple Development Setup (SQLite + In-memory Redis)
   ```bash
   # Create and activate virtual environment
   python -m venv venv
   source venv/bin/activate  # Linux/macOS
   # OR: venv\\Scripts\\activate  # Windows
   
   # Install dependencies
   pip install -r requirements-dev.txt
   
   # Set up environment
   cp .env.development .env
   
   # Run setup script
   python scripts/setup_dev.py
   
   # Start the server
   uvicorn app.main:app --reload
   ```

   ### Option B: Full Setup with Docker
   ```bash
   # Create and activate virtual environment
   python -m venv venv
   source venv/bin/activate  # Linux/macOS
   # OR: venv\\Scripts\\activate  # Windows
   
   # Install all dependencies
   pip install -r requirements.txt
   
   # Start PostgreSQL and Redis
   docker-compose up -d postgres redis
   
   # Set up environment
   cp .env.development .env
   # Edit .env to use: DATABASE_URL=postgresql://spec_user:spec_password@localhost/spec_docs
   
   # Initialize database
   python -c "from app.db.database import init_db; init_db()"
   
   # Start the server
   uvicorn app.main:app --reload
   ```

   ### Option C: Manual Installation
   ```bash
   # Install PostgreSQL and Redis locally
   # macOS: brew install postgresql redis && brew services start postgresql redis
   # Ubuntu: sudo apt install postgresql redis-server
   
   # Install Python dependencies
   pip install -r requirements.txt
   
   # Create database
   createdb spec_docs  # or sudo -u postgres createdb spec_docs
   
   # Set up environment
   cp .env.development .env
   # Edit DATABASE_URL in .env if needed
   
   # Initialize database
   python -c "from app.db.database import init_db; init_db()"
   
   # Start the server
   uvicorn app.main:app --reload
   ```

3. **Verify the setup:**
   ```bash
   # Test the setup
   python scripts/test_setup.py
   
   # Visit the API documentation
   open http://localhost:8000/docs
   ```

## Production Deployment

For production deployment:

1. Set environment variables:
   ```bash
   export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
   export REDIS_URL="redis://host:6379/0"
   export GENAI_ENDPOINT_URL="https://your-genai-service.com/generate"
   export GENAI_API_KEY="your-api-key"
   export DEBUG=false
   ```

2. Use a production WSGI server:
   ```bash
   pip install gunicorn
   gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
   ```

3. Set up Celery worker for job processing:
   ```bash
   celery -A app.jobs.celery_app worker --loglevel=info
   ```

## Troubleshooting

- **Database issues**: Use SQLite for development (`DATABASE_URL=sqlite:///./spec_docs.db`)
- **Redis issues**: The app automatically falls back to in-memory storage
- **Import errors**: Install missing dependencies with `pip install -r requirements.txt`
- **Permission errors**: Make sure scripts are executable: `chmod +x scripts/*.py`

## Support

Check the README.md file for detailed documentation and troubleshooting tips.
"""
        
        zipf.writestr("DEPLOYMENT.md", deployment_guide)
        
        # Add a simple startup script
        startup_script = """#!/bin/bash
# Simple startup script for Spec Documentation API

echo "🚀 Starting Spec Documentation API..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "📋 Creating .env from template..."
    cp .env.development .env
fi

# Set up virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv || python -m venv venv
    if [ $? -ne 0 ]; then
        echo "❌ Failed to create virtual environment"
        echo "   Make sure Python 3.8+ is installed"
        exit 1
    fi
fi

# Activate virtual environment
echo "🐍 Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "🔧 Upgrading pip..."
pip install --upgrade pip

# Install dependencies
if [ -f "requirements-dev.txt" ]; then
    echo "📦 Installing dependencies..."
    pip install -r requirements-dev.txt
else
    echo "❌ requirements-dev.txt not found"
    exit 1
fi

# Run setup script
echo "🔧 Running setup..."
python scripts/setup_dev.py

# Start the server
echo "🌟 Starting server at http://localhost:8000"
echo "📖 API docs will be available at http://localhost:8000/docs"
echo "🛑 Press Ctrl+C to stop the server"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""
        zipf.writestr("start.sh", startup_script)
        
        # Add Windows batch file
        windows_script = """@echo off
echo Starting Spec Documentation API...

REM Check if .env exists
if not exist .env (
    echo Creating .env from template...
    copy .env.development .env
)

REM Set up virtual environment if it doesn't exist
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo Failed to create virtual environment
        echo Make sure Python 3.8+ is installed
        pause
        exit /b 1
    )
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\\Scripts\\activate.bat

REM Upgrade pip
echo Upgrading pip...
pip install --upgrade pip

REM Install dependencies
if exist requirements-dev.txt (
    echo Installing dependencies...
    pip install -r requirements-dev.txt
) else (
    echo requirements-dev.txt not found
    pause
    exit /b 1
)

REM Run setup script
echo Running setup...
python scripts\\setup_dev.py

REM Start the server
echo Starting server at http://localhost:8000
echo API docs will be available at http://localhost:8000/docs
echo Press Ctrl+C to stop the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""
        zipf.writestr("start.bat", windows_script)
    
    print(f"✅ Export package created: {export_filename}")
    print(f"📊 Package size: {os.path.getsize(export_filename) / 1024 / 1024:.1f} MB")
    
    print(f"\n📋 Instructions for the target machine:")
    print(f"1. Transfer {export_filename} to the target machine")
    print(f"2. Extract: unzip {export_filename}")
    print(f"3. Run: chmod +x start.sh && ./start.sh  (Linux/macOS)")
    print(f"   Or: start.bat  (Windows)")
    print(f"4. Visit: http://localhost:8000/docs")
    
    return export_filename

if __name__ == "__main__":
    create_export_package()