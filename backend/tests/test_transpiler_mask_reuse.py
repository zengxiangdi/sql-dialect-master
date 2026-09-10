from backend.core.config import settings
from backend.core.transpiler import SQLTranspiler


def test_security_and_warning_paths_reuse_masked_sql(monkeypatch):
    monkeypatch.setattr(settings, "security_check_enabled", True)
    monkeypatch.setattr(settings, "security_block_dangerous", False)

    transpiler = SQLTranspiler()
    calls = []
    original_mask = transpiler.transpile.__globals__["mask_non_executable"]

    def spy_mask(sql):
        calls.append(sql)
        return original_mask(sql)

    monkeypatch.setitem(transpiler.transpile.__globals__, "mask_non_executable", spy_mask)

    result = transpiler.transpile("SELECT * FROM users", "mysql", "postgres")

    assert result.success is True
    assert len(calls) == 1


def test_security_helpers_still_mask_when_called_directly(monkeypatch):
    transpiler = SQLTranspiler()
    calls = []
    original_mask = transpiler.transpile.__globals__["mask_non_executable"]

    def spy_mask(sql):
        calls.append(sql)
        return original_mask(sql)

    monkeypatch.setitem(transpiler.transpile.__globals__, "mask_non_executable", spy_mask)

    transpiler._validate_security("SELECT 1")
    transpiler._generate_warnings("SELECT 1", "mysql", "postgres")

    assert len(calls) == 2
