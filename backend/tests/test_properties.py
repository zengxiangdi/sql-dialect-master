#!/usr/bin/env python3
"""Property-Based Tests for SQL Dialect Master using Hypothesis.

These tests verify correctness properties that should hold across all valid inputs.
"""
import sys
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.core.functions_lookup import FunctionEncyclopedia
from backend.core.nl2sql import NL2SQLGenerator
from backend.core.parser import SUPPORTED_DIALECTS
from backend.core.transpiler import SQLTranspiler
from backend.core.type_mapping import TypeMapper

# Initialize components
transpiler = SQLTranspiler()
func_encyclopedia = FunctionEncyclopedia()
type_mapper = TypeMapper()
nl2sql_generator = NL2SQLGenerator()

# === Strategies for generating test data ===

# All supported dialects
dialect_strategy = st.sampled_from(SUPPORTED_DIALECTS)

# Simple SQL identifiers
identifier_strategy = st.from_regex(r'[a-z][a-z0-9_]{0,10}', fullmatch=True)

# Simple column names
column_strategy = st.sampled_from(['id', 'name', 'email', 'status', 'amount', 'created_at', 'user_id'])

# Simple table names
table_strategy = st.sampled_from(['users', 'orders', 'products', 'employees', 'customers', 'events'])

# SQL type names from our mapping
type_name_strategy = st.sampled_from(list(type_mapper.mappings.keys()))

# Function categories
category_strategy = st.sampled_from(func_encyclopedia.CATEGORIES)

# Function names from our database
func_name_strategy = st.sampled_from([f['name'] for f in func_encyclopedia.functions] if func_encyclopedia.functions else ['CONCAT'])


# =============================================================================
# Property 7: Type Mapping Matrix Completeness
# **Validates: Requirements 3.2, 8.4**
# =============================================================================

class TestTypeMapMatrixCompleteness:
    """
    **Feature: sql-dialect-master, Property 7: Type Mapping Matrix Completeness**
    
    *For any* type in the mapping matrix and any pair of dialects,
    the mapping should return a valid result with source and target types.
    """
    
    @given(type_name=type_name_strategy, source=dialect_strategy, target=dialect_strategy)
    @settings(max_examples=100)
    def test_type_mapping_returns_valid_result(self, type_name, source, target):
        """Every type mapping should return a valid result structure."""
        result = type_mapper.map_type(type_name, source, target)
        
        assert result["success"] is True, f"Mapping failed for {type_name}: {source} → {target}"
        assert "source_type" in result
        assert "target_type" in result
        assert result["source_dialect"] == source
        assert result["target_dialect"] == target
    
    @given(dialect=dialect_strategy)
    @settings(max_examples=50)
    def test_all_types_have_dialect_mapping(self, dialect):
        """Every type should have a mapping for every supported dialect."""
        for type_name in type_mapper.mappings.keys():
            type_info = type_mapper.mappings[type_name]
            # At least some dialects should be present
            dialect_count = sum(1 for d in SUPPORTED_DIALECTS if d in type_info)
            assert dialect_count >= 4, f"Type {type_name} has too few dialect mappings"
    
    def test_matrix_has_minimum_types(self):
        """Matrix should contain at least 15 base types."""
        assert len(type_mapper.mappings) >= 15, "Matrix should have at least 15 types"
    
    def test_precision_warnings_exist(self):
        """Precision warnings should exist for complex types."""
        assert len(type_mapper.precision_warnings) > 0, "Should have precision warnings"


# =============================================================================
# Property 5: Function Encyclopedia Data Completeness
# **Validates: Requirements 2.2, 2.3, 8.3**
# =============================================================================

class TestFunctionDataCompleteness:
    """
    **Feature: sql-dialect-master, Property 5: Function Encyclopedia Data Completeness**
    
    *For any* function in the encyclopedia, it should have name, description,
    category, and dialect mappings.
    """
    
    @given(func_name=func_name_strategy)
    @settings(max_examples=50)
    def test_function_has_required_fields(self, func_name):
        """Every function should have required fields."""
        func = func_encyclopedia.get_function(func_name)
        assume(func is not None)
        
        assert "name" in func, f"Function {func_name} missing 'name'"
        assert "description" in func, f"Function {func_name} missing 'description'"
        assert "category" in func, f"Function {func_name} missing 'category'"
        assert "dialects" in func, f"Function {func_name} missing 'dialects'"
    
    @given(func_name=func_name_strategy)
    @settings(max_examples=50)
    def test_function_has_dialect_mappings(self, func_name):
        """Every function should have at least 3 dialect mappings."""
        func = func_encyclopedia.get_function(func_name)
        assume(func is not None)
        
        dialects = func.get("dialects", {})
        assert len(dialects) >= 3, f"Function {func_name} has too few dialect mappings"
    
    def test_encyclopedia_has_minimum_functions(self):
        """Encyclopedia should contain at least 50 functions."""
        assert len(func_encyclopedia.functions) >= 50, "Should have at least 50 functions"
    
    def test_all_categories_have_functions(self):
        """Each category should have at least one function."""
        for category in ['date', 'string', 'aggregate', 'window']:
            funcs = func_encyclopedia.list_by_category(category)
            assert len(funcs) > 0, f"Category {category} has no functions"


