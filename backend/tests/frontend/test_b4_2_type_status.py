"""B4-2 — type mapping status must recognize N/A before equality.

The Types page labelled both-missing cells (`N/A → N/A`) as ``exact``
because it compared the two values first.  The status priority is:

1. both missing → ``missing``
2. source missing → ``source_missing``
3. target missing → ``target_missing``
4. equal values → ``exact``
5. otherwise → ``mapped``
"""
from __future__ import annotations

import pytest

from frontend.core.type_status import classify_mapping_status


class TestB4_2_ClassifyMappingStatus:
    def test_both_na_is_missing_not_exact(self):
        assert classify_mapping_status("N/A", "N/A") == "missing"

    def test_source_na_is_source_missing(self):
        assert classify_mapping_status("N/A", "INT") == "source_missing"

    def test_target_na_is_target_missing(self):
        assert classify_mapping_status("INT", "N/A") == "target_missing"

    def test_equal_values_are_exact(self):
        assert classify_mapping_status("VARCHAR(n)", "VARCHAR(n)") == "exact"

    def test_different_real_values_are_mapped(self):
        assert classify_mapping_status("VARCHAR2(2000)", "VARCHAR(n)") == "mapped"

    @pytest.mark.parametrize(
        "src,tgt",
        [
            ("N/A", "N/A"),
            ("N/A", "VARCHAR"),
            ("VARCHAR", "N/A"),
        ],
    )
    def test_na_cases_never_exact(self, src, tgt):
        assert classify_mapping_status(src, tgt) != "exact"
