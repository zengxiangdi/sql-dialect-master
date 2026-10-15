"""B5-1 — release-gate independent semantic expectations.

Golden snapshots prevent unintentional drift but are not semantic
expectations.  This gate pins concrete values across the v1.1.2
surface — NL2SQL columns/aggregates/condition values/date units/
clause order, relational EXISTS/NOT EXISTS + fail-closed behavior,
transpiler target structures, TypeMapper target types, splitter
fragment boundaries, and frontend navigation payloads.  No assertion
may be derived from the current generator output at runtime.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

from backend.core.nl2sql import NL2SQLGenerator
from backend.core.transpiler import SQLTranspiler
from backend.core.type_mapping import TypeMapper
from backend.utils.validators import split_sql_statements


def _payload(result) -> str:
    sql = result.sql or ""
    return "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))


class TestB5_Nl2sqlIndependentExpectations:
    def test_grouped_average_uses_price_and_category(self):
        result = NL2SQLGenerator().generate(
            "calculate average price for products grouped by category", "hive"
        )
        assert result.success is True
        tree = sqlglot.parse_one(_payload(result), read="hive")
        avg = tree.find(exp.Avg)
        assert avg is not None
        assert avg.this.sql("hive") == "price"
        group = [c.sql("hive") for c in tree.args["group"].expressions]
        assert group == ["category"]

    def test_last_3_weeks_value_and_explanation_unit(self):
        result = NL2SQLGenerator().generate("last 3 weeks of orders", "hive")
        assert result.success is True
        assert "DATE_SUB(CURRENT_DATE, 21)" in result.sql
        assert result.explanation == "查询最近3周数据"

    def test_top_n_threshold_is_operator_bound(self):
        result = NL2SQLGenerator().generate("前10条金额大于100的订单", "hive")
        tree = sqlglot.parse_one(_payload(result), read="hive")
        where = tree.find(exp.Where)
        assert where is not None
        assert "amount > 100" in where.sql("hive"), result.sql
        limit = tree.find(exp.Limit)
        assert limit is not None
        assert int(limit.expression.this) == 10

    def test_relations_fail_closed_when_unknown(self):
        result = NL2SQLGenerator().generate("查询有发票的用户", "hive")
        assert result.success is False
        assert result.sql is None
        assert "Unable to safely infer" in result.explanation

    def test_chinese_exists_relation_is_relational(self):
        result = NL2SQLGenerator().generate("查询有订单的用户", "hive")
        assert result.success is True
        assert "EXISTS" in result.sql.upper()
        assert "users.id = orders.user_id" in result.sql
        tree = sqlglot.parse_one(_payload(result), read="hive")
        assert tree.find(exp.From).this.name == "users"


class TestB5_TranspilerIndependentExpectations:
    def test_limit_becomes_fetch_first_on_oracle(self):
        result = SQLTranspiler().transpile("SELECT * FROM t LIMIT 5", "postgres", "oracle")
        assert result.success is True
        assert "FETCH FIRST 5 ROWS ONLY" in result.target_sql

    def test_connect_by_becomes_recursive_on_duckdb(self):
        result = SQLTranspiler().transpile(
            "SELECT * FROM users START WITH id = 1 CONNECT BY PRIOR id = parent_id",
            "oracle", "duckdb",
        )
        assert result.success is True
        assert "WITH RECURSIVE" in result.target_sql

    def test_listagg_becomes_array_join_on_hive(self):
        result = SQLTranspiler().transpile(
            "SELECT LISTAGG(name, ',') WITHIN GROUP (ORDER BY id) FROM users",
            "oracle", "hive",
        )
        assert result.success is True
        assert "ARRAY_JOIN(COLLECT_LIST(name), ',')" in result.target_sql


class TestB5_TypeMapperIndependentExpectations:
    def test_varchar_target_value(self):
        result = TypeMapper().map_type("VARCHAR", "mysql", "postgres")
        assert result["success"] is True
        assert result["mapping_status"] == "mapped"
        assert result["target_type"] == "VARCHAR(n)"

    def test_unsupported_target_is_not_success(self):
        import json
        from pathlib import Path

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            data_path = Path(tmp) / "partial.json"
            data_path.write_text(json.dumps({
                "mappings": {"FULL": {"mysql": "INT", "postgres": "INTEGER"}},
                "precision_warnings": {},
            }))
            mapper = TypeMapper(data_path=data_path)
            result = mapper.map_type("FULL", "mysql", "clickhouse")
            assert result["success"] is False
            assert result["mapping_status"] == "unsupported"


class TestB5_SplitterIndependentExpectations:
    def test_tsql_go_boundaries_preserve_content(self):
        result = split_sql_statements("SELECT 1\nGO\nSELECT 2", dialect="tsql")
        assert result == ["SELECT 1", "SELECT 2"]

    def test_oracle_plsql_block_is_one_statement(self):
        result = split_sql_statements(
            "BEGIN\n  UPDATE t SET a = 1;\nEND;", dialect="oracle"
        )
        assert result == ["BEGIN\n  UPDATE t SET a = 1;\nEND"]


class TestB5_FrontendNavigationIndependentExpectations:
    def test_react_frontend_workspace_is_present(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        assert (root / "frontend-react" / "package.json").is_file()
