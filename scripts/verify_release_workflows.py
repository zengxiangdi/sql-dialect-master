"""Validate the release workflow's required workflow-name contract."""

import re
import sys
from pathlib import Path

REQUIRED_WORKFLOWS = {
    "ci.yml",
    "quality.yml",
    "benchmark.yml",
    "codeql.yml",
    "frontend.yml",
    "readme-consistency.yml",
}


def validate_release_workflows(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"required_workflows=\(([^)]*)\)", text)
    if match is None:
        return ["release workflow has no required_workflows list"]
    names = set(re.findall(r"[A-Za-z0-9_-]+\.yml", match.group(1)))
    missing = sorted(REQUIRED_WORKFLOWS - names)
    extra = sorted(names - REQUIRED_WORKFLOWS)
    errors = [f"missing required workflow: {name}" for name in missing]
    errors.extend(f"unexpected required workflow: {name}" for name in extra)
    if '"$conclusion" != "success"' not in text:
        errors.append("release workflow does not fail completed non-success runs")
    if "missing=0" not in text or "pending=0" not in text:
        errors.append("release workflow does not wait for every required workflow")
    return errors


def main() -> int:
    errors = validate_release_workflows(Path(".github/workflows/release.yml"))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Release workflow required checks verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
