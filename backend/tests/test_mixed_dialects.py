#!/usr/bin/env python3
"""Test cases for mixed dialect SQL conversions."""
import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.core.transpiler import SQLTranspiler

transpiler = SQLTranspiler()

# === Complex Multi-Table JOINs ===

class TestComplexJoins:
    """Test complex JOIN conversions across dialects."""
    
    def test_three_table_join_hive_to_spark(self):
        sql = """SELECT u.name, o.amount, p.name AS product
                 FROM users u 
                 JOIN orders o ON u.id = o.user_id 
                 JOIN products p ON o.product_id = p.id"""
        result = transpiler.transpile(sql, "hive", "spark")
        assert result.success
    
    def test_four_table_join_mysql_to_postgres(self):
        sql = """SELECT c.name, o.id, p.name, cat.name AS category
                 FROM customers c
                 JOIN orders o ON c.id = o.customer_id
                 JOIN order_items oi ON o.id = oi.order_id
                 JOIN products p ON oi.product_id = p.id
                 JOIN categories cat ON p.category_id = cat.id"""
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
    
    def test_self_join_oracle_to_hive(self):
        sql = """SELECT e.name AS employee, m.name AS manager
                 FROM employees e
                 LEFT JOIN employees m ON e.manager_id = m.id"""
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_cross_join_postgres_to_mysql(self):
        sql = "SELECT * FROM products CROSS JOIN categories"
        result = transpiler.transpile(sql, "postgres", "mysql")
        assert result.success
    
    def test_full_outer_join_tsql_to_postgres(self):
        sql = """SELECT a.id, b.id
                 FROM table_a a
                 FULL OUTER JOIN table_b b ON a.key = b.key"""
        result = transpiler.transpile(sql, "tsql", "postgres")
        assert result.success
    
    def test_multiple_left_joins_spark_to_trino(self):
        sql = """SELECT u.*, o.total, p.name
                 FROM users u
                 LEFT JOIN (SELECT user_id, SUM(amount) AS total FROM orders GROUP BY user_id) o ON u.id = o.user_id
                 LEFT JOIN profiles p ON u.id = p.user_id"""
        result = transpiler.transpile(sql, "spark", "trino")
        assert result.success


# === Subqueries and CTEs ===

class TestSubqueriesAndCTEs:
    """Test subquery and CTE conversions."""
    
    def test_scalar_subquery_hive_to_mysql(self):
        sql = """SELECT name, 
                 (SELECT COUNT(*) FROM orders WHERE user_id = users.id) AS order_count
                 FROM users"""
        result = transpiler.transpile(sql, "hive", "mysql")
        assert result.success
    
    def test_in_subquery_oracle_to_postgres(self):
        sql = """SELECT * FROM products 
                 WHERE category_id IN (SELECT id FROM categories WHERE active = 1)"""
        result = transpiler.transpile(sql, "oracle", "postgres")
        assert result.success
    
    def test_exists_subquery_mysql_to_hive(self):
        sql = """SELECT * FROM users u 
                 WHERE EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id AND o.amount > 100)"""
        result = transpiler.transpile(sql, "mysql", "hive")
        assert result.success
    
    def test_not_exists_tsql_to_spark(self):
        sql = """SELECT * FROM products p
                 WHERE NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.product_id = p.id)"""
        result = transpiler.transpile(sql, "tsql", "spark")
        assert result.success
    
    def test_derived_table_postgres_to_oracle(self):
        sql = """SELECT dept, avg_salary
                 FROM (SELECT dept, AVG(salary) AS avg_salary FROM employees GROUP BY dept) sub
                 WHERE avg_salary > 50000"""
        result = transpiler.transpile(sql, "postgres", "oracle")
        assert result.success
    
    def test_simple_cte_hive_to_trino(self):
        sql = """WITH active_users AS (
                     SELECT * FROM users WHERE status = 'active'
                 )
                 SELECT * FROM active_users WHERE created_at > '2024-01-01'"""
        result = transpiler.transpile(sql, "hive", "trino")
        assert result.success
    
    def test_multiple_ctes_mysql_to_postgres(self):
        sql = """WITH 
                 active_users AS (SELECT * FROM users WHERE status = 1),
                 recent_orders AS (SELECT * FROM orders WHERE created_at > '2024-01-01')
                 SELECT u.name, COUNT(o.id) AS order_count
                 FROM active_users u
                 LEFT JOIN recent_orders o ON u.id = o.user_id
                 GROUP BY u.name"""
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
    
    def test_nested_cte_spark_to_hive(self):
        sql = """WITH 
                 base AS (SELECT * FROM events WHERE event_type = 'click'),
                 aggregated AS (SELECT user_id, COUNT(*) AS clicks FROM base GROUP BY user_id)
                 SELECT u.name, a.clicks
                 FROM users u JOIN aggregated a ON u.id = a.user_id"""
        result = transpiler.transpile(sql, "spark", "hive")
        assert result.success


