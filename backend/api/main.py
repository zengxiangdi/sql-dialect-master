#!/usr/bin/env python3
"""FastAPI Backend for SQL Dialect Master.

Enterprise-grade multi-database SQL conversion API:
- 12 database dialects
- SQL functions encyclopedia
- data type mappings
- conversion rules
- Natural language to SQL generation

Exact counts are derived from the canonical data files at runtime —
see backend.core.metadata — and must not be restated here.
"""
import asyncio
import atexit
import copy
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from functools import lru_cache
from threading import Lock
from typing import Annotated, Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from backend.api.auth import require_api_access
from backend.api.metrics import (
    MetricsMiddleware,
    configure_runtime_metrics,
    metrics_response,
    observe_transpile_batch_size,
    record_nl2sql_llm_fallback,
    record_nl2sql_llm_request,
    record_transpile_batch_items,
    record_transpile_batch_request,
    record_transpile_request,
)
from backend.api.rate_limit_store import InMemoryRateLimitStore
from backend.api.readiness import health_probe_response
from backend.api.workers import BoundedWorkerPool, WorkerCapacityError
from backend.core import metadata as meta
from backend.core.column_hint_validation import validate_column_hints
from backend.core.config import get_dialect_api_info, settings, setup_logging
from backend.core.functions_lookup import FunctionEncyclopedia
from backend.core.nl2sql import NL2SQLGenerator, NL2SQLResult
from backend.core.nl2sql_components.evidence import EvidenceItem, GenerationEvidence
from backend.core.nl2sql_llm import LLMError, LLMN2SQLClient, validate_llm_sql
from backend.core.nl2sql_schema import SchemaContext
from backend.core.nl2sql_pipeline.orchestrator import SAFE_TABLE_HINT
from backend.core.parser import SUPPORTED_DIALECTS, SQLParser
from backend.core.semantic_diff import diff_sql_ast
from backend.core.transpiler import SQLTranspiler
from backend.core.type_mapping import TypeMapper

# Configure logging for the application from the validated settings object.
# Keep an INFO fallback for defensive compatibility with custom settings
# objects, while normal AppSettings values are resolved from SDM_LOG_LEVEL.
_log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
logger = setup_logging(level=_log_level, log_file=settings.log_file or None)
api_logger = logging.getLogger(__name__)
_worker_pool: BoundedWorkerPool | None = None
_worker_pool_lock = Lock()
_worker_pool_exit_hook = None


def _get_worker_pool() -> BoundedWorkerPool:
    """Return the process-wide pool, creating it lazily for non-ASGI callers.

    ``app`` is intentionally resolved when this helper is called, after the
    module-level FastAPI application has been initialized.  This keeps import
    time free of executor creation while preserving the ASGI/non-ASGI split.
    """
    state_pool = getattr(app.state, "worker_pool", None)
    if state_pool is not None:
        return state_pool

    global _worker_pool, _worker_pool_exit_hook
    with _worker_pool_lock:
        if _worker_pool is None:
            _worker_pool = BoundedWorkerPool(settings.api_workers, settings.api_queue_size)
            # Direct callers (benchmarks/tests/scripts) do not enter the ASGI
            # lifespan, so give their lazily-created pool a process shutdown
            # hook instead of leaving executor threads alive indefinitely.
            _worker_pool_exit_hook = _worker_pool.shutdown
            atexit.register(_worker_pool_exit_hook)
        return _worker_pool


def shutdown_worker_pool() -> None:
    """Explicitly release a lazily-created non-ASGI worker pool.

    Scripts and benchmarks should call this when their work is complete. The
    atexit hook is retained only as a final safety net and is unregistered
    before shutdown, so explicit and process-exit cleanup cannot run twice.
    """
    global _worker_pool, _worker_pool_exit_hook
    with _worker_pool_lock:
        pool = _worker_pool
        hook = _worker_pool_exit_hook
        _worker_pool = None
        _worker_pool_exit_hook = None
        if hook is not None:
            atexit.unregister(hook)
    if pool is not None:
        pool.shutdown()


