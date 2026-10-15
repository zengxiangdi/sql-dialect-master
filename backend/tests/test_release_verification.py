"""Tests for the dependency-free release metadata validator."""

import io
import tarfile
from pathlib import Path
from zipfile import ZipFile

import pytest

from backend.core.metadata import PROJECT_VERSION
from scripts.verify_release import ReleaseValidationError, validate_release


ROOT = Path(__file__).resolve().parents[2]


def test_current_release_metadata_is_consistent() -> None:
    assert validate_release(ROOT, f"v{PROJECT_VERSION}") == PROJECT_VERSION


def test_release_validator_rejects_wrong_tag_version() -> None:
    with pytest.raises(ReleaseValidationError, match="pyproject.toml version"):
        validate_release(ROOT, "v9.9.9")


def test_release_validator_rejects_non_release_tag() -> None:
    with pytest.raises(ReleaseValidationError, match="unsupported release tag"):
        validate_release(ROOT, "release-1.1.3")


def _write_distributions(dist: Path, wheel_version: str, runtime_dependency: str | None = None) -> None:
    dist.mkdir()
    required = ("backend/core/functions_db.json", "backend/core/type_mapping.json")
    wheel_path = dist / f"sql_dialect_master-{PROJECT_VERSION}-py3-none-any.whl"
    with ZipFile(wheel_path, "w") as wheel:
        for path in required:
            wheel.writestr(path, "placeholder")
        wheel.writestr(
            f"sql_dialect_master-{PROJECT_VERSION}.dist-info/METADATA",
            "Metadata-Version: 2.1\n"
            f"Name: sql-dialect-master\nVersion: {wheel_version}\n"
            + (f"Requires-Dist: {runtime_dependency}\n" if runtime_dependency else ""),
        )
    with tarfile.open(dist / f"sql_dialect_master-{PROJECT_VERSION}.tar.gz", "w:gz") as archive:
        for path in required:
            member = tarfile.TarInfo(f"sql_dialect_master-{PROJECT_VERSION}/{path}")
            member.size = 1
            archive.addfile(member, io.BytesIO(b"x"))


def test_release_validator_checks_distribution_metadata(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _write_distributions(dist, "9.9.9")

    with pytest.raises(ReleaseValidationError, match="METADATA version"):
        validate_release(ROOT, f"v{PROJECT_VERSION}", dist)


def test_release_validator_rejects_streamlit_runtime_dependency(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _write_distributions(dist, PROJECT_VERSION, "streamlit>=1.0")

    with pytest.raises(ReleaseValidationError, match="Streamlit"):
        validate_release(ROOT, f"v{PROJECT_VERSION}", dist)


def test_release_validator_accepts_normalized_sdist_filename(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _write_distributions(dist, PROJECT_VERSION)

    assert validate_release(ROOT, f"v{PROJECT_VERSION}", dist) == PROJECT_VERSION


def test_release_validator_rejects_stale_artifacts(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _write_distributions(dist, PROJECT_VERSION)
    (dist / "sql_dialect_master-0.0.1-py3-none-any.whl").touch()

    with pytest.raises(ReleaseValidationError, match="stale or duplicate"):
        validate_release(ROOT, f"v{PROJECT_VERSION}", dist)


def test_release_validator_rejects_development_package_leak(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _write_distributions(dist, PROJECT_VERSION)
    with ZipFile(next(dist.glob("*.whl")), "a") as wheel:
        wheel.writestr("backend/tests/test_accidental.py", "")

    with pytest.raises(ReleaseValidationError, match="development tests"):
        validate_release(ROOT, f"v{PROJECT_VERSION}", dist)
