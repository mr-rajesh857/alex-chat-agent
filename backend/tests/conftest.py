import pytest
from unittest.mock import patch, AsyncMock

@pytest.fixture(autouse=True)
def mock_db_engine():
    with patch("app.db.session.engine.begin") as mock_begin, \
         patch("app.db.session.engine.dispose") as mock_dispose:
        mock_begin.return_value.__aenter__ = AsyncMock()
        mock_begin.return_value.__aexit__ = AsyncMock()
        mock_dispose.return_value = AsyncMock()
        yield