@lru_cache(maxsize=len(SUPPORTED_DIALECTS))
def _get_sql_parser(dialect: str) -> SQLParser:
    """Return the immutable parser shell shared by parse requests.

    ``SQLParser`` stores only the normalized dialect and stateless extraction
    helpers.  Reusing one instance per dialect avoids constructing the same
    object for every request while keeping request-specific AST/results local
    to the worker that executes them.
    """
    return SQLParser(dialect)


@lru_cache(maxsize=256)
def _parse_elements_cached(dialect: str, sql: str) -> dict[str, Any]:
    """Cache bounded parser extraction results for repeated API queries."""
    return _get_sql_parser(dialect).extract_elements(sql)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Manage the service worker pool for a normal ASGI startup/shutdown."""
    pool = _get_worker_pool()
    application.state.worker_pool = pool
    try:
        yield
    finally:
        if _worker_pool is pool:
            shutdown_worker_pool()
        else:
            pool.shutdown()
        if getattr(application.state, "worker_pool", None) is pool:
            del application.state.worker_pool


async def _run_cpu_bound(func, *args):
    """Run parser/transpiler work off-loop with the configured timeout."""
    try:
        pool = _get_worker_pool()
        return await pool.run(func, *args, timeout=settings.request_timeout)
    except WorkerCapacityError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
            headers={"Retry-After": "1"},
        ) from exc
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="Request processing timed out",
        ) from exc

# API metadata
API_VERSION = settings.api_version
API_TITLE = settings.api_title
API_DESCRIPTION = f"""
# 🔄 SQL Dialect Master API

