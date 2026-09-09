# Architecture Audit

**Baseline commit:** `3f0bbd87e7c7d8ede8c72eb8b1604593c2f0c162`  
**Audit branch:** `audit/architecture-baseline`  
**Scope:** architecture, semantic pipeline, package topology, validation boundaries, production/API, CI and release path.  
**Status:** audit only; no production implementation changes are included in PR 1.

## 1. Executive assessment

The repository has a substantial hardening foundation: 12 configured dialects, parser/transpiler/post-processing layers, quote/comment-aware scanners, security validation, runtime data validation, a 144-pair basic dialect matrix, PostgreSQL/DuckDB runtime evidence, pinned GitHub Actions, locked dependencies, wheel validation, and dedicated API/readiness tests.

The main architectural risk has now shifted from missing safeguards to **semantic behavior being distributed across multiple compatibility/patch layers**. The conversion pipeline is therefore difficult to reason about as a compiler: the same conceptual rewrite can be defined in `rules.py`, overridden by `audit_hardening.py`, overridden again by `final_hardening.py`, and supplemented by `post_processor.py`.

The most important architectural finding is that the repository has both a good scanner/structured-transformation foundation and a legacy global-regex rule model. The next work should consolidate these rather than add another compatibility layer.

## 2. Current architecture

```text
                       +-----------------------+
                       |   FastAPI / Streamlit |
                       +-----------+-----------+
                                   |
                           boundary validation
                                   |
                 +-----------------+-----------------+
                 |                                   |
              SQL input                          NL input
                 |                                   |
          +------+-------+                    +------+-------+
          | SQLTranspiler|                    |   NL2SQL     |
          +------+-------+                    +------+-------+
                 |                                   |
          sqlglot parse/transpile             templates / extraction
                 |                                   |
          +------+-------+                    dialect adjustments
          | PostProcessor|                           |
          +------+-------+                           |
                 |                          +--------+---------+
          RuleEngine + custom               | generated SQL   |
          transformations                   +--------+---------+
                 |                                    |
                 +----------------+-------------------+
                                  |
                           target SQL validation
                                  |
                    +-------------+--------------+
                    |                            |
              parser/AST evidence          runtime evidence
                    |                            |
              semantic diff                 DB execution
```

### Architectural observations

1. `SQLTranspiler` owns orchestration, security checks, caching, output validation, warnings and batch execution.
2. `PostProcessor` applies declarative rules followed by custom semantic rewrites.
3. `p1_sql_scanner.py` and `function_call_scanner.py` provide the correct direction for lexical safety and nested-call handling.
4. `parser.py` exposes an AST-oriented analysis API, but its metadata model is still shallow for compiler-grade semantic comparison.
5. `semantic_diff.py` is currently a structural regression detector, not a complete semantic equivalence engine.
6. `audit_hardening.py` and `final_hardening.py` monkey-patch runtime classes instead of expressing final behavior in the owning modules.

## 3. Architectural strengths

### Strong validation boundary
The transpiler rejects multiple statements and validates target SQL after conversion. CI also exercises all configured dialect pairs at the parser-validity level.

### Strong lexical safety primitives
The scanner explicitly separates executable regions from literals, quoted identifiers and comments, including PostgreSQL dollar quoting and Oracle `q'...'` syntax. This is reusable compiler infrastructure and should become the mandatory boundary for remaining rewrites.

### Strong packaging discipline
The build configuration packages `backend*` and `frontend*`, excludes tests and benchmarks from distributions, and includes the JSON runtime data under `backend.core`.

### Strong CI/release groundwork
The CI workflow uses Python 3.11/3.12, runs the full suite, compiles sources, builds and inspects a wheel, smoke-tests installed runtime data, and has a dedicated PostgreSQL semantic-runtime gate. GitHub Actions are pinned by commit SHA.

## 4. Major architectural risks

### A1 — Multiple runtime monkey-patch layers (P0/P1 boundary)

`audit_hardening.py` captures original methods and then assigns replacements onto `SQLTranspiler`, `PostProcessor`, `TransformRule` and `NL2SQLGenerator`. `final_hardening.py` then applies another set of replacements. This creates import-order and initialization-order coupling and makes the effective class implementation non-local.

