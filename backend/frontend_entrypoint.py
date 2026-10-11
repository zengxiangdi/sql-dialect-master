"""Installed console entry point for the Streamlit workspace."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def main() -> None:
    """Launch the packaged Streamlit application from any working directory."""
    spec = importlib.util.find_spec("sdm_local_v2")
    if spec is None or not spec.origin:
        raise RuntimeError("The packaged Streamlit entry point is unavailable")
    script = Path(spec.origin).resolve()
    from streamlit.web import cli

    sys.argv = ["streamlit", "run", str(script), *sys.argv[1:]]
    cli.main()


if __name__ == "__main__":
    main()
