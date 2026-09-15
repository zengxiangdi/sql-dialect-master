"""Templates for SQL Dialect Master v2.

Cleaned-up template library without emoji clutter.
"""
from __future__ import annotations

TEMPLATES: dict[str, str] = {
    "Basic Queries": [
        ("Basic SELECT", "SELECT * FROM users WHERE id = 1"),
        ("DISTINCT with ORDER", "SELECT DISTINCT category, brand FROM products ORDER BY category, brand"),
        ("COALESCE null handling", "SELECT id, COALESCE(nickname, username, email, 'Anonymous') AS display_name FROM users"),
    ],
    "Aggregations": [
        ("Group aggregation", "SELECT dept, COUNT(*) AS cnt, AVG(salary) AS avg_sal FROM employees GROUP BY dept"),
        ("HAVING filter", "SELECT dept, COUNT(*) AS emp_count FROM employees GROUP BY dept HAVING COUNT(*) > 5 ORDER BY emp_count DESC"),
        ("Multiple aggregates", "SELECT category, COUNT(*) AS cnt, SUM(price) AS total, AVG(price) AS avg_price FROM products GROUP BY category"),
    ],
    "Joins": [
        ("Multi-table JOIN", "SELECT u.name, o.order_id, p.product_name FROM users u JOIN orders o ON u.id = o.user_id JOIN products p ON o.product_id = p.id"),
        ("LEFT JOIN with NULL", "SELECT u.name, COUNT(o.id) AS order_count FROM users u LEFT JOIN orders o ON u.id = o.user_id GROUP BY u.name"),
        ("Self JOIN", "SELECT e.name AS employee, m.name AS manager FROM employees e LEFT JOIN employees m ON e.manager_id = m.id"),
    ],
    "Window Functions": [
        ("ROW_NUMBER", "SELECT *, ROW_NUMBER() OVER (PARTITION BY dept ORDER BY salary DESC) AS rn FROM employees"),
        ("LAG/LEAD", "SELECT date, amount, LAG(amount, 1, 0) OVER (ORDER BY date) AS prev_amount FROM sales"),
        ("Running total", "SELECT date, amount, SUM(amount) OVER (ORDER BY date ROWS UNBOUNDED PRECEDING) AS running_total FROM sales"),
    ],
    "Subqueries": [
        ("Subquery IN clause", "SELECT * FROM products WHERE category_id IN (SELECT id FROM categories WHERE status = 'active')"),
        ("Correlated subquery", "SELECT * FROM employees e WHERE salary > (SELECT AVG(salary) FROM employees WHERE dept = e.dept)"),
        ("EXISTS subquery", "SELECT * FROM customers c WHERE EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id AND o.amount > 1000)"),
    ],
    "CTEs": [
        ("Basic CTE", "WITH active_users AS (SELECT * FROM users WHERE status = 'active') SELECT * FROM active_users WHERE created_at > '2024-01-01'"),
        ("Multiple CTEs", "WITH sales_2024 AS (SELECT * FROM sales WHERE YEAR(date) = 2024), top_products AS (SELECT product_id, SUM(amount) AS total FROM sales_2024 GROUP BY product_id) SELECT * FROM top_products ORDER BY total DESC LIMIT 10"),
    ],
    "Date Operations": [
        ("Date extraction", "SELECT YEAR(created_at) AS year, MONTH(created_at) AS month, COUNT(*) AS cnt FROM orders GROUP BY YEAR(created_at), MONTH(created_at)"),
        ("Date arithmetic", "SELECT id, created_at, DATE_ADD(created_at, 30) AS expires_at FROM subscriptions"),
        ("Date formatting", "SELECT id, DATE_FORMAT(created_at, '%Y-%m-%d') AS formatted_date FROM orders"),
    ],
    "Set Operations": [
        ("UNION ALL", "SELECT 'Q1' AS quarter, SUM(amount) AS total FROM sales WHERE month <= 3 UNION ALL SELECT 'Q2', SUM(amount) FROM sales WHERE month BETWEEN 4 AND 6"),
        ("INTERSECT", "SELECT user_id FROM orders WHERE YEAR(created_at) = 2023 INTERSECT SELECT user_id FROM orders WHERE YEAR(created_at) = 2024"),
        ("EXCEPT", "SELECT user_id FROM users EXCEPT SELECT DISTINCT user_id FROM orders"),
    ],
}

# Flatten for compatibility with old lookup pattern
FLAT_TEMPLATES: dict[str, str] = {}
for cat, items in TEMPLATES.items():
    for label, sql in items:
        FLAT_TEMPLATES[f"{cat} · {label}"] = sql
