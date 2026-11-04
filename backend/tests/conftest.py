"""Pytest fixtures and helpers."""
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("OLLAMA_URL", "http://localhost:11434")
os.environ.setdefault("OLLAMA_MODEL", "kimi-k2.7-code:cloud")
os.environ.setdefault("BEE_ADMIN_USERNAME", "admin")
os.environ.setdefault("BEE_ADMIN_PASSWORD_HASH", "$2b$12$0D9F1qZzPt1fqsQvQ6T0F.2sF3aXbYvQhQmRnQkTqQmRnQkTqQmR")
os.environ.setdefault("BEE_SECRET_KEY", "test-secret-key")

from main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_cookies(client):
    resp = client.post("/api/v1/login", data={"username": "admin", "password": "invalid"})
    return {}