**Impact:** a code reviewer cannot inspect one owning module and know the effective semantics. Fixes can be accidentally shadowed by later compatibility imports.

**Required direction:** fold stable behavior into the owning implementation, keep compatibility shims only where a public API needs them, and remove duplicate monkey patches after regression coverage exists.

### A2 — Declarative RuleEngine still permits whole-SQL regex substitution

`TransformRule.apply()` performs regex substitution against the entire SQL string. Some rules use patterns such as `([^\)]+)` or `([^,]+)` which cannot model arbitrary nested expressions.

**Impact:** transformations can cross semantic boundaries even when the current scanner-backed compatibility path protects selected legacy handlers.

**Required direction:** executable-region scanning first, then structured function/operator matching. Regex should be limited to lexical/token patterns whose grammar is explicitly bounded.

### A3 — Semantic policy is split between sqlglot, RuleEngine and ad-hoc post-processing

There is no single intermediate representation or semantic contract that says which transformation is syntax-only, which is structurally equivalent, and which requires an explicit warning.

**Impact:** syntax-valid output can still be semantically wrong.

**Required direction:** introduce a transformation classification and semantic evidence model before adding broad new rules.

### A4 — NL2SQL dialect adjustment remains string-rewrite based

NL2SQL initially generates common expressions such as `DATE_SUB(CURRENT_DATE, n)` and later applies target-dialect substitutions. The existence of multiple patches means dialect policy is not centralized in the SQL AST/generator layer.

**Impact:** one template can be syntactically accepted in one target and semantically wrong in another, especially around dates, intervals and top-N behavior.

**Required direction:** generate a dialect-neutral structured representation first, then render target-specific SQL; reserve textual rewrites for narrowly proven lexical cases.

### A5 — Import/package topology is inconsistent

`backend/api/main.py` mutates `sys.path` and then imports `core.*`, while other imports use `backend.*`. The package is configured as `backend*` and `frontend*`, so the path hack is not conceptually part of the packaging model.

**Impact:** duplicate module identities such as `core.config` vs `backend.core.config` can create singleton/config/class identity surprises when different entrypoints import modules through different names.

**Required direction:** standardize absolute imports on `backend.*` / `frontend.*` and remove runtime path mutation. Validate all supported entrypoints after migration.

### A6 — Scanner logic is duplicated

`audit_hardening.py` contains its own segment scanner while `p1_sql_scanner.py` is the intended shared scanner primitive.

**Impact:** fixes to quoting/comment semantics can diverge between implementations.

**Required direction:** make one scanner authoritative and delete the duplicate implementation once coverage is sufficient.

## 5. API / production architecture observations

The API stack already has CORS, security headers, rate limiting, structured logging, readiness/deep-health support, normalized dialect validation and centralized settings. This is a solid base.

The next concern is less about adding middleware and more about ensuring lifecycle semantics are explicit: startup initialization, multi-worker behavior, shared probe state, dependency probe concurrency, request timeouts and proxy/header handling should have a single ownership model. Avoid depending on framework-private attributes.

## 6. Compiler architecture target

The desired end-state is:

```text
Raw input
  -> lexical boundary analysis
  -> dialect parse / NL semantic model
  -> normalized IR / AST
  -> semantic transformation passes
  -> target dialect renderer
  -> target parse
  -> structural semantic checks
  -> optional runtime evidence
  -> result + warnings + provenance
```

Each transformation should declare:

- source dialect / target dialect
- input node or construct
- semantic preconditions
- output construct
- confidence/evidence class
- warning policy
- regression tests

## 7. Architecture decision

PR 1 should not refactor the runtime. It establishes the baseline and creates the evidence required for the next PRs. PR 2 should fix the highest-confidence NL2SQL semantic bugs. PR 3/4 then make those fixes regression-resistant. Only after that should PR 5 consolidate RuleEngine semantics.

## 8. Release blockers from architecture alone

- Any known semantic rewrite that can silently produce a different query result.
- Import topology that depends on `sys.path` mutation.
- Multiple competing monkey-patch implementations of the same method.
- A semantic-diff result being interpreted as proof of runtime equivalence.
- Silent fallback from unknown/ambiguous type or function mapping.
