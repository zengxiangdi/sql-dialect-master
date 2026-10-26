# 🔄 SQL Dialect Master

Enterprise-grade multi-database SQL conversion engine supporting 12 database dialects.

Current release: 1.4.0

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB.svg)](https://react.dev/)

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔄 **SQL Conversion** | Convert SQL between 12 database dialects with a complete 12 × 12 conversion matrix |
| ✅ **Output Validation** | Validate converted SQL with target-dialect parsing plus safe generic-parser fallback |
| 🧠 **Semantic Regression Coverage** | Preserve predicates, joins, grouping, ordering, limits, windows, and round-trip validity |
| 🔍 **AST Semantic Diff** | Compare dialect-aware SQL ASTs to detect structural changes introduced by conversion |
| 🗄️ **Runtime Semantic Tests** | Execute representative conversions against PostgreSQL and DuckDB and compare result sets |
| 📚 **Function Encyclopedia** | 298 SQL functions with cross-database comparison |
| 🗂️ **Type Mapping** | 39 data types × 12 databases matrix |
| 💬 **NL2SQL** | Natural language to SQL (Chinese/English) |
| 🔧 **Rule Engine** | Deterministic priority ordering, compiled patterns, dialect-aware conflict detection |
| 🛡️ **Security Validation** | Statement-level stacked-query detection with configurable blocking policy |
| ⚡ **Performance** | Rule-aware cache versioning, bounded async batch conversion, and reproducible benchmark |
| 🎨 **Modern UI** | React developer workspace with dark / light themes, responsive navigation, and command palette |

## 💾 Supported Databases

| Category | Databases |
|----------|-----------|
| **RDBMS** | MySQL 🐬, PostgreSQL 🐘, Oracle 🔴, SQL Server 🟦 |
| **Big Data** | Hive 🐝, Spark ⚡, Trino 🔷, Databricks 🧱 |
| **Cloud DW** | Snowflake ❄️, Redshift 🔶 |
| **OLAP** | ClickHouse 🏠, DuckDB 🦆 |

## 🚀 Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/zengxiangdi/sql-dialect-master.git
cd sql-dialect-master

# Install the application package
python -m pip install -e .
```

For development, testing, quality checks, and local builds, use the project's
Python environment and install the optional tooling:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev,qa]"
```

For database-backed semantic tests:

```bash
.venv/bin/python -m pip install -e ".[dev,semantic]"
```

### Run the React UI

The React workspace is the product frontend and runs independently from the
Python package. Start the API first, then run:

```bash
cd frontend-react
npm install
npm run dev
```

Open http://localhost:5174. The Vite development proxy forwards `/api`,
`/health`, and `/ready` to `http://127.0.0.1:8000`. Set `VITE_API_BASE_URL`
for a separately deployed API, or configure the URL and optional API key in
the React Settings page.

React implementation goals and gates are tracked in
[`docs/react-frontend-refactor-plan.md`](docs/react-frontend-refactor-plan.md).

### Run FastAPI Backend

```bash
uvicorn backend.api.main:app --reload
```

API docs available at http://localhost:8000/docs

Set `SDM_API_KEY` in `.env` to require credentials for `/api/*` endpoints.
Clients may send `X-API-Key` or `Authorization: Bearer <key>`. Health probes
use the separate `SDM_HEALTH_PROBE_TOKEN` setting. An empty API key preserves
local access.

`SDM_API_WORKERS` (default 4) and `SDM_API_QUEUE_SIZE` (default 4) bound CPU
work. When all slots are occupied, requests receive HTTP 503 and a
`Retry-After` header. `SDM_REQUEST_TIMEOUT` returns HTTP 504 when a request
times out; running threads retain their capacity until they finish.

## 📖 Usage Examples

### Python SDK

```python
from backend.core import SQLTranspiler

transpiler = SQLTranspiler()
result = transpiler.transpile(
    sql="SELECT DATE_FORMAT(created_at, '%Y-%m-%d') FROM orders LIMIT 10",
    source="mysql",
    target="postgres"
)
print(result.target_sql)
# Output: SELECT TO_CHAR(created_at, 'YYYY-MM-DD') FROM orders LIMIT 10
```

### REST API

```bash
curl -X POST http://localhost:8000/api/convert \
  -H "Content-Type: application/json" \
  -d '{
    "sql": "SELECT * FROM users LIMIT 10",
    "source_dialect": "mysql",
    "target_dialect": "hive"
  }'
```

Successful and failed conversions return structured metadata. Failed conversions expose a stable machine-readable `error_code` alongside the human-readable `error` message.

### NL2SQL (Natural Language)

```python
from backend.core import NL2SQLGenerator

generator = NL2SQLGenerator()
result = generator.generate("查询最近7天的订单", dialect="mysql")
print(result.sql)
# Output: SELECT * FROM orders WHERE created_at >= DATE_SUB(CURRENT_DATE, 7)
```

An optional request `schema` can ground both deterministic and LLM
generation. It contains `tables` with optional `columns`, plus explicit
`relationships`. Table and column references that the deterministic parser maps
to the schema are matched case-insensitively; ambiguous mapped references and
multi-table requests without a declared relationship fail closed instead of
falling back to hardcoded table or column names. Empty column metadata means
that the table's columns are unrestricted. Natural-language column names
outside the deterministic mapping may be ignored; use `column_hints` or the
LLM path for those.
The response field `schema_used` is true when a successful deterministic or LLM
generation was validated against the supplied schema. With no schema, the
existing deterministic behavior is unchanged.

#### Optional LLM (OpenRouter)

`POST /api/nl2sql` can optionally call an OpenRouter-compatible chat-completions
service. This is disabled by default; the SDK generator and the default API
path remain deterministic. Configure only the server's untracked `.env`:

```dotenv
SDM_NL2SQL_LLM_ENABLED=true
SDM_NL2SQL_LLM_BASE_URL=https://openrouter.ai/api/v1
SDM_NL2SQL_LLM_API_KEY="your-server-side-key"
SDM_NL2SQL_LLM_MODEL="openai/gpt-4o-mini"
SDM_NL2SQL_LLM_TIMEOUT=15
SDM_NL2SQL_LLM_MAX_TOKENS=800
SDM_NL2SQL_LLM_TEMPERATURE=0.0
SDM_NL2SQL_LLM_FALLBACK=true
SDM_NL2SQL_LLM_APP_NAME="SQL Dialect Master"
SDM_NL2SQL_LLM_APP_URL=""
```

The model above is an example, not a default; enabling generation requires an
explicit model and API key. The optional app URL supplies `HTTP-Referer`, and
the app name supplies `X-Title`. Keep the key on the server: never add it to
frontend configuration, browser storage, logs, or committed files. The server
now includes `httpx` as a runtime dependency, using the existing locked version.

When enabled, natural-language text and table/column hints are sent to the
configured external provider. Do not submit sensitive content. The LLM path
accepts only one target-dialect `SELECT`/`UNION`, including read-only CTEs;
DDL, DML, `SELECT INTO`, locking queries, and stacked statements are rejected.
INSERT/UPDATE/DELETE intents continue through the deterministic generator.
Hints constrain the prompt; they are not a database schema or authorization
boundary. No SQL is executed by generation.

Responses add `provider` (`deterministic` or `llm`), `model`, and
`fallback_reason`. An accepted LLM result reports confidence `0.8` with an
`llm_generated` evidence item; the model's reasoning is never returned.
Provider errors or rejected SQL fall back to deterministic generation by
default, with a fixed reason code in `fallback_reason`. With fallback disabled,
the API returns an ordinary failed generation with a safe explanation.
The frontend labels the provider and shows a fixed fallback notice.

Target-dialect parsing and structural checks do not guarantee semantic
correctness or harmless database behavior. Review generated SQL before
executing it. See [deployment guidance](docs/deployment.md#optional-nl2sql-llm)
for egress, timeout, cost, privacy, and metrics details.

#### Relational Query Support (D2)

NL2SQL supports existential relationship queries using `EXISTS` / `NOT EXISTS` subqueries instead of physical `JOIN`s, preserving row count and avoiding duplicate expansion from 1:N relationships.

**Known relationships** (explicit mapping):
- `users ↔ orders`: `users.id = orders.user_id`
- `customers ↔ orders`: `customers.id = orders.customer_id`
- `orders ↔ products`: `orders.product_id = products.id`
- `employees ↔ departments`: `employees.dept_id = departments.id`

**Examples:**
```python
# Positive relational query → EXISTS
result = generator.generate("find users who have orders", "postgres")
# Output: SELECT * FROM users WHERE EXISTS (SELECT 1 FROM orders WHERE users.id = orders.user_id)

# Negative relational query → NOT EXISTS
result = generator.generate("find users without orders", "postgres")
# Output: SELECT * FROM users WHERE NOT EXISTS (SELECT 1 FROM orders WHERE users.id = orders.user_id)
```

**Unknown relationships fail safely:**
```python
result = generator.generate("find users who have invoices", "postgres")
# Output: success=False, explanation="Unable to safely infer the relationship..."
```

Relationship inference uses explicit mapping only — no fabricated foreign keys. Use `table_hint` to specify schema-qualified tables when needed.

#### Date Arithmetic Semantics (D3)

Date expressions follow a **rolling vs calendar-relative** distinction:

| Expression | Semantic | DSL (postgres) |
|------------|----------|----------------|
| `today` | current calendar date | `= CURRENT_DATE` |
| `yesterday` | rolling -1 day | `= DATE_SUB(CURRENT_DATE, 1)` |
| `tomorrow` | rolling +1 day | `= DATE_ADD(CURRENT_DATE, 1)` |
| `last N days` | rolling N days | `>= DATE_SUB(CURRENT_DATE, N)` |
| `last N weeks` | rolling N×7 days | `>= DATE_SUB(CURRENT_DATE, N×7)` |
| `last week` | rolling 7 days | `>= DATE_SUB(CURRENT_DATE, 7)` |
| `last N months` | calendar -N months | `>= ADD_MONTHS(CURRENT_DATE, -N)` |
| `last month` | calendar -1 month | `>= ADD_MONTHS(CURRENT_DATE, -1)` |
| `last N years` | calendar -N years | `>= ADD_MONTHS(CURRENT_DATE, -N×12)` |
| `last year` | calendar -1 year | `>= ADD_MONTHS(CURRENT_DATE, -12)` |

**Key distinction:** `last week` uses a rolling 7-day window, while `last month`/`last year` use calendar arithmetic (`ADD_MONTHS`). This means `last month` from March 31 yields February 28/29 (not 30 days prior), and `last year` preserves month/day within the calendar.

Date conditions in combined queries (e.g., "users who have orders from last 7 days") are scoped to the relation table's date column inside the `EXISTS` subquery.

#### Type Mapping with Precision (D1)

TypeMapper now supports parameterized types and precision-aware warnings:

```python
from backend.core import TypeMapper

mapper = TypeMapper()
result = mapper.map_type("VARCHAR2(2000)", "oracle", "postgres")
# Output: source_type="VARCHAR2(n)", target_type="VARCHAR(n)", precision=2000

result = mapper.map_type("VARCHAR2(8000)", "oracle", "postgres")
# Output: warnings include "exceeds Oracle's default VARCHAR2 limit of 4000"
```

Supports `VARCHAR`, `VARCHAR2`, `NVARCHAR`, `CHAR` with numeric precision or `MAX`. Unknown parameterized types resolve to the canonical base type.

## 🏗️ Project Structure

```
sql-dialect-master/
├── backend/
│   ├── api/
│   │   ├── main.py              # FastAPI application
│   │   └── middleware.py        # Rate limiting, logging
│   ├── benchmarks/
│   │   └── transpiler_benchmark.py # Reproducible conversion benchmark
│   ├── core/
│   │   ├── nl2sql_components/   # Modular NL2SQL components
│   │   │   ├── tokenizer.py     # Language tokenization
│   │   │   ├── templates.py     # Query templates
│   │   │   └── mappings.py      # Language mappings
│   │   ├── config.py            # Configuration management
│   │   ├── transpiler.py        # SQL conversion engine
│   │   ├── parser.py            # SQL parser
│   │   ├── semantic_diff.py     # AST-based semantic difference detector
│   │   ├── rules.py             # Transformation rules
│   │   ├── post_processor.py    # Post-processing
│   │   ├── nl2sql.py            # Natural language to SQL
│   │   ├── functions_lookup.py  # Function encyclopedia
│   │   ├── functions_db.json    # Functions database
│   │   ├── type_mapping.py      # Type mapping
│   │   ├── type_mapping.json    # Types database
│   │   ├── cache.py             # TTL cache
│   │   └── exceptions.py        # Custom exceptions + ErrorCode taxonomy
│   ├── utils/
│   │   └── validators.py        # Input validation
│   │
│   └── tests/                   # Test suite and regression coverage
├── examples/
│   ├── api_client.py             # API usage examples
│   └── basic_usage.py            # SDK usage examples
├── scripts/
│   └── verify_readme_consistency.py # README source-of-truth checks
├── frontend-react/              # React + TypeScript product frontend
│   ├── src/
│   ├── package.json
│   └── vite.config.ts
├── pyproject.toml               # Project configuration
├── .env.example                 # Environment template
├── LICENSE                      # MIT License
└── README.md
```

## 🔧 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/convert` | POST | Convert SQL between dialects; response includes `error_code` on failure |
| `/api/convert/batch` | POST | Convert an ordered batch with one dialect pair and per-item results |
| `/api/parse` | POST | Parse SQL and extract structural elements |
| `/api/nl2sql` | POST | Generate SQL from natural language |
| `/api/functions` | GET | Search SQL functions |
| `/api/functions/{name}` | GET | Get function details |
| `/api/types` | GET | Get type mapping matrix |
| `/api/types/map` | POST | Map type between dialects |
| `/api/dialects` | GET | List supported dialects |
| `/health` | GET | Health check |
| `/health/deep` | GET | Deep health check |
| `/api/stats` | GET | Service and dataset statistics |

For example, send this JSON body to `POST /api/convert/batch`:

```json
{
  "statements": ["SELECT id FROM users", "SELECT user_id FROM orders"],
  "source_dialect": "postgres",
  "target_dialect": "mysql",
  "pretty": true
}
```

Results retain input order and include a zero-based `index` alongside the
single-conversion response fields. The summary includes `count`, `succeeded`,
and `failed`; top-level `success` is true only when every item succeeds.
Ordinary item failures, including a batch where every item fails, return HTTP
200 with per-item `error` and `error_code`. Request-level errors use the
existing error envelope; 503/504 responses do not include partial results.

## 🧪 Quality, Validation & Performance

The project maintains a 12 × 12 source-to-target dialect regression matrix, semantic regression tests, post-processing safety regressions, security boundary checks, deterministic rule-engine tests, cache-versioning tests, async concurrency tests, and stable error-code tests.

Converted SQL is validated after post-processing. Target-dialect parsing is preferred; when a target parser limitation prevents validation but the generic parser accepts the SQL, the result is retained with a compatibility warning. Only when both validations fail is the conversion reported as unsuccessful.

The AST semantic diff utility canonicalizes source and target SQL through SQLGlot and reports structural changes such as different predicates or AST node shapes. It is a regression detector rather than a proof of runtime equivalence.

The semantic CI gate executes representative conversions against PostgreSQL and DuckDB and compares the source and converted result sets. This provides runtime evidence for supported SQL subsets without claiming universal cross-database semantic equivalence.

Security validation structurally detects stacked SQL statements using the parser when available, with configurable policy controlling whether dangerous input is blocked or only warned about.

The SDK's `batch_transpile_async` bounds concurrent work and preserves input
order. REST batch conversion runs sequentially in one API worker slot, and the
entire batch shares the default 30-second queue-plus-execution budget
(`SDM_REQUEST_TIMEOUT`). HTTP 504 does not cancel the background batch. See
the [deployment limits](docs/deployment.md#1-deployment-model) for capacity
and timeout behavior.

A reproducible transpiler benchmark is available under `backend/benchmarks/` and is also executed in CI for performance observability. The benchmark intentionally reports measurements without failing the build on a fixed latency threshold because hosted CI timing is variable.

README source-of-truth checks run in CI and verify the release version, Python requirement, supported dialect list, and benchmark references against repository sources.

To run the benchmark locally:

```bash
python backend/benchmarks/transpiler_benchmark.py --iterations 100 --repeats 3
```

To validate README consistency locally:

```bash
python scripts/verify_readme_consistency.py
```

## ⚠️ Limitations

SQL dialect conversion is not universally semantics-preserving. The engine validates generated SQL against the target parser, but parser acceptance does not prove equivalent runtime behavior. Database-specific differences in NULL handling, implicit casts, date/time semantics, collation, timezone behavior, JSON/array operations, and other vendor features may require manual review or execution against the target database.

NL2SQL defaults to heuristic/template-driven generation, with an optional
server-side LLM path for read-only queries. Neither path provides a calibrated
probability: the returned confidence is a generation-quality signal, not the
statistical probability that the SQL is correct.

## ⚙️ Configuration

The project uses `pydantic-settings` for robust configuration.

Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
```

Key settings (prefixed with `SDM_`):
- `SDM_CACHE_ENABLED` - Enable/disable caching

### Rate limiting deployment

Rate limiting is on by default. The two backends are:

- `SDM_RATE_LIMIT_BACKEND=memory` (default) — per-process, thread-safe. Limits are **per instance**, not shared. Run this only when the API is served by a single process; in a multi-worker or multi-instance deployment each worker enforces its own limit, so the effective ceiling is `workers × SDM_RATE_LIMIT_REQUESTS`.
- `SDM_RATE_LIMIT_BACKEND=redis` — shared, atomic limits across all workers. Set `SDM_REDIS_URL` when using this backend. The store connects and pings Redis at startup and fails fast if it is unreachable; the `redis` package is required (install with `pip install redis`).

`SDM_RATE_LIMIT_ENABLED=false` disables enforcement entirely. Use the in-memory backend for local development and the Redis backend for any deployment with more than one worker or instance that must enforce a single global limit.

By default, the API does not trust `X-Forwarded-For`; rate limiting and logs
use the direct peer address. Set `SDM_TRUSTED_PROXIES` to the proxy IPs/CIDRs
only when the direct peer is a trusted proxy, after which the rightmost
non-trusted address in the XFF chain is used. Deployments behind a proxy must
also configure `SDM_HEALTH_PROBE_TOKEN` for readiness probes; readiness never
uses XFF for authorization.

SQL-bearing POST responses and health probes use `Cache-Control: no-store`;
public catalog responses use short `private` caching. Full deployment details
will be documented in `docs/deployment.md`.

See [`docs/deployment.md`](docs/deployment.md) for production deployment guidance.
Metrics configuration and scraping guidance are documented in the same guide.
