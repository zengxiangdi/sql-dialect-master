#!/usr/bin/env python3
"""Type Mapper - Map SQL data types between different database dialects.

Provides comprehensive data type mapping with:
- 36 data types across 7 categories
- 12 database dialects support
- Precision and compatibility warnings
- Type conversion suggestions
"""
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

from .config import SUPPORTED_DIALECTS, TYPE_CATEGORIES, TypeMappingInfo
from .exceptions import ConfigurationError
from .p2_data_validation import _validate_type_mapping_entry

# Configure module logger
logger = logging.getLogger(__name__)


class TypeMapper:
    """SQL Type Mapper with 36 types × 12 dialects matrix support.
    
    Features:
    - 36 data types (STRING, VARCHAR, INT, DECIMAL, DATE, ARRAY, JSON, etc.)
    - 12 database dialects
    - Precision warnings for DECIMAL, TIMESTAMP, VARCHAR
    - Type conversion suggestions
    """
    
    DIALECTS = SUPPORTED_DIALECTS
    TYPE_CATEGORIES = TYPE_CATEGORIES
    # Explicit aliases preserve deterministic resolution without fuzzy matching.
    TYPE_ALIASES = {
        "INTEGER": "INT",
    }
    
    def __init__(self, data_path: Optional[Path] = None):
        """Initialize mapper with type mapping data.
        
        Args:
            data_path: Path to type_mapping.json. Uses default if None.
        """
        if data_path is None:
            data_path = Path(__file__).parent / "type_mapping.json"
        self.data_path = data_path
        self.data = self._load_data()
        self.mappings: Dict[str, TypeMappingInfo] = self.data.get("mappings", {})
        self.precision_warnings: Dict[str, str] = self.data.get("precision_warnings", {})
    
    def _load_data(self) -> dict:
        """Load and validate type mapping data from JSON file."""
        try:
            with open(self.data_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(
                f"Unable to load type mapping data from {self.data_path}: {exc}",
                details={"data_path": str(self.data_path)},
            ) from exc

        if not isinstance(data, dict):
            raise ConfigurationError(
                f"Invalid type mapping data in {self.data_path}: top-level JSON value must be an object",
                details={"data_path": str(self.data_path)},
            )

        mappings = data.get("mappings", {})
        if not isinstance(mappings, dict):
            raise ConfigurationError(
                f"Invalid type mapping data in {self.data_path}: 'mappings' must be an object",
                details={"data_path": str(self.data_path)},
            )

        precision_warnings = data.get("precision_warnings", {})
        if not isinstance(precision_warnings, dict):
            raise ConfigurationError(
                f"Invalid type mapping data in {self.data_path}: 'precision_warnings' must be an object",
                details={"data_path": str(self.data_path)},
            )
        for name, entry in mappings.items():
            _validate_type_mapping_entry(self.data_path, name, entry)
        for name, warning in precision_warnings.items():
            if not isinstance(name, str) or not name.strip() or not isinstance(warning, str):
                raise ConfigurationError(
                    f"Invalid runtime data in {self.data_path}: precision_warnings must map non-empty strings to strings",
                    details={"data_path": str(self.data_path)},
                )

        return data
    
    def map_type(self, type_name: str, source: str, target: str) -> Dict[str, Any]:
        """Map a type from source dialect to target dialect.
        
        Args:
            type_name: Data type name
            source: Source dialect
            target: Target dialect
            
        Returns:
            Dictionary with mapping result
        """
        type_name = type_name.upper()
        source = source.lower()
        target = target.lower()

        invalid_dialects = [
            dialect for dialect in (source, target) if dialect not in SUPPORTED_DIALECTS
        ]
        if invalid_dialects:
            return {
                "success": False,
                "error": (
                    f"Unsupported dialect(s): {', '.join(invalid_dialects)}. "
                    f"Supported: {SUPPORTED_DIALECTS}"
                ),
                "source_type": type_name,
                "target_type": None,
                "source_dialect": source,
                "target_dialect": target,
            }
        
        # Resolve exact canonical names first, then only explicitly supported aliases.
        canonical_type_name = type_name
        type_info = self.mappings.get(type_name)
        if not type_info:
            canonical_type_name = self.TYPE_ALIASES.get(type_name, type_name)
            type_info = self.mappings.get(canonical_type_name)
        
        if not type_info:
            return {
                "success": False,
                "error": f"Type {type_name} not found in mappings",
                "source_type": type_name,
                "target_type": None,
                "source_dialect": source,
                "target_dialect": target
            }
        
        source_type = type_info.get(source, "N/A")
        target_type = type_info.get(target, "N/A")
        notes = type_info.get("notes", "")
        
        # Check for precision warnings
        warnings = []
        if canonical_type_name in self.precision_warnings:
            warnings.append(self.precision_warnings[canonical_type_name])
        
        # Add specific warnings based on type and dialects
        warnings.extend(self._get_type_specific_warnings(canonical_type_name, source, target))
        
        return {
            "success": True,
            "type_name": type_name,
            "source_dialect": source,
            "target_dialect": target,
            "source_type": source_type,
            "target_type": target_type,
            "notes": notes,
            "warnings": warnings,
            "category": self.get_type_category(canonical_type_name)
        }
    
    def _get_type_specific_warnings(
        self,
        type_name: str,
        source: str,
        target: str
    ) -> List[str]:
        """Get type-specific warnings for a conversion.
        
        Args:
            type_name: Data type name
            source: Source dialect
            target: Target dialect
            
        Returns:
            List of warning messages
        """
        warnings = []
        
        # Array/Map/Struct warnings
        if type_name in ["ARRAY", "MAP", "STRUCT"]:
            if target in ["mysql", "oracle", "tsql"]:
                warnings.append(
                    f"{type_name} is stored as JSON in {target} - "
                    "native array operations not available"
                )
        
        # UUID warnings
        if type_name == "UUID":
            if target not in ["postgres", "tsql", "clickhouse", "duckdb"]:
                warnings.append(
                    f"UUID stored as CHAR(36) in {target} - "
                    "consider indexing implications"
                )
        
        # JSON warnings
        if type_name in ["JSON", "JSONB"]:
            if target == "snowflake":
                warnings.append("Snowflake uses VARIANT type for JSON data")
            if target in ["hive", "spark"]:
                warnings.append("JSON stored as STRING - use JSON functions for access")
        
        # Timestamp precision
        if type_name in ["TIMESTAMP", "TIMESTAMP_TZ"]:
            if source == "oracle" and target in ["mysql", "postgres"]:
                warnings.append(
                    "Oracle TIMESTAMP has 9 fractional digits, "
                    f"{target} has 6 - potential precision loss"
                )
        
        # Boolean
        if type_name == "BOOLEAN":
            if target in ["mysql", "oracle"]:
                warnings.append(
                    f"BOOLEAN stored as numeric in {target} - "
                    "use 0/1 for false/true"
                )
        
        return warnings
    
    def get_matrix(
        self,
        source: str = None,
        target: str = None
    ) -> Dict[str, Any]:
        """Get full or filtered type mapping matrix.
        
        Args:
            source: Filter by source dialect
            target: Filter by target dialect
            
        Returns:
            Type mapping matrix
        """
        if source is None and target is None:
            return self.mappings
        
        result = {}
        for type_name, type_map in self.mappings.items():
            entry = {"type": type_name}
            if source:
                entry["source"] = type_map.get(source.lower(), "N/A")
            if target:
                entry["target"] = type_map.get(target.lower(), "N/A")
            if "notes" in type_map:
                entry["notes"] = type_map["notes"]
            entry["category"] = self.get_type_category(type_name)
            result[type_name] = entry
        
        return result
    
    def get_all_types(self) -> List[str]:
        """Get list of all supported type names.
        
        Returns:
            List of type names
        """
        return list(self.mappings.keys())
    
    def get_dialect_types(self, dialect: str) -> Dict[str, str]:
        """Get all type mappings for a specific dialect.
        
        Args:
            dialect: Dialect name
        
        Returns:
            Dictionary of type_name -> dialect_syntax
        """
        dialect = dialect.lower()
        result = {}
        for type_name, type_map in self.mappings.items():
            if dialect in type_map:
                result[type_name] = type_map[dialect]
        return result
    
    def compare_types(self, type_name: str) -> Dict[str, Any]:
        """Compare a type across all dialects.
        
        Args:
            type_name: Type name to compare
        
        Returns:
            Comparison dictionary
        """
        type_info = self.mappings.get(type_name.upper())
        if not type_info:
            return {"error": f"Type {type_name} not found"}
        
        comparison = {
            "type": type_name,
            "category": self.get_type_category(type_name),
            "dialects": {},
            "notes": type_info.get("notes", "")
        }
        
        for dialect in self.DIALECTS:
            comparison["dialects"][dialect] = type_info.get(dialect, "N/A")
        
        # Add availability summary
        available = [d for d in self.DIALECTS if comparison["dialects"].get(d, "N/A") != "N/A"]
        comparison["availability"] = {
            "supported": available,
            "coverage": f"{len(available)}/{len(self.DIALECTS)}"
        }
        
        return comparison
    
    def get_precision_warnings(self) -> Dict[str, str]:
        """Get all precision and compatibility warnings.
        
        Returns:
            Dictionary of type_name -> warning_message
        """
        return self.precision_warnings
    
    def suggest_type(
        self,
        source_type: str,
        source: str,
        target: str
    ) -> Dict[str, Any]:
        """Suggest best target type with notes and recommendations.
        
        Args:
            source_type: Source data type
            source: Source dialect
            target: Target dialect
        
        Returns:
            Dictionary with suggestion and recommendations
        """
        result = self.map_type(source_type, source, target)
        
        # Add suggestions based on common patterns
        suggestions = []
        source_upper = source_type.upper()
        target_lower = target.lower()
        
        if "VARCHAR" in source_upper and target_lower == "oracle":
            suggestions.append(
                "Consider VARCHAR2 with MAX_STRING_SIZE=EXTENDED for >4000 chars"
            )
        
        if "DECIMAL" in source_upper:
            suggestions.append(
                "Verify precision (p) and scale (s) are within target limits"
            )
        
        if "TIMESTAMP" in source_upper:
            suggestions.append(
                "Check timezone handling: WITH TIME ZONE vs WITHOUT"
            )
        
        if "ARRAY" in source_upper and target_lower in ["mysql", "oracle", "tsql"]:
            suggestions.append("Consider JSON serialization for array data")
        
        if "JSON" in source_upper and target_lower == "snowflake":
            suggestions.append("Snowflake uses VARIANT type for JSON data")
        
        if "UUID" in source_upper and target_lower not in ["postgres", "tsql", "clickhouse", "duckdb"]:
            suggestions.append(
                "UUID stored as CHAR(36) or RAW(16) - consider indexing implications"
            )
        
        if "TEXT" in source_upper and target_lower == "oracle":
            suggestions.append("Oracle uses CLOB for unlimited text - consider VARCHAR2 for smaller data")
        
        if "SERIAL" in source_upper:
            suggestions.append("Auto-increment syntax varies significantly - verify DDL")
        
        result["suggestions"] = suggestions
        return result
    
    def get_type_category(self, type_name: str) -> Optional[str]:
        """Get the category for a type.
        
        Args:
            type_name: Type name
        
        Returns:
            Category name or None
        """
        type_upper = type_name.upper()
        for category, types in self.TYPE_CATEGORIES.items():
            if type_upper in types:
                return category
        return None
    
    def get_types_by_category(self, category: str) -> List[str]:
        """Get all types in a category.
        
        Args:
            category: Category name
        
        Returns:
            List of types in a category
        """
        return self.TYPE_CATEGORIES.get(category, [])
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive type mapping statistics.
        
        Returns:
            Dictionary with statistics
        """
        # Count types by dialect availability
        dialect_coverage = {d: 0 for d in self.DIALECTS}
        for type_map in self.mappings.values():
            for dialect in self.DIALECTS:
                if type_map.get(dialect) and type_map.get(dialect) != "N/A":
                    dialect_coverage[dialect] += 1
        
        return {
            "total_types": len(self.mappings),
            "total_dialects": len(self.DIALECTS),
            "categories": len(self.TYPE_CATEGORIES),
            "by_category": {cat: len(types) for cat, types in self.TYPE_CATEGORIES.items()},
            "precision_warnings": len(self.precision_warnings),
            "dialect_coverage": dialect_coverage
        }
    
    def find_compatible_types(
        self,
        type_name: str,
        target: str
    ) -> List[Dict[str, Any]]:
        """Find compatible alternative types in target dialect.
        
        Args:
            type_name: Source type name
            target: Target dialect
        
        Returns:
            List of alternative types
        """
        type_upper = type_name.upper()
        target_lower = target.lower()
        
        # Get the category of the source type
        category = self.get_type_category(type_upper)
        if not category:
            return []
        
        # Find all types in the same category
        alternatives = []
        for alt_type in self.TYPE_CATEGORIES.get(category, []):
            if alt_type != type_upper and alt_type in self.mappings:
                target_syntax = self.mappings[alt_type].get(target_lower)
                if target_syntax and target_syntax != "N/A":
                    alternatives.append({
                        "type": alt_type,
                        "syntax": target_syntax,
                        "notes": self.mappings[alt_type].get("notes", ""),
                        "category": category
                    })
        
        return alternatives
    
    def get_conversion_path(
        self,
        source_type: str,
        source: str,
        target: str
    ) -> Dict[str, Any]:
        """Get detailed conversion path with all considerations.
        
        Args:
            source_type: Source type name
            source: Source dialect
            target: Target dialect
        
        Returns:
            Detailed conversion information
        """
        mapping = self.map_type(source_type, source, target)
        suggestion = self.suggest_type(source_type, source, target)
        alternatives = self.find_compatible_types(source_type, target)
        
        return {
            "mapping": mapping,
            "suggestions": suggestion.get("suggestions", []),
            "alternatives": alternatives,
            "precision_warning": self.precision_warnings.get(source_type.upper()),
            "category": self.get_type_category(source_type)
        }
    
    def find_source_type(
        self,
        target_syntax: str,
        target_dialect: str
    ) -> List[Dict[str, Any]]:
        """Reverse lookup: find source types that map to a target syntax.
        
        Args:
            target_syntax: Target type syntax to search for
            target_dialect: Target dialect
        
        Returns:
            List of matching source types with details
        """
        target_dialect = target_dialect.lower()
        target_syntax_upper = target_syntax.upper()
        matches = []
        
        for type_name, mapping in self.mappings.items():
            dialect_syntax = mapping.get(target_dialect, "")
            if dialect_syntax and target_syntax_upper in dialect_syntax.upper():
                matches.append({
                    "type_name": type_name,
                    "target_syntax": dialect_syntax,
                    "category": self.get_type_category(type_name),
                    "notes": mapping.get("notes", ""),
                    "exact_match": dialect_syntax.upper() == target_syntax_upper
                })
        
        # Sort by exact match first
        matches.sort(key=lambda x: (not x["exact_match"], x["type_name"]))
        return matches
    
    def get_type_compatibility_matrix(
        self,
        type_name: str
    ) -> Dict[str, Dict[str, bool]]:
        """Get compatibility matrix showing which dialects support a type natively.
        
        Args:
            type_name: Type name to check
        
        Returns:
            Matrix of dialect -> dialect compatibility
        """
        type_info = self.mappings.get(type_name.upper())
        if not type_info:
            return {"error": f"Type {type_name} not found"}
        
        matrix = {}
        for source in self.DIALECTS:
            matrix[source] = {}
            source_syntax = type_info.get(source, "N/A")
            
            for target in self.DIALECTS:
                target_syntax = type_info.get(target, "N/A")
                
                # Check if conversion is lossless
                if source_syntax == "N/A" or target_syntax == "N/A":
                    matrix[source][target] = None  # Not applicable
                elif source_syntax == target_syntax:
                    matrix[source][target] = True  # Identical
                else:
                    # Check for potential data loss
                    matrix[source][target] = self._is_compatible_conversion(
                        type_name, source_syntax, target_syntax
                    )
        
        return matrix
    
    def _is_compatible_conversion(
        self,
        type_name: str,
        source_syntax: str,
        target_syntax: str
    ) -> bool:
        """Check if type conversion is compatible (no data loss).
        
        Args:
            type_name: Type name
            source_syntax: Source dialect syntax
            target_syntax: Target dialect syntax
        
        Returns:
            True if conversion is safe
        """
        # Simple heuristic: check for common compatibility patterns
        type_upper = type_name.upper()
        
        # String types are generally compatible
        if type_upper in ["STRING", "VARCHAR", "TEXT"]:
            return True
        
        # Numeric types need precision check
        if type_upper in ["DECIMAL", "NUMERIC"]:
            return False  # Precision may vary
        
        # Timestamp precision varies
        if "TIMESTAMP" in type_upper:
            return False  # Precision may vary
        
        return True