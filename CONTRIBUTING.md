# Contributing to SQL Dialect Master

Thank you for your interest in contributing to SQL Dialect Master! We welcome contributions from the community to make SQL conversion easier and more robust.

## 🛠️ Development Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/YOUR_USERNAME/sql-dialect-master.git
   cd sql-dialect-master
   ```

2. **Create the project virtual environment**
   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # Linux/Mac
   source .venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   # Includes tests, Ruff, Bandit, dependency audit, build, and Twine.
   .venv/bin/python -m pip install -e ".[dev,qa,semantic]"

   # CI's reproducible locked runtime/test environment remains available:
   .venv/bin/python -m pip install -r requirements-lock.txt
   .venv/bin/python -m pip install -e . --no-deps
   ```

## 🏗️ Project Architecture

- **Backend**: Uses FastAPI and `sqlglot`.
  - `backend/core`: Contains the business logic (Transpiler, NL2SQL, Rules).
  - `backend/api`: REST API endpoints.
- **Frontend**: Built with Streamlit.
  - `sdm_local_v2.py`: Entry point (Frontend v2 architecture).
  - `frontend/pages/`: One module per workspace page.
  - `frontend/ui/`: Reusable UI components (status, editor, diff, command palette).
  - `frontend/core/`: Design tokens, themes, navigation, state, view models, escaping.
  - `frontend/app_context_v2.py`: Data access and dialect labels for pages.

## 🧪 Running Tests

We use `pytest` for testing. Please ensure all tests pass before submitting a PR.

```bash
# Run all tests
.venv/bin/python -m pytest

# Run specific test file
.venv/bin/python -m pytest backend/tests/test_api.py

# Check test coverage
.venv/bin/python -m pytest --cov=backend
```

## 📝 Coding Guidelines

- **Style**: We follow PEP 8. Please run `.venv/bin/ruff check backend/core backend/api frontend sdm_local_v2.py --select E9,F --ignore F401` before committing.
- **Type Hints**: Use Python type hints for function arguments and return values.
- **Documentation**: Add docstrings to modules, classes, and functions (Google style).
- **Modularity**: Keep components small and focused (e.g., separate UI logic into `frontend/ui`).

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
