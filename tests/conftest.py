import os
from dataclasses import replace

# Must precede importing app.main. Tests never read a developer .env.
os.environ["DIACRITIZER_SKIP_DOTENV"] = "1"

import pytest
from fastapi.testclient import TestClient

from app.config import Endpoint, Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings("test-key", "old-key", Endpoint("primary", "https://primary.test/v1", "secret", "model", 1, 2),
                    Endpoint("fallback", "https://fallback.test/v1", "other", "second", 2, 4),
                    True, 1, 0, 5000, tmp_path / "corrections.db")


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def headers():
    return {"X-Service-Key": "test-key"}


@pytest.fixture
def real_settings(settings):
    return replace(settings, fake=False)
