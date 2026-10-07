#!/usr/bin/env python3
"""Regression tests: parser/validate length gating and env-override contract.

Guards the Phase 2 fixes:

- ``constants.VERSION`` must re-export the canonical metadata version
  (the old hardcoded "1.0.0" drifted from the 1.1.0 release).
- The parser must NOT read ``SDM_PARSER_MAX_SQL_LENGTH`` directly via
  ``os.getenv``; it must honor the canonical ``settings`` object.
- ``settings.parser_max_sql_length`` / ``nl2sql_max_input_length`` must
  honor ``SDM_``-prefixed env overrides.
- ``parse()`` and ``validate()`` must apply the same max-length gate.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

from backend.core import constants, metadata  # noqa: E402


class TestConstantsVersionDrift:
    """constants.VERSION must never diverge from canonical metadata again."""

    def test_constants_version_matches_metadata(self) -> None:
        assert constants.VERSION == metadata.PROJECT_VERSION

    def test_constants_version_not_stale_100(self) -> None:
        assert constants.VERSION != "1.0.0"

    def test_pyproject_matches_metadata(self) -> None:
        import tomllib

        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        version = tomllib.loads(pyproject)["project"]["version"]
        assert version == metadata.PROJECT_VERSION


class TestParserNoDirectEnvRead:
    """The parser must not bypass settings with a direct os.getenv()."""

    def test_parser_source_has_no_os_getenv(self) -> None:
        text = (ROOT / "backend" / "core" / "parser.py").read_text(encoding="utf-8")
        assert "os.getenv" not in text, (
            "parser.py must read limits from settings, not os.getenv"
        )


class TestEnvOverrideThroughSettings:
    """SDM_ env vars must reach parser/validate via AppSettings only."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SDM_PARSER_MAX_SQL_LENGTH", raising=False)
        monkeypatch.delenv("SDM_NL2SQL_MAX_INPUT_LENGTH", raising=False)

    def test_settings_default_parser_max(self) -> None:
        from backend.core.config import AppSettings

        assert AppSettings().parser_max_sql_length == 100000

    def test_settings_honors_sdmparser_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.core.config import AppSettings

        monkeypatch.setenv("SDM_PARSER_MAX_SQL_LENGTH", "500")
        assert AppSettings().parser_max_sql_length == 500

    def test_settings_honors_nl2sql_input_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.core.config import AppSettings

        monkeypatch.setenv("SDM_NL2SQL_MAX_INPUT_LENGTH", "1234")
        assert AppSettings().nl2sql_max_input_length == 1234

    def test_parse_rejects_overlength(self) -> None:
        from backend.core.parser import SQLParser

        p = SQLParser(dialect="postgres")
        sql = "SELECT 1" + " " * 10
        # Default max is 100000; craft a just-over-limit input via a small
        # settings patch would be required — instead assert behavior under
        # the live settings value.
        limit = len("SELECT 1")
        # Build an SQL that respects the parser but is longer than settings.
        big_sql = "SELECT " + ", ".join(f"c{i}" for i in range(20000))
        result = p.parse(big_sql)
        assert result.success is False
        assert "exceeds maximum length" in result.error

    def test_validate_matches_parse_length_gate(self) -> None:
        """validate() and parse() must agree on the max-length boundary."""
        from backend.core.parser import SQLParser

        p = SQLParser(dialect="postgres")
        ok_sql = "SELECT 1"
        ok_parse = p.parse(ok_sql)
        ok_valid, _ = p.validate(ok_sql)
        assert ok_parse.success is True
        assert ok_valid is True

        # Both should reject the same over-length input identically.
        big_sql = "SELECT " + ", ".join(f"c{i}" for i in range(20000))
        p_res = p.parse(big_sql)
        v_res, v_err = p.validate(big_sql)
        assert p_res.success is False
        assert v_res is False
        assert p_res.error == v_err


class TestFrontendEntrypointVersion:
    """The app entrypoint must not claim a release v2.0.

    The sidebar "Frontend vN" label is the frontend *architecture*
    generation (intentionally separate from the product release), while
    the footer must show the canonical product version.
    """

    @staticmethod
    def _entrypoint_text() -> str:
        return (ROOT / "sdm_local_v2.py").read_text(encoding="utf-8")

    def test_sidebar_uses_frontend_arch_version_not_release(self) -> None:
        text = self._entrypoint_text()
        assert "Frontend v{_meta.FRONTEND_ARCHITECTURE_VERSION}" in text
        assert "v2.0 · Developer Workspace" not in text

    def test_footer_uses_canonical_product_version(self) -> None:
        text = self._entrypoint_text()
        assert "SQL Dialect Master v2.0" not in text
        assert "SQL Dialect Master v{_meta.PROJECT_VERSION}" in text

    def test_no_stale_v2_release_claim_in_entrypoint(self) -> None:
        text = self._entrypoint_text()
        # The literal release-style "v2.0" must be gone from display text.
        assert "v2.0" not in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
