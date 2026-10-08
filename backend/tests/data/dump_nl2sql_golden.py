#!/usr/bin/env python3
"""One-time helper: dump NL2SQL characterization golden snapshots.

Run manually from the repository root:

    ./.venv/bin/python backend/tests/data/dump_nl2sql_golden.py

The resulting JSON is committed as ``nl2sql_golden.json`` and read (never
recomputed) by ``test_nl2sql_characterization.py``.
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
import sys
sys.path.insert(0, str(REPO_ROOT))

from backend.core.nl2sql import NL2SQLGenerator

DIALECTS = [
    "mysql", "postgres", "oracle", "tsql", "hive", "spark",
    "trino", "databricks", "snowflake", "redshift", "clickhouse", "duckdb",
]

PROMPTS = [
    "查询所有用户",
    "find top 10 products by price",
    "calculate average price for products grouped by category",
    "查询最近7天的订单",
    "find users who have orders",
    "show users and products",
]

# D1: date arithmetic prompts
DATE_PROMPTS = [
    "查询今天的订单",
    "show yesterday's orders",
    "查询最近7天的订单",
    "查询最近3周的订单",
    "查询最近2月的订单",
    "查询最近1年的订单",
]

# D2: relational EXISTS / NOT EXISTS
RELATIONAL_PROMPTS = [
    "find users who have orders",
    "find users without orders",
]

# G1: fail-closed (unknown table pair)
FAIL_CLOSED_PROMPTS = [
    "show users and products",
    "find users who have invoices",
]


def _fields(result, text: str) -> dict:
    """The exact fields to lock in the golden snapshot."""
    return {
        "success": result.success,
        "sql": result.sql,
        "explanation": result.explanation,
        "suggestions": list(result.suggestions),
        "input_text": text,
    }


def main() -> None:
    generator = NL2SQLGenerator()

    # Matrix: 12 dialects × general prompts
    matrix = {}
    for dialect in DIALECTS:
        for prompt in PROMPTS:
            result = generator.generate(prompt, dialect=dialect)
            key = f"{dialect}::{prompt}"
            matrix[key] = _fields(result, prompt)

    # D1 date arithmetic: 5 representative dialects × date prompts
    d1 = {}
    for dialect in ["postgres", "mysql", "oracle", "tsql", "hive"]:
        for prompt in DATE_PROMPTS:
            result = generator.generate(prompt, dialect=dialect)
            key = f"D1::{dialect}::{prompt}"
            d1[key] = _fields(result, prompt)

    # D2 relational: EXISTS / NOT EXISTS
    d2 = {}
    for prompt in RELATIONAL_PROMPTS:
        for dialect in ["postgres", "mysql", "hive"]:
            result = generator.generate(prompt, dialect=dialect)
            key = f"D2::{dialect}::{prompt}"
            d2[key] = _fields(result, prompt)

    # G1 fail-closed
    g1 = {}
    for prompt in FAIL_CLOSED_PROMPTS:
        for dialect in ["postgres", "hive"]:
            result = generator.generate(prompt, dialect=dialect)
            key = f"G1::{dialect}::{prompt}"
            g1[key] = _fields(result, prompt)

    snapshot = {
        "matrix": matrix,
        "d1_date_arithmetic": d1,
        "d2_relational": d2,
        "g1_fail_closed": g1,
    }

    out_path = Path(__file__).resolve().parent / "nl2sql_golden.json"
    out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"  matrix: {len(matrix)} cases")
    print(f"  d1:     {len(d1)} cases")
    print(f"  d2:     {len(d2)} cases")
    print(f"  g1:     {len(g1)} cases")


if __name__ == "__main__":
    main()
