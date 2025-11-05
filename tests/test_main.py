"""
Basic tests for the main application setup.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


def test_health_check(client):
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "spec-documentation-api"


def test_app_creation():
    """Test that the FastAPI app is created correctly."""
    assert app.title == "Spec Documentation API"
    assert app.version == "1.0.0"