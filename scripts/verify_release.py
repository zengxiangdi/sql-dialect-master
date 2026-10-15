#!/usr/bin/env python3
"""Validate a release tag and the artifacts built for that tag.

The checks intentionally use only the standard library so they can run before
installing project dependencies in a release job.
"""

from __future__ import annotations

import argparse
import email
import re
import tarfile
import tomllib
from pathlib import Path
from zipfile import ZipFile


class ReleaseValidationError(ValueError):
    """Raised when repository release metadata is inconsistent."""


def _version_from_pyproject(path: Path) -> str:
    with path.open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def validate_release(root: Path, tag: str, dist_dir: Path | None = None) -> str:
    """Validate metadata for ``tag`` and optionally its built distributions."""
    match = re.fullmatch(r"v(\d+\.\d+\.\d+)", tag)
    if not match:
        raise ReleaseValidationError(f"unsupported release tag: {tag!r}")
    version = match.group(1)

    pyproject_version = _version_from_pyproject(root / "pyproject.toml")
    if pyproject_version != version:
        raise ReleaseValidationError(
            f"pyproject.toml version {pyproject_version!r} != tag {version!r}"
        )

    metadata = (root / "backend/core/metadata.py").read_text(encoding="utf-8")
    metadata_match = re.search(r"PROJECT_VERSION\s*=\s*[\"']([^\"']+)[\"']", metadata)
    if not metadata_match or metadata_match.group(1) != version:
        actual = metadata_match.group(1) if metadata_match else "<missing>"
        raise ReleaseValidationError(f"metadata PROJECT_VERSION {actual!r} != {version!r}")

    api_version_match = re.search(r"API_VERSION\s*=\s*[\"']([^\"']+)[\"']", metadata)
    if not api_version_match or api_version_match.group(1) != version:
        actual = api_version_match.group(1) if api_version_match else "<missing>"
        raise ReleaseValidationError(f"metadata API_VERSION {actual!r} != {version!r}")

    env_example = (root / ".env.example").read_text(encoding="utf-8")
    env_match = re.search(r"(?m)^SDM_API_VERSION=([^\n]+)", env_example)
    if not env_match or env_match.group(1).strip() != version:
        actual = env_match.group(1).strip() if env_match else "<missing>"
        raise ReleaseValidationError(f".env.example SDM_API_VERSION {actual!r} != {version!r}")

    readme = (root / "README.md").read_text(encoding="utf-8")
    if f"Current release: {version}" not in readme:
        raise ReleaseValidationError("README Current release marker is out of date")

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if not re.search(rf"(?m)^## \[{re.escape(version)}\](?:\s|$)", changelog):
        raise ReleaseValidationError(f"CHANGELOG.md has no [{version}] entry")

    if dist_dir is not None:
        wheels = sorted(dist_dir.glob(f"sql_dialect_master-{version}-*.whl"))
        # Setuptools normalizes the distribution name to underscores in both
        # wheel and sdist filenames.
        sdists = sorted(dist_dir.glob(f"sql_dialect_master-{version}.tar.gz"))
        if len(wheels) != 1:
            raise ReleaseValidationError(
                f"expected one wheel for {version}, found {len(wheels)}"
            )
        if len(sdists) != 1:
            raise ReleaseValidationError(
                f"expected one sdist for {version}, found {len(sdists)}"
            )
        artifacts = set(dist_dir.glob("*.whl")) | set(dist_dir.glob("*.tar.gz"))
        if artifacts != {wheels[0], sdists[0]}:
            raise ReleaseValidationError("distribution directory contains stale or duplicate release artifacts")

        required = ("backend/core/functions_db.json", "backend/core/type_mapping.json")
        with ZipFile(wheels[0]) as wheel:
            names = set(wheel.namelist())
            metadata_paths = [path for path in names if path.endswith(".dist-info/METADATA")]
            if len(metadata_paths) != 1:
                raise ReleaseValidationError("wheel metadata is missing")
            wheel_metadata = email.message_from_bytes(wheel.read(metadata_paths[0]))
            if wheel_metadata.get("Version") != version:
                raise ReleaseValidationError("wheel METADATA version does not match release tag")
            requirements = wheel_metadata.get_all("Requires-Dist", [])
            if any(requirement.lower().startswith("streamlit") for requirement in requirements):
                raise ReleaseValidationError("wheel runtime metadata still depends on Streamlit")
            if any(path.endswith(".dist-info/entry_points.txt") for path in names):
                raise ReleaseValidationError("wheel contains a retired frontend console entrypoint")
            leaked_frontend = [
                path for path in names
                if path == "sdm_local_v2.py" or path.startswith("frontend/")
            ]
            if leaked_frontend:
                raise ReleaseValidationError("wheel contains retired frontend files")
        missing = [path for path in required if path not in names]
        if missing:
            raise ReleaseValidationError(f"wheel is missing: {missing}")
        forbidden = [path for path in names if path.startswith(("backend/tests/", "backend/benchmarks/"))]
        if forbidden:
            raise ReleaseValidationError("wheel contains development tests or benchmarks")

        with tarfile.open(sdists[0], "r:gz") as archive:
            names = {member.name.split("/", 1)[-1] for member in archive.getmembers()}
        missing = [path for path in required if path not in names]
        if missing:
            raise ReleaseValidationError(f"sdist is missing: {missing}")
        forbidden = [
            path for path in names
            if path.startswith(("backend/tests/", "backend/benchmarks/", "frontend/"))
            or path in {"sdm_local_v2.py", "backend/frontend_entrypoint.py"}
        ]
        if forbidden:
            raise ReleaseValidationError("sdist contains retired frontend or development files")

    return version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="release tag, for example v1.1.4")
    parser.add_argument("--dist", type=Path, help="built distribution directory")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    version = validate_release(args.root.resolve(), args.tag, args.dist)
    print(f"Release metadata verified: {args.tag} ({version})")


if __name__ == "__main__":
    main()
