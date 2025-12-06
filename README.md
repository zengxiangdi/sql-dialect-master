# 🔄 SQL Dialect Master

Enterprise-grade multi-database SQL conversion engine supporting 12 database dialects.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.38+-red.svg)](https://streamlit.io/)

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔄 **SQL Conversion** | Convert SQL between 12 database dialects |
| 📚 **Function Encyclopedia** | 50+ SQL functions with cross-database comparison |
| 🗂️ **Type Mapping** | 36 data types × 12 databases matrix |
| 💬 **NL2SQL** | Natural language to SQL (Chinese/English) |
| 🔧 **40+ Rules** | Intelligent transformation rules |
| 🎨 **Modern UI** | Beautiful Streamlit interface with 5 themes |

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
git clone https://github.com/YOUR_USERNAME/sql-dialect-master.git
cd sql-dialect-master

# Install dependencies
pip install -r requirements.txt
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
│   ├── core/
│   │   ├── config.py            # Configuration management
│   │   ├── transpiler.py        # SQL conversion engine
│   │   ├── parser.py            # SQL parser
│   │   ├── rules.py             # Transformation rules
│   │   ├── post_processor.py    # Post-processing
│   │   ├── nl2sql.py            # Natural language to SQL
│   │   ├── functions_lookup.py  # Function encyclopedia
│   │   ├── functions_db.json    # Functions database
│   │   ├── type_mapping.py      # Type mapping
│   │   ├── type_mapping.json    # Types database
│   │   ├── cache.py             # TTL cache
│   │   └── exceptions.py        # Custom exceptions
│   ├── utils/
│   │   └── validators.py        # Input validation
│   └── tests/                   # Test suite
├── examples/
│   ├── api_client.py            # API usage examples
│   └── basic_usage.py           # SDK usage examples
├── sdm_local.py                 # Streamlit UI
├── pyproject.toml               # Project configuration
├── requirements.txt             # Dependencies
├── .env.example                 # Environment template
├── LICENSE                      # MIT License
└── README.md
```

## 🔧 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/convert` | POST | Convert SQL between dialects |
| `/api/nl2sql` | POST | Generate SQL from natural language |
| `/api/functions` | GET | Search SQL functions |
| `/api/functions/{name}` | GET | Get function details |
| `/api/types` | GET | Get type mapping matrix |
| `/api/types/map` | POST | Map type between dialects |
| `/api/dialects` | GET | List supported dialects |
| `/health` | GET | Health check |
| `/health/deep` | GET | Deep health check |

## 🎨 Themes

The Streamlit UI supports 5 beautiful themes:
- 🌙 Dark
- ☀️ Light  
- 🌊 Ocean (default)
- 🌸 Sakura
- 🌲 Forest

## ⚙️ Configuration

Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
```

Key settings:
- `SDM_CACHE_ENABLED` - Enable/disable caching
- `SDM_CACHE_TTL` - Cache time-to-live (seconds)
- `SDM_RATE_LIMIT_REQUESTS` - Rate limit per window
- `SDM_LOG_LEVEL` - Logging level

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=backend
```

## 📄 License

MIT License - see [LICENSE](LICENSE) file.

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📬 Contact

- Issues: [GitHub Issues](https://github.com/YOUR_USERNAME/sql-dialect-master/issues)

---

Made with ❤️ using [sqlglot](https://github.com/tobymao/sqlglot), [FastAPI](https://fastapi.tiangolo.com/), and [Streamlit](https://streamlit.io/)
