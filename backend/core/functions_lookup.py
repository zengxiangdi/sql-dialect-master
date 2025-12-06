#!/usr/bin/env python3
"""Function Encyclopedia - Search and compare SQL functions across dialects.

Provides comprehensive SQL function lookup with:
- 50+ SQL functions across 11 categories
- Cross-database syntax comparison for 12 dialects
- Fuzzy search with relevance scoring
- Category-based filtering
- Function examples and parameter documentation
"""
import json
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from difflib import SequenceMatcher

from .config import (
    SUPPORTED_DIALECTS,
    FUNCTION_CATEGORIES,
    CATEGORY_DESCRIPTIONS,
    FunctionInfo,
    settings
)

# Configure module logger
logger = logging.getLogger(__name__)


class FunctionEncyclopedia:
    """SQL Function Encyclopedia with multi-dialect comparison.
    
    Features:
    - 50+ SQL functions
    - 11 categories: string, date, math, aggregate, window, conditional, conversion, json, array, system, geo
    - 12 database dialects support
    - Fuzzy search with relevance scoring
    - Function examples and parameter documentation
    """
    
    CATEGORIES = FUNCTION_CATEGORIES
    CATEGORY_DESCRIPTIONS = CATEGORY_DESCRIPTIONS
    
    def __init__(self, data_path: Optional[Path] = None):
        """Initialize encyclopedia with function data.
        
        Args:
            data_path: Path to functions_db.json. Uses default if None.
        """
        if data_path is None:
            data_path = Path(__file__).parent / "functions_db.json"
        self.data_path = data_path
        self.functions: List[FunctionInfo] = self._load_data()
        self._build_index()
    
    def _load_data(self) -> List[FunctionInfo]:
        """Load function data from JSON file."""
        try:
            with open(self.data_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("functions", [])
        except Exception:
            return []
    
    def _build_index(self) -> None:
        """Build search index for fast lookup."""
        self.name_index: Dict[str, FunctionInfo] = {}
        self.category_index: Dict[str, List[FunctionInfo]] = {cat: [] for cat in self.CATEGORIES}
        
        for func in self.functions:
            name = func.get("name", "").upper()
            self.name_index[name] = func
            
            category = func.get("category", "").lower()
            if category in self.category_index:
                self.category_index[category].append(func)
    
    def search(self, query: str, limit: int = None) -> List[FunctionInfo]:
        """Search functions with fuzzy matching.
        
        Args:
            query: Search query
            limit: Maximum results to return
            
        Returns:
            List of matching functions sorted by relevance
        """
        limit = limit or settings.function_search_limit
        query = query.upper().strip()
        
        if not query:
            return self.functions[:limit]
        
        results: List[tuple] = []
        
        for func in self.functions:
            name = func.get("name", "").upper()
            description = func.get("description", "").upper()
            
            # Exact match - highest score
            if query == name:
                results.append((func, 1.0))
            # Starts with - high score
            elif name.startswith(query):
                results.append((func, 0.9))
            # Contains in name - medium-high score
            elif query in name:
                results.append((func, 0.7))
            # Contains in description - medium score
            elif query in description:
                results.append((func, 0.5))
            # Fuzzy match - variable score
            else:
                ratio = SequenceMatcher(None, query, name).ratio()
                if ratio > settings.function_fuzzy_threshold:
                    results.append((func, ratio))
        
        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)
        return [r[0] for r in results[:limit]]
    
    def get_function(self, name: str) -> Optional[FunctionInfo]:
        """Get detailed function information by exact name.
        
        Args:
            name: Function name (case-insensitive)
            
        Returns:
            Function info or None if not found
        """
        return self.name_index.get(name.upper())
    
    def list_by_category(self, category: str) -> List[FunctionInfo]:
        """List all functions in a category.
        
        Args:
            category: Category name (case-insensitive)
            
        Returns:
            List of functions in the category
        """
        category = category.lower()
        return self.category_index.get(category, [])
    
    def get_dialect_syntax(self, func_name: str, dialect: str) -> Optional[str]:
        """Get function syntax for specific dialect.
        
        Args:
            func_name: Function name
            dialect: Target dialect
            
        Returns:
            Syntax string or None if not found
        """
        func = self.get_function(func_name)
        if func:
            return func.get("dialects", {}).get(dialect.lower())
        return None
    
    def compare_dialects(
        self,
        func_name: str,
        dialects: List[str] = None
    ) -> Dict[str, Any]:
        """Compare function syntax across multiple dialects.
        
        Args:
            func_name: Function name
            dialects: List of dialects to compare. Uses all if None.
            
        Returns:
            Comparison dictionary with syntax for each dialect
        """
        func = self.get_function(func_name)
        if not func:
            return {"error": f"Function {func_name} not found"}
        
        if dialects is None:
            dialects = SUPPORTED_DIALECTS
        
        comparison = {
            "name": func.get("name"),
            "description": func.get("description"),
            "category": func.get("category"),
            "parameters": func.get("parameters", []),
            "examples": func.get("examples", {}),
            "notes": func.get("notes", ""),
            "dialects": {}
        }
        
        for dialect in dialects:
            syntax = func.get("dialects", {}).get(dialect)
            comparison["dialects"][dialect] = syntax if syntax else "N/A"
        
        # Add availability summary
        available = [d for d in dialects if comparison["dialects"].get(d, "N/A") != "N/A"]
        comparison["availability"] = {
            "supported": available,
            "not_supported": [d for d in dialects if d not in available],
            "coverage": f"{len(available)}/{len(dialects)}"
        }
        
        return comparison
    
    def get_all_categories(self) -> List[Dict[str, Any]]:
        """Get list of all categories with function counts and descriptions.
        
        Returns:
            List of category info dictionaries
        """
        return [
            {
                "name": cat,
                "count": len(funcs),
                "description": self.CATEGORY_DESCRIPTIONS.get(cat, ""),
                "icon": self._get_category_icon(cat)
            }
            for cat, funcs in self.category_index.items()
            if funcs
        ]
    
    def _get_category_icon(self, category: str) -> str:
        """Get icon for category."""
        icons = {
            "string": "📝",
            "date": "📅",
            "math": "🔢",
            "aggregate": "📊",
            "window": "🪟",
            "conditional": "❓",
            "conversion": "🔄",
            "json": "📋",
            "array": "📦",
            "system": "⚙️",
            "geo": "🌍"
        }
        return icons.get(category, "📄")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive encyclopedia statistics.
        
        Returns:
            Dictionary with statistics
        """
        # Count functions by dialect availability
        dialect_coverage = {d: 0 for d in SUPPORTED_DIALECTS}
        for func in self.functions:
            for dialect, syntax in func.get("dialects", {}).items():
                if syntax and syntax != "N/A":
                    dialect_coverage[dialect] = dialect_coverage.get(dialect, 0) + 1
        
        return {
            "total_functions": len(self.functions),
            "categories": len([c for c in self.category_index.values() if c]),
            "by_category": {cat: len(funcs) for cat, funcs in self.category_index.items()},
            "dialects_covered": len(SUPPORTED_DIALECTS),
            "dialect_coverage": dialect_coverage,
            "top_categories": sorted(
                [(cat, len(funcs)) for cat, funcs in self.category_index.items()],
                key=lambda x: x[1], reverse=True
            )[:5]
        }
    
    def find_equivalent(
        self,
        func_name: str,
        source_dialect: str,
        target_dialect: str
    ) -> Optional[Dict[str, Any]]:
        """Find equivalent function syntax in target dialect.
        
        Args:
            func_name: Function name
            source_dialect: Source dialect
            target_dialect: Target dialect
            
        Returns:
            Dictionary with source and target syntax, or None
        """
        func = self.get_function(func_name)
        if not func:
            return None
        
        dialects = func.get("dialects", {})
        source_syntax = dialects.get(source_dialect.lower())
        target_syntax = dialects.get(target_dialect.lower())
        
        if not source_syntax or source_syntax == "N/A":
            return None
        
        return {
            "function": func_name,
            "source_dialect": source_dialect,
            "target_dialect": target_dialect,
            "source_syntax": source_syntax,
            "target_syntax": target_syntax if target_syntax and target_syntax != "N/A" else None,
            "supported_in_target": target_syntax is not None and target_syntax != "N/A",
            "notes": func.get("notes", "")
        }
    
    def get_functions_by_dialect(self, dialect: str) -> List[Dict[str, Any]]:
        """Get all functions available in a specific dialect.
        
        Args:
            dialect: Dialect name
            
        Returns:
            List of available functions with syntax
        """
        dialect = dialect.lower()
        available = []
        
        for func in self.functions:
            syntax = func.get("dialects", {}).get(dialect)
            if syntax and syntax != "N/A":
                available.append({
                    "name": func.get("name"),
                    "category": func.get("category"),
                    "syntax": syntax,
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", [])
                })
        
        return available
    
    def search_by_description(self, query: str, limit: int = 10) -> List[FunctionInfo]:
        """Search functions by description text.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of matching functions
        """
        query = query.lower()
        results = []
        
        for func in self.functions:
            desc = func.get("description", "").lower()
            name = func.get("name", "").lower()
            
            if query in desc or query in name:
                score = 1.0 if query in name else 0.7
                results.append((func, score))
        
        results.sort(key=lambda x: x[1], reverse=True)
        return [r[0] for r in results[:limit]]
    
    def get_function_alternatives(
        self,
        func_name: str,
        dialect: str
    ) -> List[Dict[str, Any]]:
        """Get alternative functions for a dialect that doesn't support the original.
        
        Args:
            func_name: Function name
            dialect: Target dialect
            
        Returns:
            List of alternative functions in the same category
        """
        func = self.get_function(func_name)
        if not func:
            return []
        
        category = func.get("category", "")
        dialect = dialect.lower()
        
        # Get all functions in the same category that are supported in the target dialect
        alternatives = []
        for other_func in self.category_index.get(category, []):
            if other_func.get("name") == func_name:
                continue
            
            syntax = other_func.get("dialects", {}).get(dialect)
            if syntax and syntax != "N/A":
                alternatives.append({
                    "name": other_func.get("name"),
                    "syntax": syntax,
                    "description": other_func.get("description", ""),
                    "similarity": SequenceMatcher(
                        None,
                        func.get("description", ""),
                        other_func.get("description", "")
                    ).ratio()
                })
        
        # Sort by similarity
        alternatives.sort(key=lambda x: x["similarity"], reverse=True)
        return alternatives[:5]
