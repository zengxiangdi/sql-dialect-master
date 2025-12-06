#!/usr/bin/env python3
"""Test cases for SQL Server (TSQL) ↔ Hive SQL conversion."""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.core.transpiler import SQLTranspiler

transpiler = SQLTranspiler()

# === SQL Server → Hive Test Cases ===

class TestTSQLToHive:
    """Test SQL Server to Hive conversions."""
    
    def test_basic_select(self):
        sql = "SELECT * FROM users WHERE id = 1"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_top_to_limit(self):
        sql = "SELECT TOP 10 * FROM users"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
        assert "LIMIT" in result.target_sql
    
    def test_top_with_order(self):
        sql = "SELECT TOP 10 * FROM users ORDER BY created_at DESC"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_isnull_to_coalesce(self):
        sql = "SELECT ISNULL(name, 'Unknown') FROM users"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_getdate(self):
        sql = "SELECT GETDATE()"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_getutcdate(self):
        sql = "SELECT GETUTCDATE()"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_dateadd(self):
        sql = "SELECT DATEADD(day, 7, created_at) FROM orders"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_datediff(self):
        sql = "SELECT DATEDIFF(day, start_date, end_date) FROM projects"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_datepart(self):
        sql = "SELECT DATEPART(year, created_at) FROM orders"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_convert_date(self):
        sql = "SELECT CONVERT(VARCHAR, created_at, 120) FROM orders"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_cast(self):
        sql = "SELECT CAST(amount AS INT) FROM orders"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_string_agg(self):
        sql = "SELECT dept, STRING_AGG(name, ', ') FROM employees GROUP BY dept"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_charindex(self):
        sql = "SELECT CHARINDEX('@', email) FROM users"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_len(self):
        sql = "SELECT LEN(name) FROM users"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_left_right(self):
        sql = "SELECT LEFT(name, 3), RIGHT(name, 3) FROM users"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_stuff(self):
        sql = "SELECT STUFF(name, 1, 3, 'XXX') FROM users"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_concat(self):
        sql = "SELECT CONCAT(first_name, ' ', last_name) FROM users"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_iif(self):
        sql = "SELECT IIF(status = 1, 'Active', 'Inactive') FROM users"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_case_when(self):
        sql = "SELECT CASE WHEN status = 1 THEN 'Active' ELSE 'Inactive' END FROM users"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_window_row_number(self):
        sql = "SELECT *, ROW_NUMBER() OVER (PARTITION BY dept ORDER BY salary DESC) AS rn FROM employees"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_window_rank(self):
        sql = "SELECT *, RANK() OVER (ORDER BY score DESC) AS rnk FROM students"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_cte(self):
        sql = "WITH active AS (SELECT * FROM users WHERE status = 1) SELECT * FROM active"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_cross_apply(self):
        sql = "SELECT u.*, o.amount FROM users u CROSS APPLY (SELECT TOP 1 * FROM orders WHERE user_id = u.id) o"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_outer_apply(self):
        sql = "SELECT u.*, o.amount FROM users u OUTER APPLY (SELECT TOP 1 * FROM orders WHERE user_id = u.id) o"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_json_value(self):
        sql = "SELECT JSON_VALUE(data, '$.name') FROM users"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success


# === Hive → SQL Server Test Cases ===

