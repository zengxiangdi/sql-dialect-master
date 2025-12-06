#!/usr/bin/env python3
"""FastAPI Backend for SQL Dialect Master.

Enterprise-grade multi-database SQL conversion API with:
- 12 database dialects support
- 298 SQL functions encyclopedia
- 36 data type mappings
- 40 conversion rules
- Natural language to SQL generation
"""
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import setup_logging, get_dialect_api_info
from core.transpiler import SQLTranspiler
from core.parser import SQLParser, SUPPORTED_DIALECTS
from core.functions_lookup import FunctionEncyclopedia
from core.type_mapping import TypeMapper
from core.nl2sql import NL2SQLGenerator

# Configure logging for the application
logger = setup_logging(level=logging.INFO)
api_logger = logging.getLogger(__name__)

# API metadata
API_VERSION = "1.0.0"
API_TITLE = "SQL Dialect Master API"
API_DESCRIPTION = """
# 🔄 SQL Dialect Master API

Enterprise-grade multi-database SQL conversion engine.

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔄 **SQL Conversion** | Convert SQL between 12 database dialects |
| 📚 **Function Encyclopedia** | 298 SQL functions with cross-database comparison |
| 🗂️ **Type Mapping** | 36 data types × 12 databases matrix |
| 💬 **NL2SQL** | Natural language to SQL (Chinese/English) |

## 💾 Supported Databases

| Category | Databases |
|----------|-----------|
| **RDBMS** | MySQL 🐬, PostgreSQL 🐘, Oracle 🔴, SQL Server 🟦 |
| **Big Data** | Hive 🐝, Spark ⚡, Trino 🔷, Databricks 🧱 |
| **Cloud DW** | Snowflake ❄️, Redshift 🔶 |
| **OLAP** | ClickHouse 🏠, DuckDB 🦆 |

## 🚀 Quick Start

```python
import requests

# Convert SQL
response = requests.post("http://localhost:8000/api/convert", json={
    "sql": "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') FROM orders",
    "source_dialect": "mysql",
    "target_dialect": "postgres"
})
print(response.json()["target_sql"])
```

## 📖 API Endpoints

- `POST /api/convert` - Convert SQL between dialects
- `GET /api/functions` - Search SQL functions
- `GET /api/types` - Get type mapping matrix
- `POST /api/nl2sql` - Generate SQL from natural language
"""

# Initialize FastAPI app with enhanced metadata
app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    license_info={
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT"
    },
    openapi_tags=[
        {
            "name": "conversion", 
            "description": "🔄 SQL dialect conversion operations",
            "externalDocs": {"description": "Learn more", "url": "https://sqlglot.com/"}
        },
        {
            "name": "functions", 
            "description": "📚 SQL function encyclopedia with 298 functions"
        },
        {
            "name": "types", 
            "description": "🗂️ Data type mapping matrix (36 types × 12 databases)"
        },
        {
            "name": "nl2sql", 
            "description": "💬 Natural language to SQL generation"
        },
        {
            "name": "system", 
            "description": "⚙️ System and health endpoints"
        }
    ]
)

# Import middleware
from backend.api.middleware import (
    RateLimiter,
    RateLimitMiddleware,
    StructuredLoggingMiddleware,
    SecurityHeadersMiddleware
)
from backend.core.exceptions import SDMException, UnsupportedDialectError

# Configure CORS with environment-based origins for security
# In production, set SDM_ALLOWED_ORIGINS to restrict access
import os
ALLOWED_ORIGINS = os.getenv(
    "SDM_ALLOWED_ORIGINS", 
    "http://localhost:8501,http://localhost:8000,http://127.0.0.1:8501,http://127.0.0.1:8000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],  # Restrict to needed methods
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)

# Add security headers
app.add_middleware(SecurityHeadersMiddleware)

# Add rate limiting (configurable via settings)
rate_limiter = RateLimiter(
    requests_per_window=100,  # settings.rate_limit_requests
    window_seconds=60  # settings.rate_limit_window
)
app.add_middleware(RateLimitMiddleware, limiter=rate_limiter, enabled=True)

# Initialize services
transpiler = SQLTranspiler()
func_encyclopedia = FunctionEncyclopedia()
type_mapper = TypeMapper()
nl2sql_generator = NL2SQLGenerator()

# Request timing middleware with logging
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.4f}s"
    response.headers["X-API-Version"] = API_VERSION
    
    # Log request details
    api_logger.info(
        f"{request.method} {request.url.path} - {response.status_code} - {process_time:.4f}s"
    )
    return response

