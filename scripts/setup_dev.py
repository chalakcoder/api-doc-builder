#!/usr/bin/env python3
"""
Development setup script for Spec Documentation API.
"""
import os
import sys
import subprocess
from pathlib import Path

def run_command(command, description):
    """Run a command and handle errors."""
    print(f"🔄 {description}...")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed:")
        print(f"   Command: {command}")
        print(f"   Error: {e.stderr}")
        return False

def install_individual_packages(pip_cmd):
    """Install packages individually as fallback."""
    dependencies = [
        "fastapi==0.104.1",
        "uvicorn[standard]==0.24.0",
        "sqlalchemy==2.0.23",
        "alembic==1.12.1", 
        "pydantic==2.5.0",
        "pydantic-settings==2.1.0",
        "aiohttp==3.9.1",
        "httpx==0.25.2",
        "python-multipart==0.0.6",
        "tenacity==8.2.3",
        "pyyaml==6.0.1",
        "markdown==3.5.1",
        "pygments==2.17.2",
        "jsonschema==4.20.0",
        "openapi-spec-validator==0.7.1",
        "graphql-core==3.2.3"
    ]
    
    # Optional dependencies (don't fail if these don't install)
    optional_dependencies = [
        "redis==5.0.1",
        "celery==5.3.4",
        "psycopg2-binary==2.9.9"
    ]
    
    # Install core dependencies
    for dep in dependencies:
        if not run_command(f"{pip_cmd} install {dep}", f"Installing {dep}"):
            print(f"⚠️  Failed to install {dep}, you may need to install it manually")
    
    # Install optional dependencies (don't fail if they don't work)
    for dep in optional_dependencies:
        print(f"🔄 Installing optional dependency: {dep}...")
        try:
            result = subprocess.run(f"{pip_cmd} install {dep}", shell=True, check=True, capture_output=True, text=True)
            print(f"✅ {dep} installed successfully")
        except subprocess.CalledProcessError:
            print(f"⚠️  Optional dependency {dep} failed to install (this is okay for development)")

def check_redis():
    """Check if Redis is running."""
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, db=0)
        r.ping()
        print("✅ Redis is running")
        return True
    except Exception as e:
        print(f"❌ Redis is not running: {e}")
        return False

def setup_environment():
    """Set up the development environment."""
    print("🚀 Setting up Spec Documentation API for development\n")
    
    # Check if we're in the right directory
    if not Path("app").exists():
        print("❌ Please run this script from the project root directory")
        sys.exit(1)
    
    # Check if we're already in a virtual environment
    in_venv = hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix)
    venv_path = Path("venv")
    
    if not in_venv and not venv_path.exists():
        print("🐍 Creating virtual environment...")
        if not run_command("python -m venv venv", "Creating virtual environment"):
            print("❌ Failed to create virtual environment")
            print("   Make sure you have Python 3.8+ installed")
            sys.exit(1)
        print("✅ Virtual environment created at ./venv")
    elif venv_path.exists() and not in_venv:
        print("📁 Virtual environment found at ./venv")
    elif in_venv:
        print("✅ Already running in a virtual environment")
    
    # Determine pip command based on environment
    if in_venv:
        pip_cmd = "pip"
    elif os.name == 'nt':  # Windows
        pip_cmd = "venv\\Scripts\\pip"
    else:  # Unix/Linux/macOS
        pip_cmd = "venv/bin/pip"
    
    # Upgrade pip in virtual environment
    print("\n🔧 Upgrading pip...")
    run_command(f"{pip_cmd} install --upgrade pip", "Upgrading pip")
    
    # Copy development environment file
    if not Path(".env").exists():
        if Path(".env.development").exists():
            print("📋 Copying .env.development to .env")
            subprocess.run("cp .env.development .env", shell=True)
        else:
            print("⚠️  No .env.development file found, you'll need to create .env manually")
    
    # Install Python dependencies from requirements file
    print("\n📦 Installing Python dependencies...")
    
    # Try requirements-dev.txt first (minimal dependencies)
    if Path("requirements-dev.txt").exists():
        if run_command(f"{pip_cmd} install -r requirements-dev.txt", "Installing development dependencies"):
            print("✅ Development dependencies installed successfully")
        else:
            print("⚠️  Failed to install from requirements-dev.txt, trying individual packages...")
            # Fallback to individual package installation
            install_individual_packages(pip_cmd)
    else:
        # Fallback to individual package installation
        install_individual_packages(pip_cmd)
    
    # Create storage directory
    storage_path = Path("storage")
    if not storage_path.exists():
        storage_path.mkdir()
        print("📁 Created storage directory")
    
    # Determine python command based on environment
    if in_venv:
        python_cmd = "python"
    elif os.name == 'nt':  # Windows
        python_cmd = "venv\\Scripts\\python"
    else:  # Unix/Linux/macOS
        python_cmd = "venv/bin/python"
    
    # Initialize database
    print("\n🗄️  Initializing database...")
    if run_command(f"{python_cmd} -c \"from app.db.database import init_db; init_db()\"", "Database initialization"):
        print("✅ Database initialized successfully")
    else:
        print("⚠️  Database initialization failed, you may need to set it up manually")
    
    # Check Redis
    print("\n🔴 Checking Redis...")
    if not check_redis():
        print("⚠️  Redis is not running. You can:")
        print("   1. Install and start Redis locally:")
        print("      - macOS: brew install redis && brew services start redis")
        print("      - Ubuntu: sudo apt install redis-server && sudo systemctl start redis")
        print("   2. Use Docker: docker run -d -p 6379:6379 redis:7-alpine")
        print("   3. Use Docker Compose: docker-compose up -d redis")
    
    print("\n🎉 Development setup complete!")
    print("\n📋 Next steps:")
    
    if not in_venv:
        if os.name == 'nt':  # Windows
            print("   1. Activate virtual environment: venv\\Scripts\\activate")
        else:  # Unix/Linux/macOS
            print("   1. Activate virtual environment: source venv/bin/activate")
    else:
        print("   1. ✅ Virtual environment already active")
    
    print("   2. Make sure Redis is running (or use in-memory fallback)")
    
    if in_venv:
        print("   3. Start the development server: uvicorn app.main:app --reload")
        print("   4. Or use the test script: python scripts/test_setup.py")
    else:
        if os.name == 'nt':  # Windows
            print("   3. Start the development server: venv\\Scripts\\uvicorn app.main:app --reload")
        else:  # Unix/Linux/macOS
            print("   3. Start the development server: venv/bin/uvicorn app.main:app --reload")
    
    print("   5. Visit http://localhost:8000/docs for the API documentation")
    
    if not in_venv:
        print("\n💡 Pro tip: Always activate the virtual environment before running the application!")
        if os.name == 'nt':  # Windows
            print("   Windows: venv\\Scripts\\activate")
        else:  # Unix/Linux/macOS
            print("   Unix/macOS: source venv/bin/activate")

if __name__ == "__main__":
    setup_environment()