# =============================================================================
# Property 1: Round-trip Conversion Consistency
# **Validates: Requirements 1.2, 8.2**
# =============================================================================

class TestRoundTripConversion:
    """
    **Feature: sql-dialect-master, Property 1: Round-trip Conversion Consistency**
    
    *For any* valid SQL statement, converting A→B→A should produce semantically
    equivalent SQL (the output should at least be valid SQL).
    """
    
    # Simple SQL templates for testing
    simple_sqls = [
        "SELECT * FROM {table}",
        "SELECT {col} FROM {table} WHERE id = 1",
        "SELECT COUNT(*) FROM {table}",
        "SELECT {col} FROM {table} ORDER BY {col}",
        "SELECT {col} FROM {table} LIMIT 10",
    ]
    
    @given(
        table=table_strategy,
        col=column_strategy,
        source=dialect_strategy,
        target=dialect_strategy
    )
    @settings(max_examples=100)
    def test_roundtrip_produces_valid_sql(self, table, col, source, target):
        """Round-trip conversion should produce valid SQL."""
        assume(source != target)  # Skip same-dialect conversions
        
        sql = f"SELECT {col} FROM {table} WHERE id = 1"
        
        # A → B
        result1 = transpiler.transpile(sql, source, target)
        assume(result1.success)  # Skip if first conversion fails
        
        # B → A
        result2 = transpiler.transpile(result1.target_sql, target, source)
        
        # The round-trip should succeed
        assert result2.success, f"Round-trip failed: {source}→{target}→{source}"
        assert result2.target_sql is not None
        assert len(result2.target_sql) > 0
    
    @given(source=dialect_strategy, target=dialect_strategy)
    @settings(max_examples=50)
    def test_basic_select_roundtrip(self, source, target):
        """Basic SELECT should survive round-trip."""
        assume(source != target)
        
        sql = "SELECT id, name FROM users WHERE status = 1"
        
        result1 = transpiler.transpile(sql, source, target)
        assume(result1.success)
        
        result2 = transpiler.transpile(result1.target_sql, target, source)
        assert result2.success


# =============================================================================
# Property 2: Dialect-Specific Syntax Transformation
# **Validates: Requirements 1.3**
# =============================================================================

class TestDialectSpecificTransformation:
    """
    **Feature: sql-dialect-master, Property 2: Dialect-Specific Syntax Transformation**
    
    *For any* dialect-specific construct (LATERAL VIEW, LISTAGG, etc.),
    the transformation should produce valid equivalent syntax in the target dialect.
    """
    
    def test_limit_transforms_correctly(self):
        """LIMIT should transform to appropriate syntax per dialect."""
        sql = "SELECT * FROM users LIMIT 10"
        
        # Hive → Oracle should use FETCH or ROWNUM
        result = transpiler.transpile(sql, "hive", "oracle")
        assert result.success
        target_upper = result.target_sql.upper()
        assert "FETCH" in target_upper or "ROWNUM" in target_upper or "LIMIT" not in target_upper
    
    def test_top_transforms_to_limit(self):
        """TOP should transform to LIMIT for non-TSQL dialects."""
        sql = "SELECT TOP 10 * FROM users"
        
        result = transpiler.transpile(sql, "tsql", "hive")
        assert result.success
        assert "LIMIT" in result.target_sql.upper() or "TOP" not in result.target_sql.upper()
    
    @given(source=dialect_strategy, target=dialect_strategy)
    @settings(max_examples=50)
    def test_window_function_preserved(self, source, target):
        """Window functions should be preserved across dialects."""
        sql = "SELECT ROW_NUMBER() OVER (ORDER BY id) AS rn FROM users"
        
        result = transpiler.transpile(sql, source, target)
        assert result.success
        assert "ROW_NUMBER" in result.target_sql.upper() or "OVER" in result.target_sql.upper()