# === UNION/INTERSECT/EXCEPT Operations ===

class TestSetOperations:
    """Test set operation conversions."""
    
    def test_union_hive_to_mysql(self):
        sql = "SELECT id, name FROM users UNION SELECT id, name FROM admins"
        result = transpiler.transpile(sql, "hive", "mysql")
        assert result.success
    
    def test_union_all_oracle_to_postgres(self):
        sql = "SELECT id FROM table_a UNION ALL SELECT id FROM table_b"
        result = transpiler.transpile(sql, "oracle", "postgres")
        assert result.success
    
    def test_intersect_postgres_to_mysql(self):
        sql = "SELECT id FROM users INTERSECT SELECT user_id FROM orders"
        result = transpiler.transpile(sql, "postgres", "mysql")
        assert result.success
    
    def test_except_tsql_to_hive(self):
        sql = "SELECT id FROM all_users EXCEPT SELECT id FROM banned_users"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_multiple_unions_spark_to_trino(self):
        sql = """SELECT id, 'user' AS type FROM users
                 UNION ALL
                 SELECT id, 'admin' AS type FROM admins
                 UNION ALL
                 SELECT id, 'guest' AS type FROM guests"""
        result = transpiler.transpile(sql, "spark", "trino")
        assert result.success


# === Complex WHERE Clauses with Functions ===

class TestComplexWhereClauses:
    """Test complex WHERE clause conversions."""
    
    def test_date_functions_hive_to_oracle(self):
        sql = """SELECT * FROM orders 
                 WHERE created_at >= DATE_SUB(CURRENT_DATE, 30)
                 AND created_at < CURRENT_DATE"""
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
    
    def test_string_functions_mysql_to_postgres(self):
        sql = """SELECT * FROM users 
                 WHERE LOWER(email) LIKE '%@gmail.com'
                 AND LENGTH(name) > 3"""
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
    
    def test_numeric_conditions_oracle_to_hive(self):
        sql = """SELECT * FROM orders 
                 WHERE amount BETWEEN 100 AND 1000
                 AND MOD(id, 2) = 0
                 AND ROUND(discount, 2) > 0.1"""
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_null_handling_tsql_to_mysql(self):
        sql = """SELECT * FROM users 
                 WHERE email IS NOT NULL
                 AND COALESCE(phone, '') != ''
                 AND name IS NOT NULL"""
        result = transpiler.transpile(sql, "tsql", "mysql")
        assert result.success
    
    def test_case_in_where_postgres_to_spark(self):
        sql = """SELECT * FROM orders 
                 WHERE CASE WHEN status = 1 THEN amount ELSE 0 END > 100"""
        result = transpiler.transpile(sql, "postgres", "spark")
        assert result.success
    
    def test_multiple_or_conditions_hive_to_trino(self):
        sql = """SELECT * FROM users 
                 WHERE (status = 'active' OR status = 'pending')
                 AND (role = 'admin' OR role = 'moderator')"""
        result = transpiler.transpile(sql, "hive", "trino")
        assert result.success
    
    def test_in_with_subquery_mysql_to_oracle(self):
        sql = """SELECT * FROM products 
                 WHERE category_id IN (SELECT id FROM categories WHERE parent_id = 1)
                 AND price > (SELECT AVG(price) FROM products)"""
        result = transpiler.transpile(sql, "mysql", "oracle")
        assert result.success


