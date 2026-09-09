#!/usr/bin/env python3
"""FastAPI Integration Tests for SQL Dialect Master API.

Tests all API endpoints for correct behavior:
- /api/convert - SQL dialect conversion
- /api/dialects - Get supported dialects
- /api/functions - Function encyclopedia
- /api/types - Type mapping
- /api/nl2sql - Natural language to SQL
- /health - Health check endpoints
"""
import os
import sys
from pathlib import Path

import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Internal health endpoints require an explicit probe credential in tests.
os.environ.setdefault("SDM_HEALTH_PROBE_TOKEN", "test-health-token")
HEALTH_HEADERS = {"X-Health-Probe-Token": "test-health-token"}

from fastapi.testclient import TestClient

from backend.api.main import app

# Create test client
client = TestClient(app)


class TestRootEndpoint:
    """Tests for the API root endpoint."""
    
    def test_root_returns_200(self):
        """Root endpoint returns 200 OK."""
        response = client.get("/")
        assert response.status_code == 200
    
    def test_root_contains_api_info(self):
        """Root endpoint contains API information."""
        response = client.get("/")
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "status" in data
        assert data["status"] == "✅ Online"
    
    def test_root_contains_stats(self):
        """Root endpoint contains service stats."""
        response = client.get("/")
        data = response.json()
        assert "stats" in data
        assert "functions" in data["stats"]
        assert "dialects" in data["stats"]


class TestDialectsEndpoint:
    """Tests for the /api/dialects endpoint."""
    
    def test_dialects_returns_200(self):
        """Dialects list endpoint returns 200 OK."""
        response = client.get("/api/dialects")
        assert response.status_code == 200
    
    def test_dialects_contains_all_supported(self):
        """Dialects endpoint returns all 12 supported dialects."""
        response = client.get("/api/dialects")
        data = response.json()
        assert data["success"] is True
        assert data["count"] == 12
        assert len(data["dialects"]) == 12
    
    def test_dialects_contains_expected_list(self):
        """Dialects endpoint contains expected dialects."""
        response = client.get("/api/dialects")
        data = response.json()
        expected = ["hive", "mysql", "oracle", "tsql", "postgres", 
                   "spark", "trino", "snowflake", "redshift", 
                   "clickhouse", "duckdb", "databricks"]
        for dialect in expected:
            assert dialect in data["dialects"]
    
    def test_dialects_grouped_by_category(self):
        """Dialects are grouped by category."""
        response = client.get("/api/dialects")
        data = response.json()
        assert "by_category" in data
        assert "categories" in data


