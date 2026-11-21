"""Enforce combined line and branch coverage for selected core modules."""

import argparse
import json
import sys
from pathlib import Path

MODULES = (
    "backend/core/nl2sql_pipeline/validation.py",
    "backend/core/p2_data_validation.py",
    "backend/core/nl2sql_pipeline/clause_extract.py",
    "backend/core/rules.py",
    "backend/core/nl2sql_pipeline/predicates.py",
    "backend/core/nl2sql_pipeline/suggestions.py",
    "backend/core/nl2sql_pipeline/renderer.py",
    "backend/core/nl2sql_schema.py",
)
MINIMUM_PERCENT = 90


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-json", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.coverage_json.read_text(encoding="utf-8"))
        if report["meta"]["branch_coverage"] is not True:
            parser.error("The coverage report must include branch coverage")
        files = report["files"]
        if not isinstance(files, dict):
            parser.error("The coverage report must contain per-file results")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(f"Cannot read coverage report {args.coverage_json}: {exc}")

    failed = False
    for module in MODULES:
        try:
            summary = files[module]["summary"]
            covered = summary["covered_lines"] + summary["covered_branches"]
            total = summary["num_statements"] + summary["num_branches"]
            if not 0 <= covered <= total or total == 0:
                raise ValueError("invalid coverage totals")
        except (KeyError, TypeError, ValueError) as exc:
            print(f"{module}: missing or invalid coverage data ({exc})", file=sys.stderr)
            failed = True
            continue
        passed = 100 * covered >= MINIMUM_PERCENT * total
        status = "PASS" if passed else "FAIL"
        print(f"{module}: {covered / total:.2%} ({covered}/{total}) {status}")
        failed |= not passed

    if failed:
        print(f"Each module requires at least {MINIMUM_PERCENT}% coverage", file=sys.stderr)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
