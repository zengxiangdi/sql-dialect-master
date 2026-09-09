#!/usr/bin/env python3
"""FastAPI Backend for SQL Dialect Master."""
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.core.config import get_dialect_api_info, settings, setup_logging
from backend.core.functions_lookup import FunctionEncyclopedia
from backend.core.nl2sql import NL2SQLGenerator
from backend.core.parser import SUPPORTED_DIALECTS, SQLParser
from backend.core.transpiler import SQLTranspiler
from backend.core.type_mapping import TypeMapper
from backend.api.readiness import health_probe_response

logger = setup_logging(level=logging.INFO)
api_logger = logging.getLogger(__name__)
API_VERSION = settings.api_version
API_TITLE = settings.api_title
API_DESCRIPTION = "Enterprise-grade multi-database SQL conversion engine."

app = FastAPI(title=API_TITLE, description=API_DESCRIPTION, version=API_VERSION, docs_url="/docs", redoc_url="/redoc")

from backend.api.middleware import RateLimiter, RateLimitMiddleware, SecurityHeadersMiddleware, StructuredLoggingMiddleware
from backend.core.exceptions import SDMException, UnsupportedDialectError, ErrorCode

ALLOWED_ORIGINS = [origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=True, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type", "Authorization", "X-Request-ID"])
app.add_middleware(SecurityHeadersMiddleware)
rate_limiter = RateLimiter(requests_per_window=settings.rate_limit_requests, window_seconds=settings.rate_limit_window)
app.add_middleware(RateLimitMiddleware, limiter=rate_limiter, enabled=settings.rate_limit_enabled)
app.add_middleware(StructuredLoggingMiddleware)

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
    normalized = dialect.strip().lower()
    if normalized not in SUPPORTED_DIALECTS:
        raise HTTPException(status_code=400, detail=f"Unsupported {field_name}: {dialect}. Supported: {SUPPORTED_DIALECTS}")
    return normalized

class ConvertRequest(BaseModel):
    sql: str = Field(...)
    source_dialect: str = Field(...)
    target_dialect: str = Field(...)
    pretty: bool = Field(True)

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
    text: str = Field(...)
    dialect: str = Field("hive")
    table_hint: Optional[str] = None
    column_hints: Optional[List[str]] = None

class NL2SQLResponse(BaseModel):
    success: bool
    input_text: str
    sql: Optional[str] = None
    dialect: str
    explanation: str = ""
    confidence: float = 0.0
    suggestions: List[str] = Field(default_factory=list)

class ParseRequest(BaseModel):
    sql: str = Field(...)
    dialect: str = Field("hive")

class TypeMapRequest(BaseModel):
    type_name: str = Field(...)
    source_dialect: str = Field(...)
    target_dialect: str = Field(...)

class APIResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

@app.get("/")
async def root():
    return {"name": API_TITLE, "version": API_VERSION, "status": "✅ Online", "description": "Enterprise-grade multi-database SQL conversion engine", "stats": {"functions": {"count": len(func_encyclopedia.functions), "label": "📚 SQL Functions"}, "types": {"count": len(type_mapper.mappings), "label": "🗂️ Data Types"}, "dialects": {"count": len(SUPPORTED_DIALECTS), "label": "💾 Databases"}, "rules": {"count": len(transpiler.post_processor.engine.rules), "label": "🔧 Conversion Rules"}}, "timestamp": datetime.now().isoformat()}

@app.get("/api/dialects")
async def get_dialects():
    by_category = {}
    for dialect, info in DIALECT_INFO.items():
        cat = info["category"]
        by_category.setdefault(cat, []).append({"id": dialect, "name": info["name"], "icon": info["icon"]})
    return {"success": True, "dialects": SUPPORTED_DIALECTS, "count": len(SUPPORTED_DIALECTS), "details": DIALECT_INFO, "by_category": by_category, "categories": list(by_category.keys())}

@app.post("/api/convert", response_model=ConvertResponse)
async def convert_sql(request: ConvertRequest):
    source_dialect = request.source_dialect.strip().lower()
    target_dialect = request.target_dialect.strip().lower()
    if source_dialect not in SUPPORTED_DIALECTS:
        raise HTTPException(status_code=400, detail=f"Unsupported source dialect: {request.source_dialect}. Supported: {SUPPORTED_DIALECTS}")
    if target_dialect not in SUPPORTED_DIALECTS:
        raise HTTPException(status_code=400, detail=f"Unsupported target dialect: {request.target_dialect}. Supported: {SUPPORTED_DIALECTS}")
    result = transpiler.transpile(request.sql, source_dialect, target_dialect, request.pretty)
    return ConvertResponse(success=result.success, source_sql=result.source_sql, target_sql=result.target_sql, source_dialect=result.source_dialect, target_dialect=result.target_dialect, error=result.error, error_code=result.error_code, compatibility_notes=result.compatibility_notes, transformations=result.transformations, warnings=result.warnings)

@app.post("/api/parse")
async def parse_sql(request: ParseRequest):
    dialect = normalize_dialect(request.dialect)
    elements = SQLParser(dialect).extract_elements(request.sql)
    return {"success": True, "dialect": dialect, "elements": elements, "timestamp": datetime.now().isoformat()}

@app.get("/api/functions")
async def list_functions(search: Optional[str] = Query(None), category: Optional[str] = Query(None), limit: int = Query(50, ge=1, le=500)):
    functions = func_encyclopedia.search(search, limit) if search else func_encyclopedia.list_by_category(category) if category else func_encyclopedia.functions[:limit]
    return {"success": True, "functions": functions, "count": len(functions), "total": len(func_encyclopedia.functions), "stats": func_encyclopedia.get_stats()}

@app.get("/api/functions/categories")
async def get_function_categories():
    categories = func_encyclopedia.get_all_categories()
    return {"success": True, "categories": categories, "count": len(categories)}

@app.get("/api/functions/{name}")
async def get_function(name: str):
    func = func_encyclopedia.get_function(name)
    if not func:
        raise HTTPException(status_code=404, detail=f"Function '{name}' not found. Try searching with /api/functions?search={name}")
    return {"success": True, "function": func, "comparison": func_encyclopedia.compare_dialects(name)}

@app.get("/api/types")
async def list_types(source: Optional[str] = Query(None), target: Optional[str] = Query(None)):
    source = normalize_dialect(source, "source dialect") if source is not None else None
    target = normalize_dialect(target, "target dialect") if target is not None else None
    matrix = type_mapper.get_matrix(source, target)
    return {"success": True, "mappings": matrix, "dialects": type_mapper.DIALECTS, "type_count": len(matrix), "precision_warnings": type_mapper.get_precision_warnings()}

@app.post("/api/types/map")
async def map_type(request: TypeMapRequest):
    source = normalize_dialect(request.source_dialect, "source dialect")
    target = normalize_dialect(request.target_dialect, "target dialect")
    result = type_mapper.map_type(request.type_name, source, target)
    return {"success": result["success"], "type_name": request.type_name, "source_dialect": source, "target_dialect": target, "target_type": result.get("target_type"), "notes": result.get("notes", []), "timestamp": datetime.now().isoformat()}

@app.get("/api/types/{type_name}")
async def get_type(type_name: str):
    result = type_mapper.get_type_info(type_name)
    if not result:
        raise HTTPException(status_code=404, detail=f"Type '{type_name}' not found")
    return {"success": True, "type": result, "timestamp": datetime.now().isoformat()}

@app.post("/api/nl2sql", response_model=NL2SQLResponse)
async def generate_sql(request: NL2SQLRequest):
    dialect = normalize_dialect(request.dialect)
    result = nl2sql_generator.generate(request.text, dialect, request.table_hint, request.column_hints)
    return NL2SQLResponse(success=result.success, input_text=result.input_text, sql=result.sql, dialect=dialect, explanation=result.explanation, confidence=result.confidence, suggestions=result.suggestions)

@app.get("/health")
async def health_check():
    return {"status": "alive", "version": API_VERSION, "timestamp": datetime.now().isoformat()}

@app.get("/ready")
async def readiness_check(request: Request):
    return await health_probe_response(request)

@app.get("/health/deep")
async def deep_health_check(request: Request):
    return await health_probe_response(request)

@app.get("/api/stats")
async def get_stats():
    func_categories = func_encyclopedia.get_all_categories()
    return {"success": True, "stats": {"overview": {"total_functions": len(func_encyclopedia.functions), "total_types": len(type_mapper.mappings), "total_dialects": len(SUPPORTED_DIALECTS), "conversion_rules": len(transpiler.post_processor.engine.rules)}, "functions": {"total": len(func_encyclopedia.functions), "categories": func_categories, "category_count": len(func_categories)}, "types": {"total": len(type_mapper.mappings), "dialects": len(type_mapper.DIALECTS), "categories": ["String", "Numeric", "Date/Time", "Complex", "Binary", "Special"]}, "dialects": {"list": SUPPORTED_DIALECTS, "details": DIALECT_INFO}}, "timestamp": datetime.now().isoformat()}

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"success": False, "error": {"code": exc.status_code, "message": exc.detail, "type": "HTTPException"}, "timestamp": datetime.now().isoformat()})

@app.exception_handler(SDMException)
async def sdm_exception_handler(request: Request, exc: SDMException):
    status_code = 400
    if isinstance(exc, UnsupportedDialectError):
        status_code = 400
    error = exc.to_dict()
    if "code" not in error:
        error["code"] = exc.error_code.value if isinstance(exc.error_code, ErrorCode) else str(exc.error_code)
    return JSONResponse(status_code=status_code, content={"success": False, "error": error, "timestamp": datetime.now().isoformat()})

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    logger.exception("Unhandled API exception", extra={"request_id": request_id})
    content = {"success": False, "error": {"code": ErrorCode.INTERNAL_ERROR.value, "message": "Internal server error"}, "timestamp": datetime.now().isoformat()}
    if request_id:
        content["request_id"] = request_id
    return JSONResponse(status_code=500, content=content)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)