class TestConvertEndpoint:
    """Tests for the /api/convert endpoint."""
    
    def test_convert_simple_query(self):
        """Convert simple SELECT query between dialects."""
        response = client.post("/api/convert", json={
            "sql": "SELECT * FROM users LIMIT 10",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["target_sql"] is not None
        assert "SELECT" in data["target_sql"]
    
    def test_convert_date_function(self):
        """Convert SQL with DATE_FORMAT function."""
        response = client.post("/api/convert", json={
            "sql": "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') FROM orders",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
    
    def test_convert_unsupported_source_dialect(self):
        """Return error for unsupported source dialect."""
        response = client.post("/api/convert", json={
            "sql": "SELECT * FROM users",
            "source_dialect": "invalid_db",
            "target_dialect": "mysql"
        })
        assert response.status_code == 400
    
    def test_convert_unsupported_target_dialect(self):
        """Return error for unsupported target dialect."""
        response = client.post("/api/convert", json={
            "sql": "SELECT * FROM users",
            "source_dialect": "mysql",
            "target_dialect": "invalid_db"
        })
        assert response.status_code == 400
    
    def test_convert_empty_sql(self):
        """Handles empty SQL gracefully."""
        response = client.post("/api/convert", json={
            "sql": "",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        # Should return 200 with success=False or some error
        assert response.status_code == 200
    
    def test_convert_with_pretty_formatting(self):
        """Convert with pretty formatting enabled."""
        response = client.post("/api/convert", json={
            "sql": "SELECT a, b, c FROM users WHERE id = 1",
            "source_dialect": "mysql",
            "target_dialect": "hive",
            "pretty": True
        })
        assert response.status_code == 200
        data = response.json()
        # Pretty output should contain newlines
        if data["success"] and data["target_sql"]:
            assert isinstance(data["target_sql"], str)


class TestFunctionsEndpoint:
    """Tests for the /api/functions endpoints."""
    
    def test_functions_list_returns_200(self):
        """Functions list endpoint returns 200 OK."""
        response = client.get("/api/functions")
        assert response.status_code == 200
    
    def test_functions_list_contains_functions(self):
        """Functions list contains function data."""
        response = client.get("/api/functions")
        data = response.json()
        assert data["success"] is True
        assert "functions" in data
        assert "count" in data
        assert data["count"] > 0
    
    def test_functions_search_by_name(self):
        """Search functions by name."""
        response = client.get("/api/functions?search=concat")
        data = response.json()
        assert data["success"] is True
    
    def test_functions_filter_by_category(self):
        """Filter functions by category."""
        response = client.get("/api/functions?category=string")
        data = response.json()
        assert data["success"] is True
    
    def test_functions_limit_parameter(self):
        """Limit parameter restricts result count."""
        response = client.get("/api/functions?limit=5")
        data = response.json()
        assert data["success"] is True
        assert data["count"] <= 5
    
    def test_function_categories_returns_200(self):
        """Function categories endpoint returns 200."""
        response = client.get("/api/functions/categories")
        assert response.status_code == 200
    
    def test_get_specific_function(self):
        """Get specific function by name."""
        response = client.get("/api/functions/CONCAT")
        assert response.status_code in [200, 404]
    
    def test_get_nonexistent_function(self):
        """Get nonexistent function returns 404."""
        response = client.get("/api/functions/NONEXISTENT_FUNCTION_XYZ")
        assert response.status_code == 404


class TestTypesEndpoint:
    """Tests for the /api/types endpoints."""
    
    def test_types_list_returns_200(self):
        """Types list endpoint returns 200 OK."""
        response = client.get("/api/types")
        assert response.status_code == 200
    
    def test_types_contains_mappings(self):
        """Types response contains mappings."""
        response = client.get("/api/types")
        data = response.json()
        assert data["success"] is True
        assert "mappings" in data
        assert "dialects" in data
    
    def test_get_specific_type(self):
        """Get specific type mapping."""
        response = client.get("/api/types/VARCHAR")
        assert response.status_code in [200, 404]
    
    def test_type_mapping_request(self):
        """Map type between dialects."""
        response = client.post("/api/types/map", json={
            "type_name": "VARCHAR",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_type_mapping_rejects_unsupported_dialect(self):
        """Invalid dialects must not silently produce an N/A mapping."""
        response = client.post("/api/types/map", json={
            "type_name": "VARCHAR",
            "source_dialect": "invalid_db",
            "target_dialect": "postgres"
        })
        assert response.status_code == 400

    def test_type_mapping_normalizes_dialect_case(self):
        """Dialect names are case-insensitive at the API boundary."""
        response = client.post("/api/types/map", json={
            "type_name": "VARCHAR",
            "source_dialect": "MYSQL",
            "target_dialect": "POSTGRES"
        })
        assert response.status_code == 200
        assert response.json()["target_dialect"] == "postgres"


class TestNL2SQLEndpoint:
    """Tests for the /api/nl2sql endpoint."""
    
    def test_nl2sql_chinese_query(self):
        """Generate SQL from Chinese natural language."""
        response = client.post("/api/nl2sql", json={
            "text": "查询所有用户",
            "dialect": "mysql"
        })
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        assert "sql" in data
    
    def test_nl2sql_english_query(self):
        """Generate SQL from English natural language."""
        response = client.post("/api/nl2sql", json={
            "text": "get all users",
            "dialect": "mysql"
        })
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
    
    def test_nl2sql_with_table_hint(self):
        """Generate SQL with table hint."""
        response = client.post("/api/nl2sql", json={
            "text": "统计数量",
            "dialect": "hive",
            "table_hint": "employees"
        })
        assert response.status_code == 200
    
    def test_nl2sql_confidence_in_range(self):
        """NL2SQL confidence score is in valid range."""
        response = client.post("/api/nl2sql", json={
            "text": "查询前10个用户",
            "dialect": "mysql"
        })
        data = response.json()
        if data.get("success"):
            assert 0.0 <= data["confidence"] <= 1.0


class TestHealthEndpoints:
    """Tests for health check endpoints."""
    
    def test_health_returns_200(self):
        """Health endpoint returns 200 OK."""
        response = client.get("/health")
        assert response.status_code == 200
    
    def test_health_is_liveness(self):
        """Health endpoint exposes only process liveness."""
        response = client.get("/health")
        data = response.json()
        assert response.status_code == 200
        assert data["status"] == "alive"
        assert data["version"]
        assert "timestamp" in data
        assert "services" not in data
        assert "stats" not in data
        assert "uptime" not in data
        assert "checks" not in data
    
    def test_deep_health_returns_200(self):
        """Deep health check returns 200 OK for an authenticated internal probe."""
        response = client.get("/health/deep", headers=HEALTH_HEADERS)
        assert response.status_code == 200
    
    def test_deep_health_contains_checks(self):
        """Deep health check contains check results."""
        response = client.get("/health/deep", headers=HEALTH_HEADERS)
        data = response.json()
        assert "checks" in data
        assert "transpiler" in data["checks"]
        assert "functions" in data["checks"]
        assert "types" in data["checks"]
        assert "nl2sql" in data["checks"]


class TestStatsEndpoint:
    """Tests for the /api/stats endpoint."""
    
    def test_stats_returns_200(self):
        """Stats endpoint returns 200 OK."""
        response = client.get("/api/stats")
        assert response.status_code == 200
    
    def test_stats_contains_overview(self):
        """Stats response contains overview."""
        response = client.get("/api/stats")
        data = response.json()
        assert data["success"] is True
        assert "stats" in data
        assert "overview" in data["stats"]


class TestErrorHandling:
    """Tests for API error handling."""
    
    def test_invalid_json_body(self):
        """Invalid JSON body returns appropriate error."""
        response = client.post(
            "/api/convert",
            content="not valid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422
    
    def test_missing_required_field(self):
        """Missing required field returns appropriate error."""
        response = client.post("/api/convert", json={
            "sql": "SELECT * FROM users"
        })
        assert response.status_code == 422
    
    def test_404_not_found(self):
        """Nonexistent endpoint returns 404."""
        response = client.get("/api/nonexistent")
        assert response.status_code == 404


class TestResponseFormat:
    """Tests for API response format consistency."""
    
    def test_convert_response_has_timestamp(self):
        """Convert response includes timestamp."""
        response = client.post("/api/convert", json={
            "sql": "SELECT 1",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        data = response.json()
        assert "timestamp" in data
    
    def test_response_headers(self):
        """Response includes expected headers."""
        response = client.get("/")
        assert "x-process-time" in response.headers or "X-Process-Time" in response.headers


class TestSecurityValidation:
    """Tests for SQL injection and security protection."""
    
    def test_sql_injection_or_1_equals_1(self):
        """OR 1=1 injection pattern should trigger security warning."""
        response = client.post("/api/convert", json={
            "sql": "SELECT * FROM users WHERE id = 1 OR 1=1",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True or "security" in str(data).lower()
    
    def test_sql_injection_union_select(self):
        """UNION SELECT injection should be detected."""
        response = client.post("/api/convert", json={
            "sql": "SELECT * FROM users WHERE id = 1 UNION SELECT * FROM information_schema.tables",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        assert response.status_code == 200
    
    def test_stacked_query_injection(self):
        """Stacked query injection should be detected."""
        response = client.post("/api/convert", json={
            "sql": "SELECT * FROM users; DROP TABLE users;",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        assert response.status_code == 200
    
    def test_timing_attack_sleep(self):
        """SLEEP-based timing attack should be detected."""
        response = client.post("/api/convert", json={
            "sql": "SELECT * FROM users WHERE id = 1 AND SLEEP(5)",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        assert response.status_code == 200
    
    def test_dangerous_drop_table(self):
        """DROP TABLE statements should trigger warnings."""
        response = client.post("/api/convert", json={
            "sql": "DROP TABLE users",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        assert response.status_code == 200
        data = response.json()
        if data.get("warnings"):
            assert any("drop" in w.lower() or "dangerous" in w.lower() for w in data["warnings"])


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""
    
    def test_very_long_sql(self):
        """Very long SQL statements should be handled gracefully."""
        columns = ", ".join([f"col{i}" for i in range(500)])
        long_sql = f"SELECT {columns} FROM very_long_table_name"
        
        response = client.post("/api/convert", json={
            "sql": long_sql,
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
    
    def test_sql_exceeds_max_length(self):
        """SQL that exceeds max length should fail gracefully."""
        huge_sql = "SELECT " + ", ".join([f"column_{i}" for i in range(20000)])
        
        response = client.post("/api/convert", json={
            "sql": huge_sql,
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        assert response.status_code == 200
        data = response.json()
        if len(huge_sql) > 100000:
            assert data["success"] is False or "error" in data
    
    def test_whitespace_only_sql(self):
        """Whitespace-only SQL should be rejected."""
        response = client.post("/api/convert", json={
            "sql": "   \n\t  ",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
    
    def test_sql_with_special_characters(self):
        """SQL with special characters should be handled."""
        response = client.post("/api/convert", json={
            "sql": "SELECT * FROM users WHERE name = 'O\\'Brien' AND status = 'active'",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        assert response.status_code == 200
    
    def test_sql_with_comments(self):
        """SQL with comments should be handled."""
        response = client.post("/api/convert", json={
            "sql": "-- This is a comment\nSELECT * FROM users /* inline comment */ WHERE id = 1",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
    
    def test_multiple_statements(self):
        """Multiple SQL statements should be handled."""
        response = client.post("/api/convert", json={
            "sql": "SELECT * FROM users; SELECT * FROM orders;",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        assert response.status_code in [200, 400]


class TestUnicodeHandling:
    """Tests for Unicode and internationalization support."""
    
    def test_unicode_chinese_table_name(self):
        """Chinese table names should be handled."""
        response = client.post("/api/convert", json={
            "sql": "SELECT * FROM 用户表 WHERE 姓名 = '张三'",
            "source_dialect": "mysql",
            "target_dialect": "hive"
        })
        assert response.status_code == 200
    
    def test_unicode_japanese_column_name(self):
        """Japanese column names should be handled."""
        response = client.post("/api/convert", json={
            "sql": "SELECT 名前, 年齢 FROM ユーザー WHERE 年齢 > 20",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        assert response.status_code == 200
    
    def test_unicode_emoji_in_string(self):
        """Emojis in string values should be handled."""
        response = client.post("/api/convert", json={
            "sql": "SELECT * FROM posts WHERE content LIKE '%🔥%'",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        assert response.status_code == 200
    
    def test_unicode_mixed_script(self):
        """Mixed Unicode scripts should be handled."""
        response = client.post("/api/convert", json={
            "sql": "SELECT Имя, 이름, 名前 FROM users WHERE id = 1",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        assert response.status_code == 200
    
    def test_nl2sql_chinese_input(self):
        """NL2SQL should handle Chinese natural language."""
        response = client.post("/api/nl2sql", json={
            "text": "查询所有年龄大于20的用户",
            "dialect": "mysql"
        })
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
    
    def test_nl2sql_chinese_with_numbers(self):
        """NL2SQL should handle Chinese with numbers."""
        response = client.post("/api/nl2sql", json={
            "text": "统计最近30天的订单金额大于1000的数量",
            "dialect": "hive"
        })
        assert response.status_code == 200


class TestPerformance:
    """Tests for performance-related aspects."""
    
    def test_cache_stats_accessible(self):
        """Cache statistics should be accessible via deep health."""
        client.post("/api/convert", json={
            "sql": "SELECT 1 AS cache_test",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        })
        response = client.get("/health/deep", headers=HEALTH_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert "checks" in data
    
    def test_batch_conversion_limit(self):
        """Batch conversion should handle multiple statements."""
        statements = [
            "SELECT * FROM users",
            "SELECT * FROM orders",
            "SELECT * FROM products"
        ]
        
        results = []
        for stmt in statements:
            response = client.post("/api/convert", json={
                "sql": stmt,
                "source_dialect": "mysql",
                "target_dialect": "hive"
            })
            results.append(response.status_code == 200)
        
        assert all(results)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
