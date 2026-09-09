#!/usr/bin/env python3
"""FastAPI Backend for SQL Dialect Master."""
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from pydantic import BaseModel, Field, ConfigDict

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import settings, setup_logging, get_dialect_api_info
from core.transpiler import SQLTranspiler
from core.parser import SQLParser, SUPPORTED_DIALECTS
from core.functions_lookup import FunctionEncyclopedia
from core.type_mapping import TypeMapper
from core.nl2sql import NL2SQLGenerator
from backend.api.readiness import health_probe_response
from backend.core.exceptions import SDMException, UnsupportedDialectError
from backend.api.middleware import (
    RateLimiter,
    RateLimitMiddleware,
    StructuredLoggingMiddleware,
    SecurityHeadersMiddleware,
)

logger = setup_logging(level=logging.INFO)
api_logger = logging.getLogger(__name__)
API_VERSION = settings.api_version
API_TITLE = settings.api_title
API_DESCRIPTION = """
# 🔄 SQL Dialect Master API

Enterprise-grade multi-database SQL conversion engine.

| Feature | Description |
|---------|-------------|
| 🔄 **SQL Conversion** | Convert SQL between 12 database dialects |
| 📚 **Function Encyclopedia** | 298 SQL functions with cross-database comparison |
| 🗂️ **Type Mapping** | 36 data type mappings × 12 databases |
| 💬 **NL2SQL** | Natural language to SQL |

## 💾 Supported Databases

MySQL, PostgreSQL, Oracle, SQL Server, Hive, Spark, Trino, Databricks, Snowflake, Redshift, ClickHouse, DuckDB.
"""

app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    license_info={"name": "MIT License", "url": "https://opensource.org/licenses/MIT"},
    openapi_tags=[
        {"name": "conversion", "description": "🔄 SQL dialect conversion operations", "externalDocs": {"description": "Learn more", "url": "https://sqlglot.com/"}},
        {"name": "functions", "description": "📚 SQL function encyclopedia"},
        {"name": "types", "description": "🗂️ Data type mapping matrix"},
        {"name": "nl2sql", "description": "💬 Natural language to SQL generation"},
        {"name": "system", "description": "⚙️ System and health endpoints"},
    ],
)

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
app.add_middleware(
    RateLimitMiddleware,
    limiter=rate_limiter,
    enabled=settings.rate_limit_enabled,
)
app.add_middleware(StructuredLoggingMiddleware)

transpiler = SQLTranspiler()
func_encyclopedia = FunctionEncyclopedia()
type_mapper = TypeMapper()
nl2sql_generator = NL2SQLGenerator()
DIALECT_INFO = get_dialect_api_info()


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.4f}s"
    response.headers["X-API-Version"] = API_VERSION
    api_logger.info(f"{request.method} {request.url.path} - {response.status_code} - {process_time:.4f}s")
    return response


def normalize_dialect(dialect: str, field_name: str = "dialect") -> str:
    normalized = dialect.strip().lower()
    if normalized not in SUPPORTED_DIALECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported {field_name}: {dialect}. Supported: {SUPPORTED_DIALECTS}",
        )
    return normalized


class ConvertRequest(BaseModel):
    sql: str = Field(..., description="Source SQL statement to convert")
    source_dialect: str = Field(..., description="Source database dialect")
    target_dialect: str = Field(..., description="Target database dialect")
    pretty: bool = Field(True, description="Format output SQL with indentation")
    model_config = ConfigDict(json_schema_extra={"example": {"sql": "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') FROM orders", "source_dialect": "mysql", "target_dialect": "postgres", "pretty": True}})


class ConvertResponse(BaseModel):
    success: bool
    source_sql: str
    target_sql: Optional[str] = None
    source_dialect: str
    target_dialect: str
    error: Optional[str] = None
    error_code: Optional[str] = None
    compatibility_notes: List[str] = Field(default_factory=list)
    transformations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class NL2SQLRequest(BaseModel):
    text: str = Field(..., description="Natural language query (Chinese or English)")
    dialect: str = Field("hive", description="Target SQL dialect")
    table_hint: Optional[str] = Field(None, description="Optional table name hint")
    column_hints: Optional[List[str]] = Field(None, description="Optional column identifier hints; accepts simple or dotted identifiers")
    model_config = ConfigDict(json_schema_extra={"example": {"text": "统计每个部门的员工数量", "dialect": "mysql", "table_hint": "employees", "column_hints": ["employees.department", "employees.id"]}})