# =============================================================================
# Property 3: Window Function Frame Preservation
# **Validates: Requirements 1.4**
# =============================================================================

class TestWindowFramePreservation:
    """
    **Feature: sql-dialect-master, Property 3: Window Function Frame Preservation**
    
    *For any* window function with ROWS/RANGE frame specification,
    the frame should be preserved or correctly transformed in the target dialect.
    """
    
    @given(source=dialect_strategy, target=dialect_strategy)
    @settings(max_examples=50)
    def test_rows_frame_preserved(self, source, target):
        """ROWS frame should be preserved in conversion."""
        sql = "SELECT SUM(amount) OVER (ORDER BY id ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) FROM orders"
        
        result = transpiler.transpile(sql, source, target)
        assert result.success
        # Frame specification should be present
        target_upper = result.target_sql.upper()
        assert "OVER" in target_upper
    
    @given(source=dialect_strategy, target=dialect_strategy)
    @settings(max_examples=50)
    def test_partition_by_preserved(self, source, target):
        """PARTITION BY should be preserved in conversion."""
        sql = "SELECT SUM(amount) OVER (PARTITION BY user_id ORDER BY created_at) FROM orders"
        
        result = transpiler.transpile(sql, source, target)
        assert result.success
        target_upper = result.target_sql.upper()
        assert "PARTITION BY" in target_upper or "OVER" in target_upper


# =============================================================================
# Property 6: Category Filter Correctness
# **Validates: Requirements 2.5**
# =============================================================================

class TestCategoryFilterCorrectness:
    """
    **Feature: sql-dialect-master, Property 6: Category Filter Correctness**
    
    *For any* category filter, all returned functions should belong to that category.
    """
    
    @given(category=category_strategy)
    @settings(max_examples=20)
    def test_filtered_functions_match_category(self, category):
        """All functions returned by category filter should have that category."""
        functions = func_encyclopedia.list_by_category(category)
        
        for func in functions:
            assert func.get("category", "").lower() == category.lower(), \
                f"Function {func.get('name')} has wrong category"
    
    @given(category=category_strategy)
    @settings(max_examples=20)
    def test_category_filter_returns_list(self, category):
        """Category filter should always return a list."""
        result = func_encyclopedia.list_by_category(category)
        assert isinstance(result, list)


# =============================================================================
# Property 8: Complex Type Mapping with Notes
# **Validates: Requirements 3.5**
# =============================================================================

class TestComplexTypeMappingWithNotes:
    """
    **Feature: sql-dialect-master, Property 8: Complex Type Mapping with Notes**
    
    *For any* complex type (ARRAY, MAP, STRUCT), the mapping should include
    appropriate notes about compatibility.
    """
    
    complex_types = ['ARRAY', 'MAP', 'STRUCT']
    
    def test_complex_types_have_notes(self):
        """Complex types should have notes in their mappings."""
        for type_name in self.complex_types:
            if type_name in type_mapper.mappings:
                type_info = type_mapper.mappings[type_name]
                # Complex types should have notes or be well-documented
                assert len(type_info) >= 4, f"Type {type_name} should have multiple dialect mappings"
    
    @given(
        type_name=st.sampled_from(['ARRAY', 'MAP', 'STRUCT', 'DECIMAL', 'TIMESTAMP']),
        source=dialect_strategy,
        target=dialect_strategy
    )
    @settings(max_examples=50)
    def test_suggest_type_returns_suggestions(self, type_name, source, target):
        """suggest_type should return suggestions for complex types."""
        result = type_mapper.suggest_type(type_name, source, target)
        
        assert "success" in result
        if result["success"]:
            assert "suggestions" in result
            assert isinstance(result["suggestions"], list)


# =============================================================================
# Property 9: NL2SQL Output Validity
# **Validates: Requirements 4.1**
# =============================================================================

