# Spec Documentation API

Automatically generate high-quality documentation from API specifications using GenAI.

## 🚀 Quick Start

### Option 1: Simple Development Setup (Recommended)

This setup uses SQLite and in-memory Redis for the simplest development experience:

```bash
# 1. Clone and navigate to the project
git clone <repository-url>
cd spec-documentation-api

# 2. Run the automated setup (creates virtual environment and installs dependencies)
python scripts/setup_dev.py

# 3. Activate the virtual environment
source venv/bin/activate  # Linux/macOS
# OR: venv\Scripts\activate  # Windows

# 4. Start the development server
uvicorn app.main:app --reload

# 5. Visit the API documentation
open http://localhost:8000/docs
```

**Quick Start Alternative:**
```bash
# One-command startup (handles everything automatically)
./start.sh  # Linux/macOS
# OR: start.bat  # Windows
```

### Option 2: Docker Compose (Full Services)

For a complete setup with PostgreSQL and Redis:

```bash
# 1. Start the services
docker-compose up -d

# 2. Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# OR: venv\Scripts\activate  # Windows

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Set up environment
cp .env.development .env

# 5. Initialize the database
python -c "from app.db.database import init_db; init_db()"

# 6. Start the development server
uvicorn app.main:app --reload
```

### Option 3: Manual Local Setup

Install PostgreSQL and Redis locally:

**macOS:**
```bash
brew install postgresql redis
brew services start postgresql redis
createdb spec_docs
```

**Ubuntu:**
```bash
sudo apt install postgresql redis-server
sudo systemctl start postgresql redis-server
sudo -u postgres createdb spec_docs
```

## 📋 Requirements

- Python 3.8+
- PostgreSQL (optional - SQLite works for development)
- Redis (optional - in-memory fallback available)

## 🛠️ Development

### Environment Configuration

Create a `.env` file (or copy from `.env.development`):

```env
# Database
DATABASE_URL=sqlite:///./spec_docs.db  # or postgresql://user:pass@localhost/spec_docs

# Redis
REDIS_URL=redis://localhost:6379/0

# GenAI Service
GENAI_ENDPOINT_URL=http://localhost:8001/generate
GENAI_API_KEY=your-api-key

# Other settings
DEBUG=true
LOG_LEVEL=DEBUG
```

### Running the Application

```bash
# Development server with auto-reload
uvicorn app.main:app --reload

# Production server
uvicorn app.main:app --host 0.0.0.0 --port 8000

# With Celery worker for job processing
celery -A app.jobs.celery_app worker --loglevel=info
```

### API Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

## 🏗️ Architecture

The application follows a layered architecture:

- **API Layer** (`app/api/`): FastAPI endpoints and request/response models
- **Service Layer** (`app/services/`): Business logic and external service integration
- **Job Layer** (`app/jobs/`): Asynchronous job processing with Celery
- **Data Layer** (`app/db/`): Database models and repositories
- **Core Layer** (`app/core/`): Configuration, logging, and shared utilities

## 📊 Features

- **Multi-format Support**: OpenAPI, GraphQL, JSON Schema
- **Asynchronous Processing**: Background job processing with progress tracking
- **Quality Scoring**: Automated documentation quality assessment
- **Team Leaderboards**: Quality rankings and poor performance alerts
- **Rate Limiting**: API protection with Redis-based rate limiting
- **Comprehensive Error Handling**: Structured error responses with detailed context
- **Health Monitoring**: System health checks and metrics

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app

# Run specific test file
pytest tests/test_api.py
```

## 📦 Dependencies

Key dependencies:
- **FastAPI**: Modern web framework
- **SQLAlchemy**: Database ORM
- **Celery**: Distributed task queue
- **Redis**: Caching and job queue
- **Pydantic**: Data validation
- **Alembic**: Database migrations

## 🚀 Deployment

### Docker

```bash
# Build the image
docker build -t spec-docs-api .

# Run with environment variables
docker run -p 8000:8000 --env-file .env spec-docs-api
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Database connection string | `sqlite:///./spec_docs.db` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `GENAI_ENDPOINT_URL` | GenAI service endpoint | `http://localhost:8001/generate` |
| `DEBUG` | Enable debug mode | `false` |
| `LOG_LEVEL` | Logging level | `INFO` |

## 🔧 Troubleshooting

### Common Issues

1. **Database Connection Error**
   ```bash
   # For SQLite (development)
   rm spec_docs.db
   python -c "from app.db.database import init_db; init_db()"
   ```

2. **Redis Connection Error**
   ```bash
   # Check if Redis is running
   redis-cli ping
   
   # Or use in-memory fallback (automatic in development)
   ```

3. **Import Errors**
   ```bash
   # Install missing dependencies
   pip install -r requirements.txt
   ```

### Development Tips

- Use SQLite for local development (no PostgreSQL setup needed)
- The app automatically falls back to in-memory storage if Redis is unavailable
- Enable debug mode for detailed error messages
- Use the `/health` endpoint to check system status

## 📝 API Usage Examples

### Generate Documentation

```bash
# Upload a specification file
curl -X POST "http://localhost:8000/api/v1/generate-docs" \
  -H "Content-Type: multipart/form-data" \
  -F "specification_file=@openapi.yaml" \
  -F "team_id=my-team" \
  -F "service_name=my-api"

# From URL
curl -X POST "http://localhost:8000/api/v1/generate-docs" \
  -H "Content-Type: application/json" \
  -d '{
    "specification_url": "https://api.example.com/openapi.json",
    "team_id": "my-team",
    "service_name": "my-api",
    "output_formats": ["markdown", "html"]
  }'
```

### Check Job Status

```bash
curl "http://localhost:8000/api/v1/jobs/{job_id}"
```

### Download Generated Documentation

```bash
curl "http://localhost:8000/api/v1/jobs/{job_id}/download/markdown" -o documentation.md
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License.

## Features

- Support for OpenAPI, GraphQL, and JSON Schema specifications
- AI-powered documentation generation with quality scoring
- Team leaderboards and quality metrics tracking
- Async processing with job queue management
- Multiple output formats (Markdown, HTML)

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL database
- Redis server
- Access to internal GenAI endpoint

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd spec-documentation-api
```

2. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment:
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. Run the application:
```bash
python -m app.main
```

The API will be available at `http://localhost:8000`

### API Documentation

Once running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Development

### Project Structure

```
app/
├── api/          # API endpoints and routers
├── core/         # Core configuration and utilities
├── db/           # Database models and connections
├── models/       # Pydantic models for request/response
├── services/     # Business logic services
└── utils/        # Utility functions

tests/            # Test files
```

### Running Tests

```bash
pytest
```

### Code Quality

```bash
# Format code
black app/ tests/

# Sort imports
isort app/ tests/

# Type checking
mypy app/
```

## Configuration

Key environment variables:

- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection string  
- `GENAI_ENDPOINT_URL`: Internal GenAI service URL
- `GENAI_API_KEY`: Authentication key for GenAI service

See `.env.example` for complete configuration options.

## License

MIT License