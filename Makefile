.PHONY: help install dev test lint format clean run

help:  ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install production dependencies
	pip install -r requirements.txt

dev:  ## Install development dependencies and setup
	pip install -r requirements.txt
	pip install -e .

test:  ## Run tests
	pytest -v

test-cov:  ## Run tests with coverage
	pytest --cov=app --cov-report=html --cov-report=term

lint:  ## Run linting checks
	black --check app/ tests/
	isort --check-only app/ tests/
	mypy app/

format:  ## Format code
	black app/ tests/
	isort app/ tests/

clean:  ## Clean up temporary files
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf htmlcov/
	rm -rf dist/
	rm -rf build/
	rm -rf *.egg-info/

run:  ## Run the development server
	python -m app.main

run-prod:  ## Run with uvicorn in production mode
	uvicorn app.main:app --host 0.0.0.0 --port 8000

docker-build:  ## Build Docker image
	docker build -t spec-documentation-api .

docker-run:  ## Run Docker container
	docker run -p 8000:8000 --env-file .env spec-documentation-api

worker:  ## Run Celery worker for job processing
	python -m app.jobs.worker

worker-dev:  ## Run Celery worker in development mode with auto-reload
	watchmedo auto-restart --directory=./app --pattern=*.py --recursive -- python -m app.jobs.worker

beat:  ## Run Celery beat scheduler for periodic tasks
	celery -A app.jobs.celery_app beat --loglevel=info

monitor:  ## Run Celery flower for monitoring
	celery -A app.jobs.celery_app flower

jobs:  ## Show job management CLI help
	python -m app.jobs.cli --help

redis:  ## Start Redis server (requires Redis installation)
	redis-server