class NL2SQLResponse(BaseModel):
    success: bool
    input_text: str
    sql: Optional[str] = None
    dialect: str
    explanation: str = ""
    confidence: float = 0.0
    suggestions: List[str] = Field(default_factory=list)


class ParseRequest(BaseModel):
    sql: str
    dialect: str = "hive"


class TypeMapRequest(BaseModel):
    type_name: str
    source_dialect: str
    target_dialect: str
    model_config = ConfigDict(json_schema_extra={"example": {"type_name": "VARCHAR", "source_dialect": "mysql", "target_dialect": "postgres"}})


class APIResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
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
            "rules": {"count": 40, "label": "🔧 Conversion Rules"},
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
            "🔍 deep health": {"url": "/health/deep", "method": "GET"},
            "📖 docs": {"url": "/docs", "method": "GET"},
        },
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/dialects", tags=["system"])
async def get_dialects():
    by_category = {}
    for dialect, info in DIALECT_INFO.items():
        by_category.setdefault(info["category"], []).append({"id": dialect, "name": info["name"], "icon": info["icon"]})
    return {"success": True, "dialects": SUPPORTED_DIALECTS, "count": len(SUPPORTED_DIALECTS), "details": DIALECT_INFO, "by_category": by_category, "categories": list(by_category.keys())}


@app.post("/api/convert", response_model=ConvertResponse, tags=["conversion"])
async def convert_sql(request: ConvertRequest):
    source_dialect = normalize_dialect(request.source_dialect, "source dialect")
    target_dialect = normalize_dialect(request.target_dialect, "target dialect")
    result = transpiler.transpile(request.sql, source_dialect, target_dialect, request.pretty)
    return ConvertResponse(
        success=result.success,
        source_sql=result.source_sql,
        target_sql=result.target_sql,
        source_dialect=result.source_dialect,
        target_dialect=result.target_dialect,
        error=result.error,
        error_code=result.error_code,
        compatibility_notes=result.compatibility_notes,
        transformations=result.transformations,
        warnings=result.warnings,
    )


@app.post("/api/parse", tags=["conversion"])
async def parse_sql(request: ParseRequest):
    dialect = normalize_dialect(request.dialect)
    elements = SQLParser(dialect).extract_elements(request.sql)
    return {"success": True, "dialect": dialect, "elements": elements, "timestamp": datetime.now().isoformat()}


@app.get("/api/functions", tags=["functions"])
async def list_functions(
    search: Optional[str] = Query(None, description="Search term for function name"),
    category: Optional[str] = Query(None, description="Filter by category"),
    limit: int = Query(50, ge=1, le=500, description="Maximum number of results"),
):
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
async def list_types(source: Optional[str] = Query(None), target: Optional[str] = Query(None)):
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
    result = nl2sql_generator.generate(request.text, dialect, request.table_hint, request.column_hints)
    return NL2SQLResponse(success=result.success, input_text=result.input_text, sql=result.sql, dialect=dialect, explanation=result.explanation, confidence=result.confidence, suggestions=result.suggestions)


@app.get("/health", tags=["system"])
async def health_check():
    return {"status": "alive", "version": API_VERSION, "timestamp": datetime.now().isoformat()}


@app.get("/ready", tags=["system"])
async def readiness_check(request: Request):
    return await health_probe_response(request)


@app.get("/health/deep", tags=["system"])
async def deep_health_check(request: Request):
    return await health_probe_response(request)


@app.get("/api/stats", tags=["system"])
async def get_stats():
    func_categories = func_encyclopedia.get_all_categories()
    return {
        "success": True,
        "stats": {
            "overview": {"total_functions": len(func_encyclopedia.functions), "total_types": len(type_mapper.mappings), "total_dialects": len(SUPPORTED_DIALECTS), "conversion_rules": 40},
            "functions": {"total": len(func_encyclopedia.functions), "categories": func_categories, "category_count": len(func_categories)},
            "types": {"total": len(type_mapper.mappings), "dialects": len(type_mapper.DIALECTS), "categories": ["String", "Numeric", "Date/Time", "Complex", "Binary", "Special"]},
            "dialects": {"list": SUPPORTED_DIALECTS, "details": DIALECT_INFO},
        },
        "timestamp": datetime.now().isoformat(),
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
    uvicorn.run(app, host="0.0.0.0", port=8000)
