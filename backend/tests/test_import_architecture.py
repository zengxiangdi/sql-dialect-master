from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOTS = (REPO_ROOT / "backend", REPO_ROOT / "examples", REPO_ROOT / "scripts", REPO_ROOT)


def _python_files():
    seen = set()
    for root in PYTHON_ROOTS:
        if root.is_file() and root.suffix == ".py":
            candidates = [root]
        else:
            candidates = root.rglob("*.py")
        for path in candidates:
            if path not in seen and ".git" not in path.parts:
                seen.add(path)
                yield path


def test_runtime_python_does_not_mutate_sys_path():
    forbidden = ("sys.path.insert(", "sys.path.append(", "sys.path +=")
    offenders = []
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in forbidden):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_runtime_python_does_not_import_legacy_core_namespace():
    offenders = []
    prefixes = ("from core.", "import core.")
    for path in _python_files():
        text = path.read_text(encoding="utf-8")
        if any(line.lstrip().startswith(prefixes) for line in text.splitlines()):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_backend_core_is_the_single_canonical_namespace():
    import backend.core.config as backend_config

    assert backend_config.__name__ == "backend.core.config"
    assert backend_config.__package__ == "backend.core"

    try:
        import core.config as legacy_config  # noqa: F401
    except ModuleNotFoundError:
        return

    assert legacy_config.__name__ != backend_config.__name__, (
        "The legacy core namespace must not alias the canonical backend.core module"
    )

    assert legacy_config.__file__ != backend_config.__file__, (
        "The same source file must never be loaded under both core.* and backend.core.*"
    )
