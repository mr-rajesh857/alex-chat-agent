import pytest
from contextlib import asynccontextmanager
from unittest.mock import patch

@asynccontextmanager
async def mock_lifespan(app):
    yield

@pytest.fixture(autouse=True)
def override_lifespan():
    with patch("app.main.lifespan", mock_lifespan):
        yield