class TestHiveToTSQL:
    """Test Hive to SQL Server conversions."""
    
    def test_basic_select(self):
        sql = "SELECT * FROM users WHERE id = 1"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_limit_to_top(self):
        sql = "SELECT * FROM users LIMIT 10"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
        assert "TOP" in result.target_sql or "FETCH" in result.target_sql
    
    def test_coalesce(self):
        sql = "SELECT COALESCE(name, 'Unknown') FROM users"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_nvl(self):
        sql = "SELECT NVL(name, 'Unknown') FROM users"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_current_date(self):
        sql = "SELECT CURRENT_DATE"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_current_timestamp(self):
        sql = "SELECT CURRENT_TIMESTAMP"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_date_add(self):
        sql = "SELECT DATE_ADD(created_at, 7) FROM orders"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_date_sub(self):
        sql = "SELECT DATE_SUB(created_at, 7) FROM orders"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_datediff(self):
        sql = "SELECT DATEDIFF(end_date, start_date) FROM projects"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_date_format(self):
        sql = "SELECT DATE_FORMAT(created_at, 'yyyy-MM-dd') FROM orders"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_year_month_day(self):
        sql = "SELECT YEAR(created_at), MONTH(created_at), DAY(created_at) FROM orders"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_concat(self):
        sql = "SELECT CONCAT(first_name, ' ', last_name) FROM users"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_substring(self):
        sql = "SELECT SUBSTRING(name, 1, 5) FROM users"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_length(self):
        sql = "SELECT LENGTH(name) FROM users"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_instr(self):
        sql = "SELECT INSTR(email, '@') FROM users"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_replace(self):
        sql = "SELECT REPLACE(name, 'old', 'new') FROM users"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_trim(self):
        sql = "SELECT TRIM(name) FROM users"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_upper_lower(self):
        sql = "SELECT UPPER(name), LOWER(email) FROM users"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_collect_list(self):
        sql = "SELECT dept, COLLECT_LIST(name) FROM employees GROUP BY dept"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_collect_set(self):
        sql = "SELECT dept, COLLECT_SET(name) FROM employees GROUP BY dept"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_array_join(self):
        sql = "SELECT ARRAY_JOIN(COLLECT_LIST(name), ', ') FROM employees GROUP BY dept"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_get_json_object(self):
        sql = "SELECT GET_JSON_OBJECT(data, '$.name') FROM users"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_window_row_number(self):
        sql = "SELECT *, ROW_NUMBER() OVER (PARTITION BY dept ORDER BY salary DESC) AS rn FROM employees"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_window_rank(self):
        sql = "SELECT *, RANK() OVER (ORDER BY score DESC) AS rnk FROM students"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_window_dense_rank(self):
        sql = "SELECT *, DENSE_RANK() OVER (ORDER BY score DESC) AS drnk FROM students"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_window_lag(self):
        sql = "SELECT *, LAG(amount, 1) OVER (ORDER BY created_at) AS prev_amount FROM orders"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_window_lead(self):
        sql = "SELECT *, LEAD(amount, 1) OVER (ORDER BY created_at) AS next_amount FROM orders"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_cte(self):
        sql = "WITH active AS (SELECT * FROM users WHERE status = 1) SELECT * FROM active"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_recursive_cte(self):
        sql = """WITH RECURSIVE tree AS (
            SELECT id, parent_id, 1 AS level FROM nodes WHERE parent_id IS NULL
            UNION ALL
            SELECT n.id, n.parent_id, t.level + 1 FROM nodes n JOIN tree t ON n.parent_id = t.id
        ) SELECT * FROM tree"""
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_case_when(self):
        sql = "SELECT CASE WHEN status = 1 THEN 'Active' ELSE 'Inactive' END FROM users"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_join_inner(self):
        sql = "SELECT u.name, o.amount FROM users u JOIN orders o ON u.id = o.user_id"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_join_left(self):
        sql = "SELECT u.name, o.amount FROM users u LEFT JOIN orders o ON u.id = o.user_id"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_union(self):
        sql = "SELECT id FROM users UNION SELECT id FROM admins"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_union_all(self):
        sql = "SELECT id FROM users UNION ALL SELECT id FROM admins"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_subquery(self):
        sql = "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders)"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_exists(self):
        sql = "SELECT * FROM users u WHERE EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id)"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_group_by_having(self):
        sql = "SELECT dept, COUNT(*) AS cnt FROM employees GROUP BY dept HAVING COUNT(*) > 5"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_distinct(self):
        sql = "SELECT DISTINCT category FROM products"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_order_by_multiple(self):
        sql = "SELECT * FROM users ORDER BY created_at DESC, name ASC"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_between(self):
        sql = "SELECT * FROM orders WHERE amount BETWEEN 100 AND 500"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_like_pattern(self):
        sql = "SELECT * FROM users WHERE name LIKE 'John%'"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_is_null(self):
        sql = "SELECT * FROM users WHERE email IS NULL"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success
    
    def test_in_list(self):
        sql = "SELECT * FROM users WHERE status IN (1, 2, 3)"
        result = transpiler.transpile(sql, "hive", "tsql")
        assert result.success


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