# === Window Functions ===

class TestWindowFunctions:
    """Test window function conversions across dialects."""
    
    def test_row_number_partition_hive_to_snowflake(self):
        sql = """SELECT *, 
                 ROW_NUMBER() OVER (PARTITION BY dept ORDER BY salary DESC) AS rn
                 FROM employees"""
        result = transpiler.transpile(sql, "hive", "snowflake")
        assert result.success
    
    def test_rank_dense_rank_mysql_to_postgres(self):
        sql = """SELECT *,
                 RANK() OVER (ORDER BY score DESC) AS rnk,
                 DENSE_RANK() OVER (ORDER BY score DESC) AS drnk
                 FROM students"""
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
    
    def test_lag_lead_oracle_to_hive(self):
        sql = """SELECT *,
                 LAG(amount, 1, 0) OVER (PARTITION BY user_id ORDER BY created_at) AS prev_amount,
                 LEAD(amount, 1, 0) OVER (PARTITION BY user_id ORDER BY created_at) AS next_amount
                 FROM orders"""
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_first_last_value_tsql_to_spark(self):
        sql = """SELECT *,
                 FIRST_VALUE(amount) OVER (PARTITION BY user_id ORDER BY created_at) AS first_order,
                 LAST_VALUE(amount) OVER (PARTITION BY user_id ORDER BY created_at) AS last_order
                 FROM orders"""
        result = transpiler.transpile(sql, "tsql", "spark")
        assert result.success
    
    def test_running_sum_postgres_to_trino(self):
        sql = """SELECT *,
                 SUM(amount) OVER (PARTITION BY user_id ORDER BY created_at ROWS UNBOUNDED PRECEDING) AS running_total
                 FROM orders"""
        result = transpiler.transpile(sql, "postgres", "trino")
        assert result.success
    
    def test_moving_average_spark_to_hive(self):
        sql = """SELECT *,
                 AVG(amount) OVER (PARTITION BY user_id ORDER BY created_at ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS moving_avg
                 FROM orders"""
        result = transpiler.transpile(sql, "spark", "hive")
        assert result.success
    
    def test_ntile_hive_to_mysql(self):
        sql = """SELECT *,
                 NTILE(4) OVER (ORDER BY score) AS quartile
                 FROM students"""
        result = transpiler.transpile(sql, "hive", "mysql")
        assert result.success
    
    def test_percent_rank_oracle_to_postgres(self):
        sql = """SELECT *,
                 PERCENT_RANK() OVER (ORDER BY salary) AS pct_rank,
                 CUME_DIST() OVER (ORDER BY salary) AS cume_dist
                 FROM employees"""
        result = transpiler.transpile(sql, "oracle", "postgres")
        assert result.success


# === Aggregation Functions ===

class TestAggregationFunctions:
    """Test aggregation function conversions."""
    
    def test_basic_aggregates_hive_to_mysql(self):
        sql = """SELECT dept,
                 COUNT(*) AS cnt,
                 SUM(salary) AS total_salary,
                 AVG(salary) AS avg_salary,
                 MAX(salary) AS max_salary,
                 MIN(salary) AS min_salary
                 FROM employees GROUP BY dept"""
        result = transpiler.transpile(sql, "hive", "mysql")
        assert result.success
    
    def test_count_distinct_oracle_to_postgres(self):
        sql = "SELECT dept, COUNT(DISTINCT employee_id) AS unique_employees FROM assignments GROUP BY dept"
        result = transpiler.transpile(sql, "oracle", "postgres")
        assert result.success
    
    def test_group_by_having_tsql_to_hive(self):
        sql = """SELECT category, COUNT(*) AS product_count
                 FROM products
                 GROUP BY category
                 HAVING COUNT(*) > 10"""
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_group_by_multiple_columns_mysql_to_spark(self):
        sql = """SELECT year, month, region, SUM(sales) AS total_sales
                 FROM sales_data
                 GROUP BY year, month, region"""
        result = transpiler.transpile(sql, "mysql", "spark")
        assert result.success