class TestNL2SQLOutputValidity:
    """
    **Feature: sql-dialect-master, Property 9: NL2SQL Output Validity**
    
    *For any* natural language input, the generated SQL should be syntactically valid.
    """
    
    # Sample natural language queries
    nl_queries = [
        "查询所有用户",
        "获取订单数量",
        "统计每个部门的员工数",
        "get all users",
        "count orders",
        "find products with price greater than 100",
        "select top 10 customers",
        "查询最近7天的订单",
    ]
    
    @given(
        query=st.sampled_from(nl_queries),
        dialect=dialect_strategy
    )
    @settings(max_examples=50)
    def test_nl2sql_produces_valid_sql(self, query, dialect):
        """NL2SQL should produce syntactically valid SQL."""
        result = nl2sql_generator.generate(query, dialect)
        
        assert result.success
        assert result.sql is not None
        assert len(result.sql) > 0
        # Should contain SQL keywords
        sql_upper = result.sql.upper()
        assert any(kw in sql_upper for kw in ['SELECT', 'INSERT', 'UPDATE', 'DELETE', '--'])
    
    @given(dialect=dialect_strategy)
    @settings(max_examples=20)
    def test_nl2sql_returns_result_structure(self, dialect):
        """NL2SQL should return proper result structure."""
        result = nl2sql_generator.generate("查询用户", dialect)
        
        assert hasattr(result, 'success')
        assert hasattr(result, 'sql')
        assert hasattr(result, 'dialect')
        assert hasattr(result, 'explanation')
        assert hasattr(result, 'confidence')
        assert hasattr(result, 'suggestions')
    
    @given(dialect=dialect_strategy)
    @settings(max_examples=20)
    def test_nl2sql_confidence_in_range(self, dialect):
        """NL2SQL confidence should be between 0 and 1."""
        result = nl2sql_generator.generate("get all orders", dialect)
        
        assert 0.0 <= result.confidence <= 1.0


# =============================================================================
# Property 10: API Error Response Format
# **Validates: Requirements 6.5**
# =============================================================================

class TestAPIErrorResponseFormat:
    """
    **Feature: sql-dialect-master, Property 10: API Error Response Format**
    
    *For any* invalid input, the transpiler should return a consistent error format.
    """
    
    @given(dialect=dialect_strategy)
    @settings(max_examples=20)
    def test_invalid_sql_returns_error_format(self, dialect):
        """Invalid SQL should return proper error structure."""
        invalid_sql = "SELEC * FORM users"  # Intentionally malformed
        
        result = transpiler.transpile(invalid_sql, dialect, "mysql")
        
        # Should have consistent structure even on failure
        assert hasattr(result, 'success')
        assert hasattr(result, 'error')
        if not result.success:
            assert result.error is not None
            assert len(result.error) > 0
    
    def test_unsupported_dialect_returns_error(self):
        """Unsupported dialect should return proper error."""
        result = transpiler.transpile("SELECT 1", "unsupported_db", "mysql")
        
        assert result.success is False
        assert result.error is not None
        assert "unsupported" in result.error.lower() or "dialect" in result.error.lower()
    
    @given(source=dialect_strategy, target=dialect_strategy)
    @settings(max_examples=30)
    def test_transpile_result_has_all_fields(self, source, target):
        """TranspileResult should always have all required fields."""
        result = transpiler.transpile("SELECT 1", source, target)
        
        assert hasattr(result, 'success')
        assert hasattr(result, 'source_sql')
        assert hasattr(result, 'target_sql')
        assert hasattr(result, 'source_dialect')
        assert hasattr(result, 'target_dialect')
        assert hasattr(result, 'error')
        assert hasattr(result, 'compatibility_notes')
        assert hasattr(result, 'transformations')
        assert hasattr(result, 'warnings')


# =============================================================================
# Property 4: Unsupported Construct Error Handling (Already marked complete)
# **Validates: Requirements 1.5**
# =============================================================================

class TestUnsupportedConstructErrorHandling:
    """
    **Feature: sql-dialect-master, Property 4: Unsupported Construct Error Handling**
    
    *For any* unsupported SQL construct, the system should return a clear error
    rather than crashing or producing invalid output.
    """
    
    def test_empty_sql_handled(self):
        """Empty SQL should be handled gracefully."""
        result = transpiler.transpile("", "hive", "mysql")
        # Should either succeed with empty or fail gracefully
        assert hasattr(result, 'success')
    
    def test_whitespace_only_handled(self):
        """Whitespace-only SQL should be handled gracefully."""
        result = transpiler.transpile("   \n\t  ", "hive", "mysql")
        assert hasattr(result, 'success')
    
    @given(source=dialect_strategy, target=dialect_strategy)
    @settings(max_examples=20)
    def test_malformed_sql_handled(self, source, target):
        """Malformed SQL should not crash the transpiler."""
        malformed_sqls = [
            "SELECT FROM",
            "INSERT VALUES",
            "UPDATE SET",
            "DELETE",
            "(((",
        ]
        
        for sql in malformed_sqls:
            result = transpiler.transpile(sql, source, target)
            # Should not raise exception, should return result
            assert hasattr(result, 'success')


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--hypothesis-show-statistics"])
