#!/usr/bin/env python3
"""Basic usage examples for SQL Dialect Master."""

from backend.core import SQLTranspiler, NL2SQLGenerator, FunctionEncyclopedia, TypeMapper

# =============================================================================
# 1. SQL Conversion
# =============================================================================
print("=" * 60)
print("1. SQL Conversion Examples")
print("=" * 60)

transpiler = SQLTranspiler()

# MySQL to PostgreSQL
result = transpiler.transpile(
    sql="SELECT DATE_FORMAT(created_at, '%Y-%m-%d') FROM orders LIMIT 10",
    source="mysql",
    target="postgres"
)
print(f"\nMySQL → PostgreSQL:")
print(f"Input:  SELECT DATE_FORMAT(created_at, '%Y-%m-%d') FROM orders LIMIT 10")
print(f"Output: {result.target_sql}")

# Hive to Oracle
result = transpiler.transpile(
    sql="SELECT COLLECT_LIST(name) FROM users GROUP BY dept",
    source="hive",
    target="oracle"
)
print(f"\nHive → Oracle:")
print(f"Input:  SELECT COLLECT_LIST(name) FROM users GROUP BY dept")
print(f"Output: {result.target_sql}")

# =============================================================================
# 2. NL2SQL (Natural Language to SQL)
# =============================================================================
print("\n" + "=" * 60)
print("2. NL2SQL Examples")
print("=" * 60)

generator = NL2SQLGenerator()

# Chinese input
result = generator.generate("查询最近7天的订单", dialect="mysql")
print(f"\n输入: 查询最近7天的订单")
print(f"SQL:  {result.sql}")
print(f"置信度: {result.confidence:.0%}")

# English input
result = generator.generate("get top 10 users by score", dialect="postgres")
print(f"\nInput: get top 10 users by score")
print(f"SQL:   {result.sql}")
print(f"Confidence: {result.confidence:.0%}")

# =============================================================================
# 3. Function Encyclopedia
# =============================================================================
print("\n" + "=" * 60)
print("3. Function Encyclopedia")
print("=" * 60)

encyclopedia = FunctionEncyclopedia()

# Search functions
results = encyclopedia.search("DATE", limit=3)
print("\nSearch 'DATE' functions:")
for func in results:
    print(f"  - {func['name']}: {func.get('description', '')}")

# Compare function across dialects
comparison = encyclopedia.compare_dialects("CONCAT")
print(f"\nCONCAT function across dialects:")
for dialect, syntax in list(comparison['dialects'].items())[:4]:
    print(f"  {dialect}: {syntax}")

# =============================================================================
# 4. Type Mapping
# =============================================================================
print("\n" + "=" * 60)
print("4. Type Mapping")
print("=" * 60)

mapper = TypeMapper()

# Map VARCHAR from MySQL to Oracle
result = mapper.map_type("VARCHAR", "mysql", "oracle")
print(f"\nVARCHAR: MySQL → Oracle")
print(f"  MySQL:  {result['source_type']}")
print(f"  Oracle: {result['target_type']}")

# Map ARRAY from Hive to PostgreSQL
result = mapper.map_type("ARRAY", "hive", "postgres")
print(f"\nARRAY: Hive → PostgreSQL")
print(f"  Hive:     {result['source_type']}")
print(f"  Postgres: {result['target_type']}")

print("\n" + "=" * 60)
print("Done!")
print("=" * 60)
