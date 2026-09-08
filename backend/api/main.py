#!/usr/bin/env python3
"""FastAPI Backend for SQL Dialect Master."""
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

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import settings, setup_logging, get_dialect_api_info
from core.transpiler import SQLTranspiler
from core.parser import SQLParser, SUPPORTED_DIALECTS
from core.functions_lookup import FunctionEncyclopedia
from core.type_mapping import TypeMapper
from core.nl2sql import NL2SQLGenerator

logger = setup_logging(level=logging.INFO)
api_logger = logging.getLogger(__name__)

API_VERSION = settings.api_version
API_TITLE = settings.api_title
API_DESCRIPTION = """
# 🔄 SQL Dialect Master API

Enterprise-grade multi-database SQL conversion engine.

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔄 **SQL Conversion** | Convert SQL between 12 database dialects |
| 📚 **Function Encyclopedia** | Cross-database SQL function reference |
| 🗂️ **Type Mapping** | Cross-database data type mapping matrix |
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

- `POST /api/convert` - Convert SQL between database dialects
- `GET /api/functions` - Search SQL functions
- `GET /api/types` - Get type mapping matrix
- `POST /api/nl2sql` - Generate SQL from natural language
"""

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
        {"name": "conversion", "description": "🔄 SQL dialect conversion operations", "externalDocs": {"description": "Learn more", "url": "https://sqlglot.com/"}},
        {"name": "functions", "description": "📚 SQL function encyclopedia"},
        {"name": "types", "description": "🗂️ Data type mapping matrix"},
        {"name": "nl2sql", "description": "💬 Natural language to SQL generation"},
        {"name": "system", "description": "⚙️ System and health endpoints"}
    ]
)

from backend.api.middleware import (
    RateLimiter,
    RateLimitMiddleware,
    StructuredLoggingMiddleware,
    SecurityHeadersMiddleware
)
from backend.core.exceptions import SDMException, UnsupportedDialectError

ALLOWED_ORIGINS = [origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)
app.add_middleware(SecurityHeadersMiddleware)
rate_limiter = RateLimiter(
    requests_per_window=settings.rate_limit_requests,
    window_seconds=settings.rate_limit_window,
)
app.add_middleware(RateLimitMiddleware, limiter=rate_limiter, enabled=settings.rate_limit_enabled)

transpiler = SQLTranspiler()
func_encyclopedia = FunctionEncyclopedia()
type_mapper = TypeMapper()
nl2sql_generator = NL2SQLGenerator()


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.4f}s"
    response.headers["X-API-Version"] = API_VERSION
    api_logger.info(f"{request.method} {request.url.path} - {response.status_code} - {process_time:.4f}s")
    return response


DIALECT_INFO = get_dialect_api_info()


def normalize_dialect(dialect: str, field_name: str = "dialect") -> str:
    """Normalize and validate a dialect at the API boundary."""
    normalized = dialect.strip().lower()
    if normalized not in SUPPORTED_DIALECTS:
        raise HTTPException(status_code=400, detail=f"Unsupported {field_name}: {dialect}. Supported: {SUPPORTED_DIALECTS}")
    return normalized


class ConvertRequest(BaseModel):
    sql: str = Field(..., description="Source SQL statement to convert")
    source_dialect: str = Field(..., description="Source database dialect")
    target_dialect: str = Field(..., description="Target database dialect")
    pretty: bool = Field(True, description="Format output SQL with indentation")
    model_config = ConfigDict(json_schema_extra={"example": {"sql": "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') FROM orders", "source_dialect": "mysql", "target_dialect": "postgres", "pretty": True}})


class ConvertResponse(BaseModel):
    success: bool = Field(..., description="Whether conversion was successful")
    source_sql: str = Field(..., description="Original SQL statement")
    target_sql: Optional[str] = Field(None, description="Converted SQL statement")
    source_dialect: str = Field(..., description="Source dialect")
    target_dialect: str = Field(..., description="Target dialect")
    error: Optional[str] = Field(None, description="Error message if conversion failed")
    error_code: Optional[str] = Field(None, description="Stable machine-readable error category")
    compatibility_notes: List[str] = Field(default_factory=list, description="Compatibility notes")
    transformations: List[str] = Field(default_factory=list, description="Applied transformations")
    warnings: List[str] = Field(default_factory=list, description="Conversion warnings")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat(), description="Response timestamp")