Enterprise-grade multi-database SQL conversion engine.

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔄 **SQL Conversion** | Convert SQL between {meta.SUPPORTED_DIALECTS_COUNT} database dialects |
| 📚 **Function Encyclopedia** | {meta.FUNCTION_COUNT} SQL functions with cross-database comparison |
| 🗂️ **Type Mapping** | {meta.TYPE_COUNT} data type mappings × {meta.SUPPORTED_DIALECTS_COUNT} databases matrix |
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
response = requests.post("http://localhost:8000/api/convert", json={{
    "sql": "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') FROM orders",
    "source_dialect": "mysql",
    "target_dialect": "postgres"
}})
print(response.json()["target_sql"])
```

## 📖 API Endpoints

- `POST /api/convert` - Convert SQL between {meta.SUPPORTED_DIALECTS_COUNT} database dialects
- `GET /api/functions` - Search SQL functions
- `GET /api/types` - Get type mapping matrix
- `POST /api/nl2sql` - Generate SQL from natural language
"""

# Initialize FastAPI app with enhanced metadata
app = FastAPI(
    dependencies=[Depends(require_api_access)],
    lifespan=lifespan,
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
            "description": f"📚 SQL function encyclopedia with {meta.FUNCTION_COUNT} functions"
        },
        {
            "name": "types",
            "description": f"🗂️ Data type mapping matrix ({meta.TYPE_COUNT} types × {meta.SUPPORTED_DIALECTS_COUNT} databases)"
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
    CacheControlMiddleware,
    RateLimiter,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    StructuredLoggingMiddleware,
)
from backend.core.exceptions import SDMException, UnsupportedDialectError, ErrorCode

# Configure CORS from the centralized Pydantic settings source.
ALLOWED_ORIGINS = [origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()]
TRUSTED_PROXY_NETWORKS = settings.trusted_proxy_networks

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],  # Restrict to needed methods
    # Keep preflight explicit so browser clients can send the correlation and
    # API-key headers used by the React request layer.  Expose operational
    # response headers as well: without this list browsers silently hide
    # Retry-After and request timing/correlation metadata from JavaScript even
    # though the server emits them correctly.
    allow_headers=["Accept", "Content-Type", "Authorization", "X-API-Key", "X-Request-ID"],
    expose_headers=[
        "Retry-After",
        "X-API-Version",
        "X-Process-Time",
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "X-Request-ID",
    ],
)

# Type/function matrices and conversion reports are often much larger than
# the request itself.  Compress them at the ASGI boundary so browser clients
# spend less time waiting on the network without changing response schemas.
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

# Add security headers
app.add_middleware(SecurityHeadersMiddleware)

# Add rate limiting (configurable via settings)
rate_limiter = RateLimiter(
    requests_per_window=settings.rate_limit_requests,
    window_seconds=settings.rate_limit_window,
    store=None if settings.rate_limit_enabled else InMemoryRateLimitStore(),
)
app.add_middleware(
    RateLimitMiddleware,
    limiter=rate_limiter,
    enabled=settings.rate_limit_enabled,
    trusted_proxies=TRUSTED_PROXY_NETWORKS,
)

# Structured request logging must wrap rate limiting so rejected requests also get IDs.
app.add_middleware(
    StructuredLoggingMiddleware,
    trusted_proxies=TRUSTED_PROXY_NETWORKS,
)
app.add_middleware(CacheControlMiddleware)

# Initialize services
transpiler = SQLTranspiler()
func_encyclopedia = FunctionEncyclopedia()
type_mapper = TypeMapper()
nl2sql_generator = NL2SQLGenerator()

configure_runtime_metrics(
    transpiler_provider=lambda: transpiler,
    worker_provider=_get_worker_pool,
    limiter_provider=lambda: rate_limiter,
)

# Request timing middleware with logging
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    # ``perf_counter`` is monotonic and high resolution.  Wall-clock time can
    # jump when NTP adjusts the host clock, which would otherwise produce a
    # negative or wildly inflated duration header and log entry.
    start_time = time.perf_counter()
    response = await call_next(request)
    process_time = time.perf_counter() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.4f}s"
    response.headers["X-API-Version"] = API_VERSION

    # Log request details
    api_logger.info("%s %r - %s - %.4fs", request.method, request.url.path,
                    response.status_code, process_time)
    return response


# This is the outermost application middleware, so it also observes short
# circuit responses returned by rate limiting and worker-capacity guards.
app.add_middleware(MetricsMiddleware)

# Dialect info for enhanced responses (from centralized config)
DIALECT_INFO = get_dialect_api_info()


def normalize_dialect(dialect: str, field_name: str = "dialect") -> str:
    """Normalize and validate a dialect at the API boundary."""
    normalized = dialect.strip().lower()
    if normalized not in SUPPORTED_DIALECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported {field_name}: {dialect}. Supported: {SUPPORTED_DIALECTS}",
        )
    return normalized

# === Request/Response Models with Enhanced Documentation ===

class ConvertRequest(BaseModel):
    """SQL conversion request model."""
    sql: str = Field(..., description="Source SQL statement to convert")
    source_dialect: str = Field(..., description="Source database dialect")
    target_dialect: str = Field(..., description="Target database dialect")
    pretty: bool = Field(
        settings.transpiler_pretty_default,
        description="Format output SQL with indentation",
    )

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
    error_code: Optional[str] = Field(None, description="Stable machine-readable error category")
    compatibility_notes: List[str] = Field(default_factory=list, description="Compatibility notes")
    transformations: List[str] = Field(default_factory=list, description="Applied transformations")
    warnings: List[str] = Field(default_factory=list, description="Conversion warnings")
    target_validation_state: str = Field(
        "target_valid",
        description=(
            "Target-dialect parse status of the produced output. "
            '"target_valid": target parser accepted the output; '
            '"generic_only": target parser rejected it but the generic parser '
            'accepted it — the conversion is retained with a warning and must '
            'not be read as target-validated; '
            '"invalid": neither parser accepts the output.'
        ),
    )
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat(), description="Response timestamp")


class BatchConvertRequest(BaseModel):
    """Convert an ordered, bounded list using one dialect pair."""

    statements: List[StrictStr] = Field(
        ...,
        min_length=1,
        max_length=settings.max_batch_size,
        description="SQL statements in input order; each item is converted independently",
    )
    source_dialect: str
    target_dialect: str
    pretty: bool = settings.transpiler_pretty_default


class BatchConvertItemResponse(ConvertResponse):
    """A conversion result associated with its original input position."""

    index: int = Field(..., ge=0, description="Zero-based index in the input statements")


class BatchConvertResponse(BaseModel):
    """Ordered conversion results, including ordinary per-item failures."""

    success: bool
    results: List[BatchConvertItemResponse]
    count: int
    succeeded: int
    failed: int
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


SchemaIdentifier = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*)*$",
    ),
]


class SchemaColumn(BaseModel):
    name: SchemaIdentifier
    type: Optional[str] = None


class SchemaTable(BaseModel):
    name: SchemaIdentifier
    columns: List[SchemaColumn] = Field(default_factory=list, max_length=200)


class SchemaRelationship(BaseModel):
    from_table: SchemaIdentifier
    from_column: SchemaIdentifier
    to_table: SchemaIdentifier
    to_column: SchemaIdentifier


class SchemaDefinition(BaseModel):
    tables: List[SchemaTable] = Field(default_factory=list, max_length=50)
    relationships: List[SchemaRelationship] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_total_columns(self):
        if sum(len(table.columns) for table in self.tables) > 1000:
            raise ValueError("Schema must contain at most 1000 columns in total")
        table_names = {table.name.casefold() for table in self.tables}
        for relationship in self.relationships:
            if (
                relationship.from_table.casefold() not in table_names
                or relationship.to_table.casefold() not in table_names
            ):
                raise ValueError("Schema relationship references an unknown table")
        return self


class NL2SQLRequest(BaseModel):
    """Natural language to SQL request model."""
    text: str = Field(..., description="Natural language query (Chinese or English)")
    dialect: str = Field("hive", description="Target SQL dialect")
    table_hint: Optional[str] = Field(None, description="Optional table name hint")
    column_hints: Optional[List[str]] = Field(
        None,
        description="Optional column identifier hints; accepts simple or dotted identifiers",
    )
    # Alias avoids shadowing Pydantic's legacy BaseModel.schema method.
    schema_definition: Optional[SchemaDefinition] = Field(
        None, alias="schema", description="Optional database schema for LLM generation and validation",
    )

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "text": "统计每个部门的员工数量",
            "dialect": "mysql",
            "table_hint": "employees",
            "column_hints": ["employees.department", "employees.id"]
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
    parameter_style: Optional[str] = Field(
        None,
        description=(
            "Placeholder style for generated DML: numeric ($1 in PostgreSQL/Redshift, "
            ":1 in Oracle), named (@p1 in T-SQL), format (%s in MySQL), or qmark (?)"
        ),
    )
    parameters: List[str] = Field(
        default_factory=list,
        description="Ordered placeholders that callers must bind for generated DML",
    )
    evidence: Optional[Dict[str, Any]] = Field(
        None, description="Structured evidence supporting the confidence score",
    )
    provider: str = "deterministic"
    model: Optional[str] = None
    fallback_reason: Optional[str] = None
    schema_used: bool = False

class ParseRequest(BaseModel):
    """SQL parse request model."""
    sql: str = Field(..., description="SQL statement to parse")
    dialect: str = Field("hive", description="SQL dialect")


class DiffRequest(BaseModel):
    """Semantic SQL comparison request."""

    source_sql: str = Field(..., description="Source SQL statement")
    target_sql: str = Field(..., description="Target SQL statement")
    source_dialect: str = Field(..., description="Source SQL dialect")
    target_dialect: str = Field(..., description="Target SQL dialect")

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

@app.get("/metrics", include_in_schema=False)
async def metrics_endpoint(request: Request):
    return await metrics_response(request)

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
            "🔍 deep health": {"url": "/health/deep", "method": "GET"},
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
    source_dialect = request.source_dialect.strip().lower()
    target_dialect = request.target_dialect.strip().lower()
    if source_dialect not in SUPPORTED_DIALECTS:
        record_transpile_request("unknown", "unknown", "validation_error")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported source dialect: {request.source_dialect}. Supported: {SUPPORTED_DIALECTS}"
        )
    if target_dialect not in SUPPORTED_DIALECTS:
        record_transpile_request(source_dialect, "unknown", "validation_error")
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported target dialect: {request.target_dialect}. Supported: {SUPPORTED_DIALECTS}"
        )

    # sqlglot parsing/transpilation is CPU-bound.  Keep it off the event loop
    # so one large request cannot stall unrelated async requests.
    try:
        result = await _run_cpu_bound(
            transpiler.transpile,
            request.sql,
            source_dialect,
            target_dialect,
            request.pretty,
        )
    except HTTPException:
        record_transpile_request(source_dialect, target_dialect, "error")
        raise
    record_transpile_request(
        source_dialect,
        target_dialect,
        "success" if result.success else "error",
    )
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
        target_validation_state=result.target_validation_state,
    )

@app.post("/api/convert/batch", response_model=BatchConvertResponse, tags=["conversion"])
async def convert_sql_batch(request: BatchConvertRequest):
    """Convert statements sequentially in one worker slot, preserving input order.

    Ordinary item failures, including a batch where every item fails, return
    HTTP 200 with per-item errors. Request-level failures use the existing
    error envelope. A 504 ends the wait but does not cancel the worker batch.
    """
    source_dialect = target_dialect = "unknown"
    try:
        source_dialect = normalize_dialect(request.source_dialect, "source dialect")
        target_dialect = normalize_dialect(request.target_dialect, "target dialect")
        observe_transpile_batch_size(len(request.statements))
        batch_results = await _run_cpu_bound(
            transpiler.batch_transpile,
            list(request.statements),
            source_dialect,
            target_dialect,
            request.pretty,
        )
        results = [
            BatchConvertItemResponse(index=index, **result.to_dict())
            for index, result in enumerate(batch_results)
        ]
        count = len(results)
        succeeded = sum(item.success for item in results)
        failed = count - succeeded
        response = BatchConvertResponse(
            success=failed == 0,
            results=results,
            count=count,
            succeeded=succeeded,
            failed=failed,
        )
    except HTTPException as exc:
        record_transpile_batch_request(
            source_dialect,
            target_dialect,
            "validation_error" if exc.status_code == 400 else "error",
        )
        raise
    except Exception:
        record_transpile_batch_request(source_dialect, target_dialect, "error")
        raise

    record_transpile_batch_items(source_dialect, target_dialect, succeeded, failed)
    record_transpile_batch_request(
        source_dialect,
        target_dialect,
        "success" if failed == 0 else "partial_failure" if succeeded else "error",
    )
    return response


@app.post("/api/parse", tags=["conversion"])
async def parse_sql(request: ParseRequest):
    """
    Parse SQL and extract elements.

    Extracts tables, columns, functions, and other elements from SQL.
    """
    dialect = normalize_dialect(request.dialect)
    elements = await _run_cpu_bound(_parse_elements_cached, dialect, request.sql)
    elements = copy.deepcopy(elements)
    if "error" in elements:
        raise HTTPException(status_code=422, detail=elements["error"] or "SQL parsing failed")
    return {
        "success": True,
        "dialect": dialect,
        "elements": elements,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/diff", tags=["conversion"])
async def compare_semantic_diff(request: DiffRequest):
    """Compare source and target SQL without executing either statement."""
    source_dialect = normalize_dialect(request.source_dialect, "source dialect")
    target_dialect = normalize_dialect(request.target_dialect, "target dialect")
    result = await _run_cpu_bound(
        diff_sql_ast,
        request.source_sql,
        request.target_sql,
        source_dialect,
        target_dialect,
    )
    payload = asdict(result)
    payload["success"] = True
    if result.parse_error:
        payload["error"] = result.parse_error
    return payload

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
    normalized_category = category.strip().lower() if category is not None else None
    if category is not None:
        if normalized_category not in func_encyclopedia.CATEGORIES:
            raise HTTPException(
                status_code=400,
                detail=(f"Unknown function category: {category}. Available categories: "
                        + ", ".join(func_encyclopedia.CATEGORIES)),
            )
    if search:
        # The search cache applies the category predicate before ranking and
        # the public limit, so category-filtered queries do not scan or copy
        # unrelated function records.
        functions = func_encyclopedia.search(search, limit, normalized_category)
    elif category:
        functions = func_encyclopedia.list_by_category(normalized_category)[:limit]
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

    Returns the complete type mapping matrix (canonical type count × 12 databases).

    **Type Categories:**
    - String: STRING, VARCHAR, CHAR, TEXT, etc.
    - Numeric: BIGINT, INT, DECIMAL, FLOAT, etc.
    - Date/Time: DATE, TIME, TIMESTAMP, INTERVAL
    - Complex: ARRAY, MAP, STRUCT, JSON
    - Special: UUID, INET, GEOMETRY
    """
    if source is not None:
        source = normalize_dialect(source, "source dialect")
    if target is not None:
        target = normalize_dialect(target, "target dialect")
    matrix = type_mapper.get_matrix(source, target)
    mappings = [
        {"type": type_name, **mapping}
        for type_name, mapping in matrix.items()
    ] if isinstance(matrix, dict) else list(matrix)
    return {
        "success": True,
        "mappings": mappings,
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
    source_dialect = normalize_dialect(request.source_dialect, "source dialect")
    target_dialect = normalize_dialect(request.target_dialect, "target dialect")

    result = type_mapper.suggest_type(
        request.type_name,
        source_dialect,
        target_dialect,
    )
    return {
        "success": result.get("success", False),
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
    dialect = normalize_dialect(request.dialect)
    # Validate table_hint at the API boundary: an illegal identifier is
    # a client error (4xx), never an internal ValueError → 500.  The
    # same rule backs the orchestrator's direct-caller ValueError.
    if request.table_hint and not SAFE_TABLE_HINT.fullmatch(request.table_hint.strip()):
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid table_hint: must be a simple SQL identifier or "
                "dotted identifier"
            ),
        )
    schema_payload = (
        request.schema_definition.model_dump(exclude_none=True)
        if request.schema_definition is not None else None
    )
    schema_context = (
        SchemaContext.from_mapping(schema_payload)
        if schema_payload is not None else None
    )
    use_llm = (
        settings.nl2sql_llm_enabled
        and bool(request.text.strip())
        and len(request.text) <= settings.nl2sql_max_input_length
        and validate_column_hints(request.column_hints) is None
        and nl2sql_generator._detect_operation(request.text.lower()) not in {"INSERT", "UPDATE", "DELETE"}
    )
    if not use_llm:
        if schema_context is None:
            result = await _run_cpu_bound(
                nl2sql_generator.generate,
                request.text,
                dialect,
                request.table_hint,
                request.column_hints,
            )
        else:
            result = await _run_cpu_bound(
                nl2sql_generator.generate,
                request.text,
                dialect,
                request.table_hint,
                request.column_hints,
                schema_context,
            )
    else:
        schema = schema_payload
        started = time.perf_counter()
        try:
            # Keep the legacy no-schema client call compatible with direct
            # callers and providers that implement the existing signature.
            schema_options = {"schema": schema} if schema is not None else {}
            generation = await LLMN2SQLClient().generate(
                request.text, dialect, request.table_hint, request.column_hints,
                **schema_options,
            )
            sql = validate_llm_sql(generation.sql, dialect, **schema_options)
        except LLMError as exc:
            record_nl2sql_llm_request(exc.reason, time.perf_counter() - started)
            if settings.nl2sql_llm_fallback:
                record_nl2sql_llm_fallback()
                if schema_context is None:
                    deterministic_result = await _run_cpu_bound(
                        nl2sql_generator.generate,
                        request.text,
                        dialect,
                        request.table_hint,
                        request.column_hints,
                    )
                else:
                    deterministic_result = await _run_cpu_bound(
                        nl2sql_generator.generate,
                        request.text,
                        dialect,
                        request.table_hint,
                        request.column_hints,
                        schema_context,
                    )
                result = copy.copy(deterministic_result)
                result.provider = "deterministic"
                result.model = None
                result.fallback_reason = exc.reason
                result.schema_used = bool(
                    schema_context is not None
                    and deterministic_result.success
                    and deterministic_result.schema_used
                )
            else:
                result = NL2SQLResult(
                    input_text=request.text,
                    dialect=dialect,
                    explanation="LLM generation is unavailable or returned SQL that could not be validated.",
                    provider="llm",
                )
        else:
            record_nl2sql_llm_request("success", time.perf_counter() - started)
            result = NL2SQLResult(
                success=True,
                input_text=request.text,
                sql=sql,
                dialect=dialect,
                explanation=f"Generated by {generation.model} via OpenRouter.",
                confidence=0.8,
                evidence=GenerationEvidence([
                    EvidenceItem("llm_generated", "Generated by the configured LLM", 0.8, detail=generation.model),
                ]),
                suggestions=["Review the generated SQL before executing it."],
                provider="llm",
                model=generation.model,
                schema_used=bool(schema and (schema["tables"] or schema["relationships"])),
            )
    return NL2SQLResponse(
        success=result.success,
        input_text=result.input_text,
        sql=result.sql,
        dialect=dialect,
        explanation=result.explanation,
        confidence=result.confidence,
        suggestions=list(result.suggestions[: settings.nl2sql_max_suggestions]),
        parameter_style=result.parameter_style,
        parameters=list(result.parameters),
        evidence=result.evidence.to_dict() if result.evidence is not None else None,
        provider=getattr(result, "provider", "deterministic"),
        model=getattr(result, "model", None),
        fallback_reason=getattr(result, "fallback_reason", None),
        schema_used=getattr(result, "schema_used", False),
    )

@app.get("/health", tags=["system"])
async def health_check():
    """Return process liveness without probing business dependencies."""
    return {
        "status": "alive",
        "version": API_VERSION,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/ready", tags=["system"])
async def readiness_check(request: Request):
    """Return readiness after authorized dependency probes."""
    return await health_probe_response(request)

@app.get("/health/deep", tags=["system"])
async def deep_health_check(request: Request):
    """Return deep health using the shared authorized dependency probe service."""
    return await health_probe_response(request)

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
                "conversion_rules": len(transpiler.post_processor.engine.rules)
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
@app.exception_handler(RequestValidationError)
async def safe_schema_validation_handler(request: Request, exc: RequestValidationError):
    """Keep schema inputs out of 422 details without changing the envelope."""
    if request.url.path == "/api/nl2sql" and isinstance(exc.body, dict) and "schema" in exc.body:
        # A missing top-level field can include the entire body as its input,
        # so sanitize every error for schema-bearing requests, not only errors
        # whose location is inside schema. All messages remain fixed by the
        # Pydantic constraints above; context and input may contain user data.
        errors = [
            {key: error[key] for key in ("type", "loc", "msg") if key in error}
            for error in exc.errors()
        ]
        exc = RequestValidationError(errors)
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    error_code_by_status = {
        503: ErrorCode.SERVICE_UNAVAILABLE.value,
        504: ErrorCode.REQUEST_TIMEOUT.value,
    }
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "success": False,
            "error": {
                "code": error_code_by_status.get(exc.status_code, exc.status_code),
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

    error = exc.to_dict()
    if "code" not in error:
        error["code"] = exc.error_code.value if isinstance(exc.error_code, ErrorCode) else str(exc.error_code)

    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": error,
            "timestamp": datetime.now().isoformat()
        }
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Return a generic 500 response while retaining request correlation internally."""
    request_id = getattr(request.state, "request_id", None)
    logger.exception("Unhandled API exception", extra={"request_id": request_id})
    content = {
        "success": False,
        "error": {
            "code": ErrorCode.INTERNAL_ERROR.value,
            "message": "Internal server error",
        },
        "timestamp": datetime.now().isoformat(),
    }
    if request_id:
        content["request_id"] = request_id
    return JSONResponse(status_code=500, content=content)

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
