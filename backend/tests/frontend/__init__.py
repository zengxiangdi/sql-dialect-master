"""Compatibility tests for the retired Python UI.

The product frontend is React. These source-level tests remain available for
the optional legacy UI extra, but they must not make the default SDK test
installation depend on Streamlit.
"""

import pytest

pytest.importorskip("streamlit")
