from pathlib import Path

from scripts.verify_release_workflows import validate_release_workflows


def test_release_workflow_requires_all_quality_workflows() -> None:
    assert validate_release_workflows(Path(".github/workflows/release.yml")) == []
