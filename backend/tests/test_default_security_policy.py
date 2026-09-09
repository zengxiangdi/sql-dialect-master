import os
import subprocess
import sys

import pytest

from backend.core import settings
from backend.core.transpiler import SQLTranspiler


def test_dangerous_sql_is_blocked_by_default():
    assert settings.security_check_enabled is True
    assert settings.security_block_dangerous is True

    result = SQLTranspiler().transpile(
        "DROP TABLE users",
        "mysql",
        "postgres",
    )

    assert result.success is False
    assert result.error_code == "SECURITY_VIOLATION"
    assert result.target_sql is None


def test_stacked_statements_are_blocked_by_default():
    result = SQLTranspiler().transpile(
        "SELECT 1; SELECT 2",
        "mysql",
        "postgres",
    )

    assert result.success is False
    assert result.error_code == "SECURITY_VIOLATION"
    assert "Multiple SQL statements" in (result.error or "")


def test_explicit_security_override_is_respected():
    env = os.environ.copy()
    env["SDM_SECURITY_BLOCK_DANGEROUS"] = "false"
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "from backend.core import settings; print(settings.security_block_dangerous)",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert probe.stdout.strip() == "False"


def test_security_bypass_parameter_is_not_supported():
    with pytest.raises(TypeError):
        kwargs = {"skip_security": True}
        SQLTranspiler().transpile(
            "DROP TABLE users",
            "mysql",
            "postgres",
            **kwargs,
        )
