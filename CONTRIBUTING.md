# Contributing to SQL Dialect Master

Thank you for your interest in contributing to SQL Dialect Master! We welcome contributions from the community to make SQL conversion easier and more robust.

## 🛠️ Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/YOUR_USERNAME/sql-dialect-master.git
   cd sql-dialect-master
   ```

2. **Create a virtual environment (Recommended)**
   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # Linux/Mac
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   # Install project documentation
   pip install -r requirements.txt
   
   # Install test dependencies
   pip install pytest pytest-cov black isort
   ```

## 🏗️ Project Architecture

- **Backend**: Uses FastAPI and `sqlglot`.
  - `backend/core`: Contains the business logic (Transpiler, NL2SQL, Rules).
  - `backend/api`: REST API endpoints.
- **Frontend**: Built with Streamlit.
  - `sdm_local.py`: Entry point.
  - `frontend/tabs`: Modular logic for each UI tab.
  - `frontend/components.py`: Reusable UI widgets.

## 🧪 Running Tests

We use `pytest` for testing. Please ensure all tests pass before submitting a PR.

```bash
# Run all tests
pytest

# Run specific test file
pytest backend/tests/test_api.py

# Check test coverage
pytest --cov=backend
```

## 📝 Coding Guidelines

- **Style**: We follow PEP 8. Please run `black .` and `isort .` before committing.
- **Type Hints**: Use Python type hints for function arguments and return values.
- **Documentation**: Add docstrings to modules, classes, and functions (Google style).
- **Modularity**: Keep components small and focused (e.g., separate UI logic into `frontend/tabs`).

## 🚀 Adding New Features

### Adding a New SQL Dialect
1. Check if `sqlglot` supports the dialect.
2. Update `SUPPORTED_DIALECTS` in `backend/core/config.py`.
3. Update `type_mapping.json` with dialect specific types.
4. Update `functions_db.json` with dialect specific function syntax.

### Modifying NL2SQL
The NL2SQL module is located in `backend/core/nl2sql_components`.
- `templates.py`: Add new SQL generation templates.
- `mappings.py`: Add new keywords or table mappings.
- `tokenizer.py`: Update tokenization logic.

## 🤝 Pull Request Process

1. Create a clean branch from `main`: `git checkout -b feature/your-feature-name`.
2. Commit your changes with clear messages.
3. Push to your fork and submit a Pull Request.
4. Describe your changes and link to any relevant issues.

## 🐛 Reporting Issues

If you find a bug, please create an issue with:
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Python version)