# Dialect info for enhanced responses (from centralized config)
DIALECT_INFO = get_dialect_api_info()

# === Request/Response Models with Enhanced Documentation ===

class ConvertRequest(BaseModel):
    """SQL conversion request model."""
    sql: str = Field(..., description="Source SQL statement to convert")
    source_dialect: str = Field(..., description="Source database dialect")
    target_dialect: str = Field(..., description="Target database dialect")
    pretty: bool = Field(True, description="Format output SQL with indentation")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "sql": "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') FROM orders",
            "source_dialect": "mysql",
            "target_dialect": "postgres",
            "pretty": True
        }
    })

class ConvertResponse(BaseModel):
    """SQL conversion response model."""
    success: bool = Field(..., description="Whether conversion was successful")
    source_sql: str = Field(..., description="Original SQL statement")
    target_sql: Optional[str] = Field(None, description="Converted SQL statement")
    source_dialect: str = Field(..., description="Source dialect")
    target_dialect: str = Field(..., description="Target dialect")
    error: Optional[str] = Field(None, description="Error message if conversion failed")
    compatibility_notes: List[str] = Field(default_factory=list, description="Compatibility notes")
    transformations: List[str] = Field(default_factory=list, description="Applied transformations")
    warnings: List[str] = Field(default_factory=list, description="Conversion warnings")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat(), description="Response timestamp")

class NL2SQLRequest(BaseModel):
    """Natural language to SQL request model."""
    text: str = Field(..., description="Natural language query (Chinese or English)")
    dialect: str = Field("hive", description="Target SQL dialect")
    table_hint: Optional[str] = Field(None, description="Optional table name hint")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "text": "统计每个部门的员工数量",
            "dialect": "mysql",
            "table_hint": "employees"
        }
    })

class NL2SQLResponse(BaseModel):
    """Natural language to SQL response model."""
    success: bool = Field(..., description="Whether generation was successful")
    input_text: str = Field(..., description="Original natural language input")
    sql: Optional[str] = Field(None, description="Generated SQL statement")
    dialect: str = Field(..., description="Target dialect")
    explanation: str = Field("", description="Explanation of generated SQL")
    confidence: float = Field(0.0, description="Confidence score (0.0-1.0)")
    suggestions: List[str] = Field(default_factory=list, description="Improvement suggestions")

class ParseRequest(BaseModel):
    """SQL parse request model."""
    sql: str = Field(..., description="SQL statement to parse")
    dialect: str = Field("hive", description="SQL dialect")

class TypeMapRequest(BaseModel):
    """Type mapping request model."""
    type_name: str = Field(..., description="Source data type name")
    source_dialect: str = Field(..., description="Source database dialect")
    target_dialect: str = Field(..., description="Target database dialect")

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "type_name": "VARCHAR",
            "source_dialect": "mysql",
            "target_dialect": "postgres"
        }
    })

class APIResponse(BaseModel):
    """Standard API response wrapper."""
    success: bool = Field(..., description="Operation success status")
    data: Optional[Dict[str, Any]] = Field(None, description="Response data")
    error: Optional[str] = Field(None, description="Error message if failed")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

# === API Endpoints ===

@app.get("/", tags=["system"])
async def root():
    """
    🏠 API Root - Welcome & Service Information
    
    Returns comprehensive API information including:
    - Service statistics
    - Available endpoints
    - Quick start guide
    """
    return {
        "name": API_TITLE,
        "version": API_VERSION,
        "status": "✅ Online",
        "description": "Enterprise-grade multi-database SQL conversion engine",
        "stats": {
            "functions": {"count": len(func_encyclopedia.functions), "label": "📚 SQL Functions"},
            "types": {"count": len(type_mapper.mappings), "label": "🗂️ Data Types"},
            "dialects": {"count": len(SUPPORTED_DIALECTS), "label": "💾 Databases"},
            "rules": {"count": 40, "label": "🔧 Conversion Rules"}
        },
        "endpoints": {
            "🔄 conversion": {"url": "/api/convert", "method": "POST"},
            "📝 parsing": {"url": "/api/parse", "method": "POST"},
            "💾 dialects": {"url": "/api/dialects", "method": "GET"},
            "📚 functions": {"url": "/api/functions", "method": "GET"},
            "🗂️ types": {"url": "/api/types", "method": "GET"},
            "💬 nl2sql": {"url": "/api/nl2sql", "method": "POST"},
            "❤️ health": {"url": "/health", "method": "GET"},
            "📖 docs": {"url": "/docs", "method": "GET"}
        },
        "quick_start": {
            "example": {
                "endpoint": "POST /api/convert",
                "body": {
                    "sql": "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') FROM orders",
                    "source_dialect": "mysql",
                    "target_dialect": "postgres"
                }
            }
        },
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/dialects", tags=["system"])
async def get_dialects():
    """
    💾 Get Supported SQL Dialects
    
    Returns all 12 supported database dialects with:
    - Display name and icon
    - Category (RDBMS, Big Data, Cloud DW, etc.)
    - Grouped by category for easy navigation
    """
    # Group dialects by category
    by_category = {}
    for dialect, info in DIALECT_INFO.items():
        cat = info["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append({
            "id": dialect,
            "name": info["name"],
            "icon": info["icon"]
        })
    
    return {
        "success": True,
        "dialects": SUPPORTED_DIALECTS,
        "count": len(SUPPORTED_DIALECTS),
        "details": DIALECT_INFO,
        "by_category": by_category,
        "categories": list(by_category.keys())
    }

