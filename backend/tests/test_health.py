from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
import pytest

# Patch database engine before importing app
with patch("app.db.session.engine.begin") as mock_begin, patch("app.db.session.engine.dispose") as mock_dispose:
    mock_begin.return_value.__aenter__ = AsyncMock()
    mock_begin.return_value.__aexit__ = AsyncMock()
    mock_dispose.return_value = AsyncMock()
    from app.main import app

client = TestClient(app)

def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "online"

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
