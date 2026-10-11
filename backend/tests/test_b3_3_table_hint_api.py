"""B3-3 — illegal table_hint must be a 4xx validation error, not a 500.

The orchestrator raises ``ValueError`` for an illegal ``table_hint``;
the API boundary must convert that into a stable 4xx validation error
before the generator is ever invoked (no SQL-generation side effects),
while direct orchestrator calls keep their clear ValueError contract.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.core.nl2sql import NL2SQLGenerator

client = TestClient(app)


class TestB3_3_TableHintValidation:
    def test_valid_hint_succeeds(self):
        response = client.post(
            "/api/nl2sql",
            json={
                "text": "查询所有用户",
                "dialect": "mysql",
                "table_hint": "employees",
            },
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    def test_valid_dotted_hint_succeeds(self):
        response = client.post(
            "/api/nl2sql",
            json={
                "text": "查询所有用户",
                "dialect": "mysql",
                "table_hint": "hr.employees",
            },
        )
        assert response.status_code == 200

    @pytest.mark.parametrize(
        "bad_hint",
        [
            "bad table!",        # space + punctuation
            "users; DROP TABLE x",  # SQL injection attempt
            "1users",            # leading digit
            "users--",           # comment marker
            "users' OR '1'='1",  # quote injection
        ],
    )
    def test_illegal_hint_is_4xx(self, bad_hint):
        response = client.post(
            "/api/nl2sql",
            json={
                "text": "查询所有用户",
                "dialect": "mysql",
                "table_hint": bad_hint,
            },
        )
        assert 400 <= response.status_code < 500, (
            f"hint {bad_hint!r} must be a 4xx, got {response.status_code}: "
            f"{response.text[:200]}"
        )
        # The API's HTTPException envelope carries the message under
        # error.message (see custom_http_exception_handler).
        payload = response.json()
        message = (
            payload.get("error", {}).get("message", "")
            if isinstance(payload.get("error"), dict)
            else str(payload.get("error", ""))
        )
        assert "table_hint" in message

    def test_illegal_hint_does_not_invoke_generator(self, monkeypatch):
        """Rejection must happen at the boundary — the generator must not
        be called at all (no side effects)."""
        called = []

        def fake_generate(*args, **kwargs):
            called.append(args)
            raise AssertionError("generator must not be invoked")

        monkeypatch.setattr(NL2SQLGenerator, "generate", fake_generate)
        response = client.post(
            "/api/nl2sql",
            json={
                "text": "查询所有用户",
                "dialect": "mysql",
                "table_hint": "users; DROP TABLE x",
            },
        )
        assert response.status_code == 400
        assert called == []

    def test_direct_orchestrator_valueerror_contract(self):
        """The orchestrator keeps its explicit ValueError contract for
        direct callers."""
        generator = NL2SQLGenerator()
        with pytest.raises(ValueError, match="table_hint"):
            generator.generate("查询所有用户", "mysql", table_hint="bad table!")
