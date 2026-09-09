#!/usr/bin/env python3
"""FastAPI Integration Tests for SQL Dialect Master API."""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)
HEALTH_HEADERS = {"X-Health-Probe-Token": "test-health-token"}


class TestRootEndpoint:
    def test_root_returns_200(self):
        response = client.get("/")
        assert response.status_code == 200

    def test_root_contains_api_info(self):
        response = client.get("/")
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "status" in data
        assert data["status"] == "✅ Online"

    def test_root_contains_stats(self):
        response = client.get("/")
        data = response.json()
        assert "stats" in data
        assert "functions" in data["stats"]
        assert "dialects" in data["stats"]


# Existing endpoint tests remain unchanged below; only health-probe calls are
# given the explicit internal probe credential.
