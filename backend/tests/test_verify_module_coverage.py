"""Check the module coverage gate at the threshold and with incomplete reports."""

import json
from pathlib import Path

import pytest

from scripts.verify_module_coverage import MODULES, main


@pytest.mark.parametrize(
    ("covered_branches", "expected_status"),
    [(10, 0), (9, 1)],
)
def test_each_module_must_meet_exact_coverage_threshold(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    covered_branches: int,
    expected_status: int,
) -> None:
    summary = {
        "covered_lines": 890,
        "num_statements": 950,
        "covered_branches": 50,
        "num_branches": 50,
    }
    files = {module: {"summary": summary.copy()} for module in MODULES}
    target = MODULES[0]
    files[target]["summary"]["covered_branches"] = covered_branches
    report = tmp_path / "coverage.json"
    report.write_text(
        json.dumps({"meta": {"branch_coverage": True}, "files": files}),
        encoding="utf-8",
    )

    assert main(["--coverage-json", str(report)]) == expected_status
    output = capsys.readouterr().out
    expected_line = "90.00% (900/1000) PASS" if expected_status == 0 else "89.90% (899/1000) FAIL"
    assert f"{target}: {expected_line}" in output


def test_missing_module_fails_gate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report = tmp_path / "coverage.json"
    report.write_text(
        json.dumps({"meta": {"branch_coverage": True}, "files": {}}),
        encoding="utf-8",
    )

    assert main(["--coverage-json", str(report)]) == 1
    error = capsys.readouterr().err
    assert all(f"{module}: missing or invalid coverage data" in error for module in MODULES)


def test_line_only_report_is_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    report = tmp_path / "coverage.json"
    report.write_text(
        json.dumps({"meta": {"branch_coverage": False}, "files": {}}),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc:
        main(["--coverage-json", str(report)])

    assert exc.value.code == 2
    assert "must include branch coverage" in capsys.readouterr().err
