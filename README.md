# 🔄 SQL Dialect Master

Enterprise-grade multi-database SQL conversion engine supporting 12 database dialects.

Current release: 1.0.1

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.38+-red.svg)](https://streamlit.io/)

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔄 **SQL Conversion** | Convert SQL between 12 database dialects with a complete 12 × 12 conversion matrix |
| ✅ **Output Validation** | Validate converted SQL with target-dialect parsing plus safe generic-parser fallback |
| 🧠 **Semantic Regression Coverage** | Preserve predicates, joins, grouping, ordering, limits, windows, and round-trip validity |
| 🔍 **AST Semantic Diff** | Compare dialect-aware SQL ASTs to detect structural changes introduced by conversion |
| 🗄️ **Runtime Semantic Tests** | Execute representative conversions against PostgreSQL and DuckDB and compare result sets |
| 📚 **Function Encyclopedia** | 298 SQL functions with cross-database comparison |
| 🗂️ **Type Mapping** | 36 data types × 12 databases matrix |
| 💬 **NL2SQL** | Natural language to SQL (Chinese/English) |
| 🔧 **Rule Engine** | Deterministic priority ordering, compiled patterns, dialect-aware conflict detection |
| 🛡️ **Security Validation** | Statement-level stacked-query detection with configurable blocking policy |
| ⚡ **Performance** | Rule-aware cache versioning, bounded async batch conversion, and reproducible benchmark |
| 🎨 **Modern UI** | Streamlit interface with 5 themes + Custom Theme Editor |

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

For development and testing, install the optional development dependencies:

```bash
python -m pip install -e ".[dev]"
```

For database-backed semantic tests:

```bash
python -m pip install -e ".[dev,semantic]"
```

### Run Streamlit UI (Recommended)

```bash
streamlit run sdm_local.py
```

Open http://localhost:8501 in your browser.

### Run FastAPI Backend

```bash
uvicorn backend.api.main:app --reload
```

API docs available at http://localhost:8000/docs

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
├── frontend/                    # Streamlit UI Components
│   ├── tabs/                    # Modular Tab Pages
│   │   ├── convert.py
│   │   ├── functions.py
│   │   ├── types.py
│   │   ├── nl2sql.py
│   │   ├── explain.py
│   │   └── lineage.py
│   ├── app_context.py           # Shared Application Context
│   ├── components.py            # Reusable UI Widgets
│   ├── themes.py                # Visual Themes
│   └── templates.py             # SQL Templates
├── examples/
│   ├── api_client.py             # API usage examples
│   └── basic_usage.py            # SDK usage examples
├── scripts/
│   └── verify_readme_consistency.py # README source-of-truth checks
├── sdm_local.py                 # Streamlit Application Entry
├── pyproject.toml               # Project configuration
├── requirements.txt              # Legacy/runtime dependency list
├── .env.example                 # Environment template
├── LICENSE                      # MIT License
└── README.md
```

## 🔧 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/convert` | POST | Convert SQL between dialects; response includes `error_code` on failure |
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

## 🧪 Quality, Validation & Performance

The project maintains a 12 × 12 source-to-target dialect regression matrix, semantic regression tests, post-processing safety regressions, security boundary checks, deterministic rule-engine tests, cache-versioning tests, async concurrency tests, and stable error-code tests.

Converted SQL is validated after post-processing. Target-dialect parsing is preferred; when a target parser limitation prevents validation but the generic parser accepts the SQL, the result is retained with a compatibility warning. Only when both validations fail is the conversion reported as unsuccessful.

The AST semantic diff utility canonicalizes source and target SQL through SQLGlot and reports structural changes such as different predicates or AST node shapes. It is a regression detector rather than a proof of runtime equivalence.

The semantic CI gate executes representative conversions against PostgreSQL and DuckDB and compares the source and converted result sets. This provides runtime evidence for supported SQL subsets without claiming universal cross-database semantic equivalence.

Security validation structurally detects stacked SQL statements using the parser when available, with configurable policy controlling whether dangerous input is blocked or only warned about.

The async batch API bounds concurrent work and preserves input order. A reproducible transpiler benchmark is available under `backend/benchmarks/` and is also executed in CI for performance observability. The benchmark intentionally reports measurements without failing the build on a fixed latency threshold because hosted CI timing is variable.

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

NL2SQL is heuristic/template-driven rather than a calibrated probabilistic model. The returned confidence score should be treated as a generation-quality signal, not as a statistical probability that the SQL is correct.

## ⚙️ Configuration

The project uses `pydantic-settings` for robust configuration.

Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
```

Key settings (prefixed with `SDM_`):
- `SDM_CACHE_ENABLED` - Enable/disable caching