# === Date/Time Functions ===

class TestDateTimeFunctions:
    """Test date/time function conversions."""
    
    def test_current_date_hive_to_oracle(self):
        sql = "SELECT CURRENT_DATE, CURRENT_TIMESTAMP FROM dual"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
    
    def test_date_arithmetic_mysql_to_postgres(self):
        sql = "SELECT DATE_ADD(created_at, INTERVAL 7 DAY) FROM orders"
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
    
    def test_extract_parts_oracle_to_hive(self):
        sql = "SELECT EXTRACT(YEAR FROM created_at), EXTRACT(MONTH FROM created_at) FROM orders"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_date_format_tsql_to_mysql(self):
        sql = "SELECT FORMAT(created_at, 'yyyy-MM-dd') FROM orders"
        result = transpiler.transpile(sql, "tsql", "mysql")
        assert result.success
    
    def test_date_trunc_postgres_to_spark(self):
        sql = "SELECT DATE_TRUNC('month', created_at) FROM orders"
        result = transpiler.transpile(sql, "postgres", "spark")
        assert result.success


# === String Functions ===

class TestStringFunctions:
    """Test string function conversions."""
    
    def test_concat_hive_to_oracle(self):
        sql = "SELECT CONCAT(first_name, ' ', last_name) AS full_name FROM users"
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
    
    def test_substring_mysql_to_postgres(self):
        sql = "SELECT SUBSTRING(name, 1, 5) FROM users"
        result = transpiler.transpile(sql, "mysql", "postgres")
        assert result.success
    
    def test_upper_lower_oracle_to_hive(self):
        sql = "SELECT UPPER(name), LOWER(email) FROM users"
        result = transpiler.transpile(sql, "oracle", "hive")
        assert result.success
    
    def test_trim_tsql_to_mysql(self):
        sql = "SELECT LTRIM(RTRIM(name)) FROM users"
        result = transpiler.transpile(sql, "tsql", "mysql")
        assert result.success
    
    def test_replace_postgres_to_spark(self):
        sql = "SELECT REPLACE(description, 'old', 'new') FROM products"
        result = transpiler.transpile(sql, "postgres", "spark")
        assert result.success
    
    def test_length_spark_to_trino(self):
        sql = "SELECT LENGTH(name), CHAR_LENGTH(description) FROM products"
        result = transpiler.transpile(sql, "spark", "trino")
        assert result.success


# === Type Casting ===

class TestTypeCasting:
    """Test type casting conversions."""
    
    def test_cast_to_int_hive_to_mysql(self):
        sql = "SELECT CAST(amount AS INT) FROM orders"
        result = transpiler.transpile(sql, "hive", "mysql")
        assert result.success
    
    def test_cast_to_string_oracle_to_postgres(self):
        sql = "SELECT CAST(id AS VARCHAR(10)) FROM users"
        result = transpiler.transpile(sql, "oracle", "postgres")
        assert result.success
    
    def test_cast_to_decimal_tsql_to_hive(self):
        sql = "SELECT CAST(price AS DECIMAL(10,2)) FROM products"
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
    
    def test_cast_to_date_mysql_to_spark(self):
        sql = "SELECT CAST(date_string AS DATE) FROM events"
        result = transpiler.transpile(sql, "mysql", "spark")
        assert result.success


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
