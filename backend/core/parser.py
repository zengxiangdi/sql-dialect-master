#!/usr/bin/env python3
"""SQL Parser - Parse and analyze SQL statements using sqlglot.

Provides comprehensive SQL parsing with:
- 12 database dialects support
- AST extraction and analysis
- Element extraction (tables, columns, functions, joins)
- Query type detection
"""
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import sqlglot
from sqlglot import exp

# Import from centralized config
from .config import SUPPORTED_DIALECTS

# Configure module logger
logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = ['SUPPORTED_DIALECTS', 'ParseResult', 'SQLParser']


@dataclass
class ParseResult:
    """Result of SQL parsing operation."""
    success: bool
    ast: Optional[exp.Expression] = None
    dialect: str = ""
    error: Optional[str] = None
    tables: List[Dict[str, Any]] = field(default_factory=list)
    columns: List[Dict[str, Any]] = field(default_factory=list)
    functions: List[Dict[str, Any]] = field(default_factory=list)
    joins: List[Dict[str, Any]] = field(default_factory=list)
    query_type: str = ""


class SQLParser:
    """SQL Parser using sqlglot for multi-dialect support.
    
    Supports all 12 dialects:
    - RDBMS: MySQL, PostgreSQL, Oracle, SQL Server (T-SQL)
    - Big Data: Hive, Spark, Trino, Databricks
    - Cloud DW: Snowflake, Redshift
    - OLAP: ClickHouse
    - Embedded: DuckDB
    """
    
    def __init__(self, dialect: str = "hive"):
        """Initialize parser with target dialect.
        
        Args:
            dialect: SQL dialect to use for parsing
            
        Raises:
            ValueError: If dialect is not supported
        """
        dialect_lower = dialect.lower()
        if dialect_lower not in SUPPORTED_DIALECTS:
            raise ValueError(
                f"Unsupported dialect: {dialect}. "
                f"Supported: {', '.join(SUPPORTED_DIALECTS)}"
            )
        self.dialect = dialect_lower
    
    def parse(self, sql: str) -> ParseResult:
        """Parse SQL string into AST.
        
        Args:
            sql: SQL statement to parse
            
        Returns:
            ParseResult with AST and extracted elements
        """
        if not sql or not sql.strip():
            return ParseResult(
                success=False,
                error="Empty SQL statement",
                dialect=self.dialect
            )
        
        try:
            ast = sqlglot.parse_one(sql, read=self.dialect)
            result = ParseResult(
                success=True,
                ast=ast,
                dialect=self.dialect,
                query_type=self._get_query_type(ast)
            )
            result.tables = self._extract_tables(ast)
            result.columns = self._extract_columns(ast)
            result.functions = self._extract_functions(ast)
            result.joins = self._extract_joins(ast)
            return result
        except Exception as e:
            return ParseResult(
                success=False,
                error=str(e),
                dialect=self.dialect
            )
    
    def validate(self, sql: str) -> tuple:
        """Validate SQL syntax.
        
        Args:
            sql: SQL statement to validate
            
        Returns:
            Tuple of (is_valid: bool, error_message: Optional[str])
        """
        if not sql or not sql.strip():
            return False, "Empty SQL statement"
        
        try:
            sqlglot.parse_one(sql, read=self.dialect)
            return True, None
        except Exception as e:
            return False, str(e)
    
    def extract_elements(self, sql: str) -> Dict[str, Any]:
        """Extract all SQL elements for analysis.
        
        Args:
            sql: SQL statement to analyze
            
        Returns:
            Dictionary with extracted elements
        """
        result = self.parse(sql)
        if not result.success:
            return {"error": result.error}
        
        return {
            "query_type": result.query_type,
            "tables": result.tables,
            "columns": result.columns,
            "functions": result.functions,
            "joins": result.joins,
            "has_subquery": self._has_subquery(result.ast),
            "has_cte": self._has_cte(result.ast),
            "has_window": self._has_window_function(result.ast),
            "has_aggregation": self._has_aggregation(result.ast),
            "has_distinct": self._has_distinct(result.ast),
            "has_union": self._has_union(result.ast),
            "has_order_by": self._has_order_by(result.ast),
            "has_limit": self._has_limit(result.ast),
        }
    
    def get_complexity_score(self, sql: str) -> Dict[str, Any]:
        """Calculate SQL complexity score.
        
        Args:
            sql: SQL statement to analyze
            
        Returns:
            Dictionary with complexity metrics
        """
        result = self.parse(sql)
        if not result.success:
            return {"error": result.error, "score": 0}
        
        score = 1  # Base score
        factors = []
        
        # Add complexity for various features
        if result.joins:
            join_score = len(result.joins) * 2
            score += join_score
            factors.append(f"Joins: +{join_score}")
        
        if self._has_subquery(result.ast):
            score += 3
            factors.append("Subquery: +3")
        
        if self._has_cte(result.ast):
            score += 2
            factors.append("CTE: +2")
        
        if self._has_window_function(result.ast):
            score += 2
            factors.append("Window function: +2")
        
        if self._has_aggregation(result.ast):
            score += 1
            factors.append("Aggregation: +1")
        
        if self._has_union(result.ast):
            score += 2
            factors.append("UNION: +2")
        
        # Complexity level
        if score <= 2:
            level = "Simple"
        elif score <= 5:
            level = "Moderate"
        elif score <= 10:
            level = "Complex"
        else:
            level = "Very Complex"
        
        return {
            "score": score,
            "level": level,
            "factors": factors,
            "tables_count": len(result.tables),
            "columns_count": len(result.columns),
            "functions_count": len(result.functions),
            "joins_count": len(result.joins)
        }
    
    def _get_query_type(self, ast: exp.Expression) -> str:
        """Determine the type of SQL query."""
        type_map = {
            exp.Select: "SELECT",
            exp.Insert: "INSERT",
            exp.Update: "UPDATE",
            exp.Delete: "DELETE",
            exp.Create: "CREATE",
            exp.Drop: "DROP",
            exp.Alter: "ALTER",
            exp.Merge: "MERGE",
            exp.Union: "UNION",
        }
        for exp_type, name in type_map.items():
            if isinstance(ast, exp_type):
                return name
        return "UNKNOWN"
    
    def _extract_tables(self, ast: exp.Expression) -> List[Dict[str, Any]]:
        """Extract all table references."""
        tables = []
        seen = set()
        
        for table in ast.find_all(exp.Table):
            key = (table.name, table.alias)
            if key not in seen:
                seen.add(key)
                tables.append({
                    "name": table.name,
                    "alias": table.alias if table.alias else None,
                    "schema": table.db if hasattr(table, 'db') and table.db else None,
                    "catalog": table.catalog if hasattr(table, 'catalog') and table.catalog else None
                })
        return tables
    
    def _extract_columns(self, ast: exp.Expression) -> List[Dict[str, Any]]:
        """Extract all column references."""
        columns = []
        seen = set()
        
        for col in ast.find_all(exp.Column):
            key = (col.name, col.table)
            if key not in seen:
                seen.add(key)
                columns.append({
                    "name": col.name,
                    "table": col.table if col.table else None,
                    "alias": None  # Column aliases are in Alias nodes
                })
        return columns
    
    def _extract_functions(self, ast: exp.Expression) -> List[Dict[str, Any]]:
        """Extract all function calls."""
        functions = []
        seen = set()
        
        for func in ast.find_all(exp.Func):
            name = func.sql_name() if hasattr(func, 'sql_name') else type(func).__name__
            if name not in seen:
                seen.add(name)
                functions.append({
                    "name": name,
                    "args_count": len(func.args) if hasattr(func, 'args') else 0,
                    "is_aggregate": isinstance(func, (exp.AggFunc,)),
                    "is_window": False  # Will be updated if in window context
                })
        return functions
    
    def _extract_joins(self, ast: exp.Expression) -> List[Dict[str, Any]]:
        """Extract all JOIN operations."""
        joins = []
        for join in ast.find_all(exp.Join):
            join_type = "INNER"
            if join.kind:
                join_type = join.kind.upper()
            elif join.side:
                join_type = f"{join.side.upper()} OUTER"
            
            table_name = ""
            if hasattr(join.this, 'name'):
                table_name = join.this.name
            elif hasattr(join.this, 'alias'):
                table_name = str(join.this)
            else:
                table_name = str(join.this)
            
            joins.append({
                "type": join_type,
                "table": table_name,
                "on_condition": str(join.args.get('on')) if join.args.get('on') else None
            })
        return joins
    
    def _has_subquery(self, ast: exp.Expression) -> bool:
        """Check if query contains subqueries."""
        return len(list(ast.find_all(exp.Subquery))) > 0
    
    def _has_cte(self, ast: exp.Expression) -> bool:
        """Check if query contains CTEs (WITH clause)."""
        return ast.find(exp.With) is not None
    
    def _has_window_function(self, ast: exp.Expression) -> bool:
        """Check if query contains window functions."""
        return len(list(ast.find_all(exp.Window))) > 0
    
    def _has_aggregation(self, ast: exp.Expression) -> bool:
        """Check if query contains GROUP BY."""
        return ast.find(exp.Group) is not None
    
    def _has_distinct(self, ast: exp.Expression) -> bool:
        """Check if query contains DISTINCT."""
        return ast.find(exp.Distinct) is not None
    
    def _has_union(self, ast: exp.Expression) -> bool:
        """Check if query contains UNION."""
        return isinstance(ast, exp.Union) or ast.find(exp.Union) is not None
    
    def _has_order_by(self, ast: exp.Expression) -> bool:
        """Check if query contains ORDER BY."""
        return ast.find(exp.Order) is not None
    
    def _has_limit(self, ast: exp.Expression) -> bool:
        """Check if query contains LIMIT."""
        return ast.find(exp.Limit) is not None or ast.find(exp.Fetch) is not None
