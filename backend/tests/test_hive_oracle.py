#!/usr/bin/env python3
"""Test cases for Hive ↔ Oracle SQL conversion."""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.core.transpiler import SQLTranspiler

transpiler = SQLTranspiler()

# === Hive → Oracle Test Cases ===

class TestHiveToOracle:
    """Test Hive to Oracle conversions."""
    
    def test_basic_select(self):
        sql = "SELECT * FROM users WHERE id = 1"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
        assert "SELECT" in result.target_sql
    
    def test_limit_to_fetch(self):
        sql = "SELECT * FROM users LIMIT 10"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
        assert "FETCH" in result.target_sql or "ROWNUM" in result.target_sql.upper()
    
    def test_string_concat(self):
        sql = "SELECT CONCAT(first_name, ' ', last_name) FROM users"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
    
    def test_date_add(self):
        sql = "SELECT DATE_ADD(created_at, 7) FROM orders"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
    
    def test_nvl_coalesce(self):
        sql = "SELECT COALESCE(name, 'Unknown') FROM users"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
    
    def test_window_row_number(self):
        sql = "SELECT *, ROW_NUMBER() OVER (PARTITION BY dept ORDER BY salary DESC) AS rn FROM employees"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
        assert "ROW_NUMBER" in result.target_sql
    
    def test_window_rank(self):
        sql = "SELECT *, RANK() OVER (ORDER BY score DESC) AS rnk FROM students"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
    
    def test_case_when(self):
        sql = "SELECT CASE WHEN status = 1 THEN 'Active' ELSE 'Inactive' END FROM users"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
        assert "CASE" in result.target_sql
    
    def test_group_by_having(self):
        sql = "SELECT dept, COUNT(*) AS cnt FROM employees GROUP BY dept HAVING COUNT(*) > 5"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
        assert "HAVING" in result.target_sql
    
    def test_subquery(self):
        sql = "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders)"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
    
    def test_join_inner(self):
        sql = "SELECT u.name, o.amount FROM users u JOIN orders o ON u.id = o.user_id"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
        assert "JOIN" in result.target_sql
    
    def test_join_left(self):
        sql = "SELECT u.name, o.amount FROM users u LEFT JOIN orders o ON u.id = o.user_id"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
    
    def test_union(self):
        sql = "SELECT id FROM users UNION SELECT id FROM admins"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
        assert "UNION" in result.target_sql
    
    def test_cte(self):
        sql = "WITH active_users AS (SELECT * FROM users WHERE status = 1) SELECT * FROM active_users"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
    
    def test_distinct(self):
        sql = "SELECT DISTINCT category FROM products"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
        assert "DISTINCT" in result.target_sql
    
    def test_order_by_multiple(self):
        sql = "SELECT * FROM users ORDER BY created_at DESC, name ASC"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
    
    def test_aggregate_sum(self):
        sql = "SELECT SUM(amount) FROM orders"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
    
    def test_aggregate_avg(self):
        sql = "SELECT AVG(salary) FROM employees"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
    
    def test_between(self):
        sql = "SELECT * FROM orders WHERE amount BETWEEN 100 AND 500"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
        assert "BETWEEN" in result.target_sql
    
    def test_like_pattern(self):
        sql = "SELECT * FROM users WHERE name LIKE 'John%'"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
        assert "LIKE" in result.target_sql
    
    def test_is_null(self):
        sql = "SELECT * FROM users WHERE email IS NULL"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
    
    def test_is_not_null(self):
        sql = "SELECT * FROM users WHERE email IS NOT NULL"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
    
    def test_in_list(self):
        sql = "SELECT * FROM users WHERE status IN (1, 2, 3)"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
    
    def test_not_in(self):
        sql = "SELECT * FROM users WHERE status NOT IN (0, -1)"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
    
    def test_exists(self):
        sql = "SELECT * FROM users u WHERE EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id)"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success


# === Oracle → Hive Test Cases ===

class TestOracleToHive:
    """Test Oracle to Hive conversions."""
    
    def test_basic_select(self):
        sql = "SELECT * FROM users WHERE id = 1"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_rownum_to_limit(self):
        sql = "SELECT * FROM users WHERE ROWNUM <= 10"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_nvl_to_coalesce(self):
        sql = "SELECT NVL(name, 'Unknown') FROM users"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_decode_to_case(self):
        sql = "SELECT DECODE(status, 1, 'Active', 'Inactive') FROM users"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_sysdate(self):
        sql = "SELECT SYSDATE FROM dual"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_to_char_date(self):
        sql = "SELECT TO_CHAR(created_at, 'YYYY-MM-DD') FROM orders"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_to_date(self):
        sql = "SELECT TO_DATE('2024-01-01', 'YYYY-MM-DD') FROM dual"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_substr(self):
        sql = "SELECT SUBSTR(name, 1, 5) FROM users"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_instr(self):
        sql = "SELECT INSTR(email, '@') FROM users"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_trim(self):
        sql = "SELECT TRIM(name) FROM users"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_upper_lower(self):
        sql = "SELECT UPPER(name), LOWER(email) FROM users"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_replace(self):
        sql = "SELECT REPLACE(name, 'old', 'new') FROM users"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_round(self):
        sql = "SELECT ROUND(amount, 2) FROM orders"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_trunc(self):
        sql = "SELECT TRUNC(amount) FROM orders"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_mod(self):
        sql = "SELECT MOD(id, 10) FROM users"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_abs(self):
        sql = "SELECT ABS(balance) FROM accounts"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_window_lag(self):
        sql = "SELECT *, LAG(amount, 1) OVER (ORDER BY created_at) AS prev_amount FROM orders"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_window_lead(self):
        sql = "SELECT *, LEAD(amount, 1) OVER (ORDER BY created_at) AS next_amount FROM orders"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_window_first_value(self):
        sql = "SELECT *, FIRST_VALUE(amount) OVER (PARTITION BY user_id ORDER BY created_at) FROM orders"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_window_sum(self):
        sql = "SELECT *, SUM(amount) OVER (PARTITION BY user_id) AS total FROM orders"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_analytic_count(self):
        sql = "SELECT *, COUNT(*) OVER () AS total_count FROM users"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_multiple_joins(self):
        sql = """SELECT u.name, o.amount, p.name AS product
                 FROM users u 
                 JOIN orders o ON u.id = o.user_id 
                 JOIN products p ON o.product_id = p.id"""
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_self_join(self):
        sql = "SELECT e.name, m.name AS manager FROM employees e LEFT JOIN employees m ON e.manager_id = m.id"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_cross_join(self):
        sql = "SELECT * FROM products CROSS JOIN categories"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_union_all(self):
        sql = "SELECT id FROM users UNION ALL SELECT id FROM admins"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