class NL2SQLRequest(BaseModel):
    text: str = Field(..., description="Natural language query (Chinese or English)")
    dialect: str = Field("hive", description="Target SQL dialect")
    table_hint: Optional[str] = Field(None, description="Optional table name hint")
    model_config = ConfigDict(json_schema_extra={"example": {"text": "统计每个部门的员工数量", "dialect": "mysql", "table_hint": "employees"}})


class NL2SQLResponse(BaseModel):
    success: bool = Field(..., description="Whether generation was successful")
    input_text: str = Field(..., description="Original natural language input")
    sql: Optional[str] = Field(None, description="Generated SQL statement")
    dialect: str = Field(..., description="Target dialect")
    explanation: str = Field("", description="Explanation of generated SQL")
    confidence: float = Field(0.0, description="Confidence score (0.0-1.0)")
    suggestions: List[str] = Field(default_factory=list, description="Improvement suggestions")


class ParseRequest(BaseModel):
    sql: str = Field(..., description="SQL statement to parse")
    dialect: str = Field("hive", description="SQL dialect")


class TypeMapRequest(BaseModel):
    type_name: str = Field(..., description="Source data type name")
    source_dialect: str = Field(..., description="Source database dialect")
    target_dialect: str = Field(..., description="Target database dialect")
    model_config = ConfigDict(json_schema_extra={"example": {"type_name": "VARCHAR", "source_dialect": "mysql", "target_dialect": "postgres"}})


class APIResponse(BaseModel):
    success: bool = Field(..., description="Operation success status")
    data: Optional[Dict[str, Any]] = Field(None, description="Response data")
    error: Optional[str] = Field(None, description="Error message if failed")
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