@app.post("/api/convert", response_model=ConvertResponse, tags=["conversion"])
async def convert_sql(request: ConvertRequest):
    """
    Convert SQL from one dialect to another.
    
    Supports conversion between 12 database dialects with:
    - Automatic syntax transformation
    - Function mapping
    - Type conversion
    - Compatibility notes
    
    **Example:**
    ```json
    {
        "sql": "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') FROM orders",
        "source_dialect": "mysql",
        "target_dialect": "postgres"
    }
    ```
    """
    # Validate dialects
    if request.source_dialect not in SUPPORTED_DIALECTS:
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported source dialect: {request.source_dialect}. Supported: {SUPPORTED_DIALECTS}"
        )
    if request.target_dialect not in SUPPORTED_DIALECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported target dialect: {request.target_dialect}. Supported: {SUPPORTED_DIALECTS}"
        )
    
    result = transpiler.transpile(
        request.sql,
        request.source_dialect,
        request.target_dialect,
        request.pretty
    )
    return ConvertResponse(
        success=result.success,
        source_sql=result.source_sql,
        target_sql=result.target_sql,
        source_dialect=result.source_dialect,
        target_dialect=result.target_dialect,
        error=result.error,
        compatibility_notes=result.compatibility_notes,
        transformations=result.transformations,
        warnings=result.warnings
    )

