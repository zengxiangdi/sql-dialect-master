import re

from fastapi.testclient import TestClient

from backend.api.main import API_VERSION, app


client = TestClient(app)


def test_process_time_header_is_non_negative_seconds_with_four_decimals():
    response = client.get("/health")

    assert response.status_code == 200
    process_time = response.headers["X-Process-Time"]
    assert re.fullmatch(r"\d+\.\d{4}s", process_time)
    assert float(process_time[:-1]) >= 0.0


def test_api_version_header_matches_configured_api_version():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-API-Version"] == API_VERSION