@app.get("/", tags=["system"])
async def root():
    return {
        "name": API_TITLE,
        "version": API_VERSION,
        "status": "✅ Online",
        "description": "Enterprise-grade multi-database SQL conversion engine",
        "stats": {
            "functions": {"count": len(func_encyclopedia.functions), "label": "📚 SQL Functions"},
            "types": {"count": len(type_mapper.mappings), "label": "🗂️ Data Types"},
            "dialects": {"count": len(SUPPORTED_DIALECTS), "label": "💾 Databases"},
            "rules": {"count": len(transpiler.post_processor.engine.rules), "label": "🔧 Conversion Rules"}
        },
        "endpoints": {
            "🔄 conversion": {"url": "/api/convert", "method": "POST"},
            "📝 parsing": {"url": "/api/parse", "method": "POST"},
            "💾 dialects": {"url": "/api/dialects", "method": "GET"},
            "📚 functions": {"url": "/api/functions", "method": "GET"},
            "🗂️ types": {"url": "/api/types", "method": "GET"},
            "💬 nl2sql": {"url": "/api/nl2sql", "method": "POST"},
            "❤️ health": {"url": "/health", "method": "GET"},
            "🟢 readiness": {"url": "/ready", "method": "GET"},
            "📖 docs": {"url": "/docs", "method": "GET"}
        },
        "quick_start": {"example": {"endpoint": "POST /api/convert", "body": {"sql": "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') FROM orders", "source_dialect": "mysql", "target_dialect": "postgres"}}},
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/dialects", tags=["system"])
async def get_dialects():
    by_category = {}
    for dialect, info in DIALECT_INFO.items():
        cat = info["category"]
        by_category.setdefault(cat, []).append({"id": dialect, "name": info["name"], "icon": info["icon"]})
    return {"success": True, "dialects": SUPPORTED_DIALECTS, "count": len(SUPPORTED_DIALECTS), "details": DIALECT_INFO, "by_category": by_category, "categories": list(by_category.keys())}


@app.post("/api/convert", response_model=ConvertResponse, tags=["conversion"])
async def convert_sql(request: ConvertRequest):
    source_dialect = request.source_dialect.strip().lower()
    target_dialect = request.target_dialect.strip().lower()
    if source_dialect not in SUPPORTED_DIALECTS:
        raise HTTPException(status_code=400, detail=f"Unsupported source dialect: {request.source_dialect}. Supported: {SUPPORTED_DIALECTS}")
    if target_dialect not in SUPPORTED_DIALECTS:
        raise HTTPException(status_code=400, detail=f"Unsupported target dialect: {request.target_dialect}. Supported: {SUPPORTED_DIALECTS}")
    result = transpiler.transpile(request.sql, source_dialect, target_dialect, request.pretty)
    return ConvertResponse(success=result.success, source_sql=result.source_sql, target_sql=result.target_sql, source_dialect=result.source_dialect, target_dialect=result.target_dialect, error=result.error, error_code=result.error_code, compatibility_notes=result.compatibility_notes, transformations=result.transformations, warnings=result.warnings)


@app.post("/api/parse", tags=["conversion"])
async def parse_sql(request: ParseRequest):
    dialect = normalize_dialect(request.dialect)
    parser = SQLParser(dialect)
    elements = parser.extract_elements(request.sql)
    return {"success": True, "dialect": dialect, "elements": elements, "timestamp": datetime.now().isoformat()}


@app.get("/api/functions", tags=["functions"])
async def list_functions(search: Optional[str] = Query(None, description="Search term for function name"), category: Optional[str] = Query(None, description="Filter by category (string, date, math, etc.)"), limit: int = Query(50, ge=1, le=500, description="Maximum number of results")):
    if search:
        functions = func_encyclopedia.search(search, limit)
    elif category:
        functions = func_encyclopedia.list_by_category(category)
    else:
        functions = func_encyclopedia.functions[:limit]
    return {"success": True, "functions": functions, "count": len(functions), "total": len(func_encyclopedia.functions), "stats": func_encyclopedia.get_stats()}


@app.get("/api/functions/categories", tags=["functions"])
async def get_function_categories():
    categories = func_encyclopedia.get_all_categories()
    return {"success": True, "categories": categories, "count": len(categories)}


@app.get("/api/functions/{name}", tags=["functions"])
async def get_function(name: str):
    func = func_encyclopedia.get_function(name)
    if not func:
        raise HTTPException(status_code=404, detail=f"Function '{name}' not found. Try searching with /api/functions?search={name}")
    return {"success": True, "function": func, "comparison": func_encyclopedia.compare_dialects(name)}


@app.get("/api/types", tags=["types"])
async def list_types(source: Optional[str] = Query(None, description="Filter by source dialect"), target: Optional[str] = Query(None, description="Filter by target dialect")):
    if source is not None:
        source = normalize_dialect(source, "source dialect")
    if target is not None:
        target = normalize_dialect(target, "target dialect")
    matrix = type_mapper.get_matrix(source, target)
    return {"success": True, "mappings": matrix, "dialects": type_mapper.DIALECTS, "type_count": len(matrix), "precision_warnings": type_mapper.get_precision_warnings()}


@app.get("/api/types/{type_name}", tags=["types"])
async def get_type(type_name: str):
    comparison = type_mapper.compare_types(type_name)
    if "error" in comparison:
        raise HTTPException(status_code=404, detail=f"Type '{type_name}' not found. Available types: STRING, VARCHAR, INT, BIGINT, DECIMAL, DATE, TIMESTAMP, ARRAY, MAP, JSON, etc.")
    return {"success": True, **comparison}


@app.post("/api/types/map", tags=["types"])
async def map_type(request: TypeMapRequest):
    source_dialect = normalize_dialect(request.source_dialect, "source dialect")
    target_dialect = normalize_dialect(request.target_dialect, "target dialect")
    result = type_mapper.suggest_type(request.type_name, source_dialect, target_dialect)
    return {"success": True, **result, "timestamp": datetime.now().isoformat()}


@app.post("/api/nl2sql", response_model=NL2SQLResponse, tags=["nl2sql"])
async def generate_sql(request: NL2SQLRequest):
    dialect = normalize_dialect(request.dialect)
    result = nl2sql_generator.generate(request.text, dialect, request.table_hint)
    return NL2SQLResponse(success=result.success, input_text=result.input_text, sql=result.sql, dialect=dialect, explanation=result.explanation, confidence=result.confidence, suggestions=result.suggestions)


def _run_readiness_checks() -> Dict[str, Dict[str, Any]]:
    """Run lightweight in-process checks used by readiness probes."""
    checks: Dict[str, Dict[str, Any]] = {}
    try:
        result = transpiler.transpile("SELECT 1 AS test", "mysql", "postgres")
        checks["transpiler"] = {"status": "ok" if result.success else "error", "test_result": result.success}
    except Exception as exc:
        checks["transpiler"] = {"status": "error", "message": str(exc)}
    try:
        func = func_encyclopedia.get_function("CONCAT")
        checks["functions"] = {"status": "ok" if func else "warning", "sample_lookup": "CONCAT" if func else None}
    except Exception as exc:
        checks["functions"] = {"status": "error", "message": str(exc)}
    try:
        type_result = type_mapper.map_type("VARCHAR", "mysql", "postgres")
        checks["types"] = {"status": "ok" if type_result.get("success") else "warning", "sample_mapping": type_result.get("target_type")}
    except Exception as exc:
        checks["types"] = {"status": "error", "message": str(exc)}
    try:
        nl_result = nl2sql_generator.generate("查询所有用户", "mysql")
        checks["nl2sql"] = {"status": "ok" if nl_result.success else "warning", "confidence": nl_result.confidence}
    except Exception as exc:
        checks["nl2sql"] = {"status": "error", "message": str(exc)}
    return checks


@app.get("/health", tags=["system"])
async def health_check():
    """Liveness probe: confirms the application process is serving HTTP."""
    return {
        "status": "✅ healthy",
        "version": API_VERSION,
        "probe": "liveness",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/ready", tags=["system"])
async def readiness_check():
    """Readiness probe: validates core services before accepting traffic."""
    checks = _run_readiness_checks()
    has_errors = any(check.get("status") == "error" for check in checks.values())
    all_ok = all(check.get("status") == "ok" for check in checks.values())
    status = "✅ ready" if all_ok else ("❌ not ready" if has_errors else "⚠️ degraded")
    payload = {
        "status": status,
        "version": API_VERSION,
        "probe": "readiness",
        "checks": checks,
        "timestamp": datetime.now().isoformat(),
    }
    return JSONResponse(status_code=200 if all_ok else 503, content=payload)


@app.get("/health/deep", tags=["system"])
async def deep_health_check():
    """Deep health diagnostics; unlike /health, this executes component checks."""
    checks = _run_readiness_checks()
    has_errors = any(check.get("status") == "error" for check in checks.values())
    all_ok = all(check.get("status") == "ok" for check in checks.values())
    return {"status": "✅ healthy" if all_ok else ("❌ unhealthy" if has_errors else "⚠️ degraded"), "version": API_VERSION, "checks": checks, "timestamp": datetime.now().isoformat()}


@app.get("/api/stats", tags=["system"])
async def get_stats():
    func_categories = func_encyclopedia.get_all_categories()
    rule_count = len(transpiler.post_processor.engine.rules)
    return {
        "success": True,
        "stats": {
            "overview": {"total_functions": len(func_encyclopedia.functions), "total_types": len(type_mapper.mappings), "total_dialects": len(SUPPORTED_DIALECTS), "conversion_rules": rule_count},
            "functions": {"total": len(func_encyclopedia.functions), "categories": func_categories, "category_count": len(func_categories)},
            "types": {"total": len(type_mapper.mappings), "dialects": len(type_mapper.DIALECTS), "categories": ["String", "Numeric", "Date/Time", "Complex", "Binary", "Special"]},
            "dialects": {"list": SUPPORTED_DIALECTS, "details": DIALECT_INFO}
        },
        "timestamp": datetime.now().isoformat()
    }


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"success": False, "error": {"code": exc.status_code, "message": exc.detail, "type": "HTTPException"}, "timestamp": datetime.now().isoformat()})


@app.exception_handler(SDMException)
async def sdm_exception_handler(request: Request, exc: SDMException):
    status_code = 400
    if isinstance(exc, UnsupportedDialectError):
        status_code = 400
    return JSONResponse(status_code=status_code, content={"success": False, "error": exc.to_dict(), "timestamp": datetime.now().isoformat()})


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