@app.post("/api/parse", tags=["conversion"])
async def parse_sql(request: ParseRequest):
    """
    Parse SQL and extract elements.
    
    Extracts tables, columns, functions, and other elements from SQL.
    """
    parser = SQLParser(request.dialect)
    elements = parser.extract_elements(request.sql)
    return {
        "success": True,
        "dialect": request.dialect,
        "elements": elements,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/functions", tags=["functions"])
async def list_functions(
    search: Optional[str] = Query(None, description="Search term for function name"),
    category: Optional[str] = Query(None, description="Filter by category (string, date, math, etc.)"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of results")
):
    """
    List or search SQL functions.
    
    **Categories:** string, date, math, aggregate, window, conditional, conversion, json, array, system, geo
    
    **Examples:**
    - `/api/functions?search=date` - Search for date functions
    - `/api/functions?category=string` - List all string functions
    - `/api/functions?limit=100` - Get first 100 functions
    """
    if search:
        functions = func_encyclopedia.search(search, limit)
    elif category:
        functions = func_encyclopedia.list_by_category(category)
    else:
        functions = func_encyclopedia.functions[:limit]
    
    return {
        "success": True,
        "functions": functions,
        "count": len(functions),
        "total": len(func_encyclopedia.functions),
        "stats": func_encyclopedia.get_stats()
    }

@app.get("/api/functions/categories", tags=["functions"])
async def get_function_categories():
    """
    Get all function categories with counts.
    
    Returns list of categories and number of functions in each.
    """
    categories = func_encyclopedia.get_all_categories()
    return {
        "success": True,
        "categories": categories,
        "count": len(categories)
    }

@app.get("/api/functions/{name}", tags=["functions"])
async def get_function(name: str):
    """
    Get detailed function information.
    
    Returns function details with syntax for all 12 database dialects.
    """
    func = func_encyclopedia.get_function(name)
    if not func:
        raise HTTPException(
            status_code=404, 
            detail=f"Function '{name}' not found. Try searching with /api/functions?search={name}"
        )
    
    comparison = func_encyclopedia.compare_dialects(name)
    return {
        "success": True,
        "function": func,
        "comparison": comparison
    }

@app.get("/api/types", tags=["types"])
async def list_types(
    source: Optional[str] = Query(None, description="Filter by source dialect"),
    target: Optional[str] = Query(None, description="Filter by target dialect")
):
    """
    Get type mapping matrix.
    
    Returns complete 36 types × 12 databases mapping matrix.
    
    **Type Categories:**
    - String: STRING, VARCHAR, CHAR, TEXT, etc.
    - Numeric: BIGINT, INT, DECIMAL, FLOAT, etc.
    - Date/Time: DATE, TIME, TIMESTAMP, INTERVAL
    - Complex: ARRAY, MAP, STRUCT, JSON
    - Special: UUID, INET, GEOMETRY
    """
    matrix = type_mapper.get_matrix(source, target)
    return {
        "success": True,
        "mappings": matrix,
        "dialects": type_mapper.DIALECTS,
        "type_count": len(matrix),
        "precision_warnings": type_mapper.get_precision_warnings()
    }

@app.get("/api/types/{type_name}", tags=["types"])
async def get_type(type_name: str):
    """
    Get type mapping details for a specific type.
    
    Returns mapping for all 12 database dialects.
    """
    comparison = type_mapper.compare_types(type_name)
    if "error" in comparison:
        raise HTTPException(
            status_code=404, 
            detail=f"Type '{type_name}' not found. Available types: STRING, VARCHAR, INT, BIGINT, DECIMAL, DATE, TIMESTAMP, ARRAY, MAP, JSON, etc."
        )
    return {
        "success": True,
        **comparison
    }

@app.post("/api/types/map", tags=["types"])
async def map_type(request: TypeMapRequest):
    """
    Map a type from source to target dialect.
    
    Returns the equivalent type in the target database with notes.
    """
    result = type_mapper.suggest_type(
        request.type_name,
        request.source_dialect,
        request.target_dialect
    )
    return {
        "success": True,
        **result,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/nl2sql", response_model=NL2SQLResponse, tags=["nl2sql"])
async def generate_sql(request: NL2SQLRequest):
    """
    Generate SQL from natural language.
    
    Supports both Chinese and English input.
    
    **Examples:**
    - "查询最近7天的订单" → SELECT * FROM orders WHERE created_at >= DATE_SUB(CURRENT_DATE, 7)
    - "统计每个部门的员工数量" → SELECT dept, COUNT(*) FROM employees GROUP BY dept
    - "Get top 10 users by score" → SELECT * FROM users ORDER BY score DESC LIMIT 10
    """
    result = nl2sql_generator.generate(
        request.text,
        request.dialect,
        request.table_hint
    )
    return NL2SQLResponse(
        success=result.success,
        input_text=result.input_text,
        sql=result.sql,
        dialect=result.dialect,
        explanation=result.explanation,
        confidence=result.confidence,
        suggestions=result.suggestions
    )

@app.get("/health", tags=["system"])
async def health_check():
    """
    ❤️ Health Check Endpoint
    
    Returns comprehensive service status including:
    - Overall health status
    - Individual service status
    - Resource statistics
    """
    services = {
        "transpiler": {"status": "✅ healthy", "rules": 40, "description": "SQL conversion engine"},
        "functions": {"status": "✅ healthy", "count": len(func_encyclopedia.functions), "description": "Function encyclopedia"},
        "types": {"status": "✅ healthy", "count": len(type_mapper.mappings), "description": "Type mapping service"},
        "nl2sql": {"status": "✅ healthy", "description": "Natural language processor"}
    }
    
    all_healthy = all("healthy" in s["status"] for s in services.values())
    
    return {
        "status": "✅ healthy" if all_healthy else "⚠️ degraded",
        "version": API_VERSION,
        "uptime": "Available",
        "timestamp": datetime.now().isoformat(),
        "services": services,
        "stats": {
            "dialects": len(SUPPORTED_DIALECTS),
            "functions": len(func_encyclopedia.functions),
            "types": len(type_mapper.mappings),
            "rules": 40
        }
    }


@app.get("/health/deep", tags=["system"])
async def deep_health_check():
    """
    🔍 Deep Health Check Endpoint
    
    Performs actual validation of all components:
    - Tests transpiler with sample SQL
    - Validates function encyclopedia data
    - Checks type mapping integrity
    - Verifies NL2SQL generation
    """
    checks = {}
    
    # Test transpiler
    try:
        result = transpiler.transpile("SELECT 1 AS test", "mysql", "postgres")
        checks["transpiler"] = {
            "status": "✅ ok" if result.success else "❌ error",
            "test_result": result.success,
            "cache_stats": transpiler.get_stats().get("cache", {})
        }
    except Exception as e:
        checks["transpiler"] = {"status": "❌ error", "message": str(e)}
    
    # Test function encyclopedia
    try:
        func = func_encyclopedia.get_function("CONCAT")
        checks["functions"] = {
            "status": "✅ ok" if func else "⚠️ warning",
            "total_count": len(func_encyclopedia.functions),
            "sample_lookup": "CONCAT" if func else None
        }
    except Exception as e:
        checks["functions"] = {"status": "❌ error", "message": str(e)}
    
    # Test type mapper
    try:
        type_result = type_mapper.map_type("VARCHAR", "mysql", "postgres")
        checks["types"] = {
            "status": "✅ ok" if type_result.get("success") else "⚠️ warning",
            "total_count": len(type_mapper.mappings),
            "sample_mapping": type_result.get("target_type")
        }
    except Exception as e:
        checks["types"] = {"status": "❌ error", "message": str(e)}
    
    # Test NL2SQL
    try:
        nl_result = nl2sql_generator.generate("查询所有用户", "mysql")
        checks["nl2sql"] = {
            "status": "✅ ok" if nl_result.success else "⚠️ warning",
            "confidence": nl_result.confidence,
            "generated_sql": nl_result.sql[:50] if nl_result.sql else None
        }
    except Exception as e:
        checks["nl2sql"] = {"status": "❌ error", "message": str(e)}
    
    # Overall status
    all_ok = all("ok" in c.get("status", "") for c in checks.values())
    has_errors = any("error" in c.get("status", "") for c in checks.values())
    
    return {
        "status": "✅ healthy" if all_ok else ("❌ unhealthy" if has_errors else "⚠️ degraded"),
        "version": API_VERSION,
        "checks": checks,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/stats", tags=["system"])
async def get_stats():
    """
    📊 Get API Statistics
    
    Returns comprehensive statistics about:
    - Function encyclopedia
    - Type mappings
    - Conversion rules
    - Supported dialects
    """
    func_categories = func_encyclopedia.get_all_categories()
    
    return {
        "success": True,
        "stats": {
            "overview": {
                "total_functions": len(func_encyclopedia.functions),
                "total_types": len(type_mapper.mappings),
                "total_dialects": len(SUPPORTED_DIALECTS),
                "conversion_rules": 40
            },
            "functions": {
                "total": len(func_encyclopedia.functions),
                "categories": func_categories,
                "category_count": len(func_categories)
            },
            "types": {
                "total": len(type_mapper.mappings),
                "dialects": len(type_mapper.DIALECTS),
                "categories": ["String", "Numeric", "Date/Time", "Complex", "Binary", "Special"]
            },
            "dialects": {
                "list": SUPPORTED_DIALECTS,
                "details": DIALECT_INFO
            }
        },
        "timestamp": datetime.now().isoformat()
    }

# Custom exception handler for better error responses
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": exc.status_code,
                "message": exc.detail,
                "type": "HTTPException"
            },
            "timestamp": datetime.now().isoformat()
        }
    )


@app.exception_handler(SDMException)
async def sdm_exception_handler(request: Request, exc: SDMException):
    """Handle custom SDM exceptions."""
    status_code = 400
    if isinstance(exc, UnsupportedDialectError):
        status_code = 400
    
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": exc.to_dict(),
            "timestamp": datetime.now().isoformat()
        }
    )

# Run with: uvicorn backend.api.main:app --reload
if __name__ == "__main__":
    import uvicorn
    print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║  🔄 SQL Dialect Master API v{API_VERSION}                      ║
    ║  ──────────────────────────────────────────────────────  ║
    ║  📚 Functions: {len(func_encyclopedia.functions):>3}  │  🗂️ Types: {len(type_mapper.mappings):>2}  │  💾 DBs: {len(SUPPORTED_DIALECTS):>2}   ║
    ║  ──────────────────────────────────────────────────────  ║
    ║  📖 Docs: http://localhost:8000/docs                     ║
    ║  ❤️ Health: http://localhost:8000/health                 ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    uvicorn.run(app, host="0.0.0.0", port=8000)
