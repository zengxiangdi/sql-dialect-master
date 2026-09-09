# Semantic Risk Register

**Baseline commit:** `3f0bbd87e7c7d8ede8c72eb8b1604593c2f0c162`  
**Audit branch:** `audit/architecture-baseline`  
**Method:** source inspection of conversion/NL2SQL/parser/diff/rule/test/CI layers.  
**Policy:** no semantic risk is considered resolved merely because output parses.

## Severity model

- **P0:** high probability of semantic corruption or silent wrong-result SQL on common workloads; blocks semantic release confidence.
- **P1:** architecture/testability risk that can cause or conceal semantic regressions, but is not itself proven to corrupt a common query class.
- **P2:** maintainability, observability or performance debt without an immediate correctness impact.

## P0 semantic risks

| ID | Area | Risk | Likely failure mode | Required evidence |
|---|---|---|---|---|
| S-001 | NL2SQL dates | Generic `DATE_SUB(CURRENT_DATE, n)` template plus target-specific text rewrites do not establish semantics for every target dialect. | Target SQL is accepted but date arithmetic or interval typing differs. | Dialect-specific golden cases + target parser + runtime where available. |
| S-002 | NL2SQL date rewrites | Multiple hardening modules redefine `_apply_dialect_adjustments`, including an implementation using raw `str.replace`/regex. | `CURRENT_DATE` or related text inside strings/comments can be rewritten; effective behavior depends on import order. | Literal/comment/string tests and import-order test. |
| S-003 | ROWNUM/TOP/LIMIT | Row limiting constructs are not universally equivalent. ROWNUM filtering interacts with predicate/order shape; TOP can include dialect-specific options. | Different rows returned, especially with ordering, subqueries or additional predicates. | Semantic corpus for ordered/unordered cases; runtime evidence for supported DB pairs. |
| S-004 | Aggregate rewrites | `GROUP_CONCAT`, `LISTAGG`, array aggregation and related conversions can lose order, NULL behavior, DISTINCT semantics or output typing. | Same syntax shape but different aggregate result. | Aggregate matrix with order, DISTINCT, NULL, empty-group cases. |
| S-005 | NULL semantics | Function and predicate rewrites can confuse `IS NULL` predicates, two-argument null functions and type-dependent NULL behavior. | Different three-valued-logic result or coercion. | Truth-table fixtures and runtime checks. |
| S-006 | Boolean precedence | Text/template transformations can alter grouping when `AND`/`OR` are combined. | Rows are included/excluded differently without a parse failure. | AST-based predicate comparison + runtime truth-table cases. |
| S-007 | DML generation | INSERT/UPDATE/DELETE are less covered by the current semantic-runtime suite than SELECT aggregation. | Mutation affects different rows/columns or changes target behavior. | DML golden tests + runtime transaction-isolated fixtures. |

## P1 semantic/validation risks

| ID | Area | Risk | Why it matters |
|---|---|---|---|
| S-008 | Semantic diff | Current equality requires identical canonical SQL and identical AST node-type counts. | Semantically equivalent cross-dialect rewrites can be reported as different, while classifications beyond `equivalent=False` are unavailable. |
| S-009 | Semantic diff | No distinction between `equivalent`, `structurally different but equivalent`, `potentially different`, and `definitely different`. | Callers cannot make policy decisions from the result. |
| S-010 | Semantic diff | No first-class category/severity/source-fragment/target-fragment/explanation fields. | Reviewers cannot quickly understand whether a difference is harmless formatting or a dangerous semantic change. |
| S-011 | Parser metadata | Function metadata sets `is_window` to `False` even when window expressions exist. | Downstream semantic analysis can undercount or misclassify window functions. |
| S-012 | Type mapping | `map_type` falls back to partial substring matching and selects the first matching entry. | Ambiguous or parameterized type names can silently map to the wrong canonical type. |
| S-013 | Function encyclopedia | Direct function lookup is exact-name based; aliases/normalized aliases and ambiguity policy are not first-class. | Unsupported or renamed functions can fail as a lookup miss or be handled inconsistently elsewhere. |
| S-014 | RuleEngine | Many rules use regexes that do not model nested parentheses. | Nested function arguments can be truncated or incorrectly matched. |
| S-015 | Rewrite boundaries | Scanner protection exists but is not universal across all compatibility layers. | A new rule can regress string/comment/identifier safety. |
| S-016 | Evidence hierarchy | Target parse acceptance is still used as a practical gate even when semantic equivalence is unknown. | False confidence in conversion correctness. |

## P2 semantic debt

| ID | Area | Risk |
|---|---|---|
| S-017 | Duplicate scanner | `audit_hardening.py` duplicates scanner behavior that already exists in `p1_sql_scanner.py`. |
| S-018 | Compatibility layers | Method monkey-patching makes semantic ownership non-local. |
| S-019 | Test organization | Semantic tests are fragmented across many top-level test files rather than a dedicated corpus/matrix structure. |
| S-020 | Corpus | There is no checked-in declarative Golden Corpus format containing semantic expectations and warning policies. |
| S-021 | Runtime breadth | Runtime semantic evidence is concentrated on PostgreSQL/DuckDB and one main aggregation scenario. |

## Dialect-specific review priorities

### PostgreSQL
Inspect interval/date arithmetic, `NULL`, casts, arrays/JSON and ordered aggregates.

### MySQL
Inspect `DATE_FORMAT`, `GROUP_CONCAT`, NULL functions, implicit coercion and LIMIT semantics.

### Oracle
Inspect `TRUNC`, `ADD_MONTHS`, `ROWNUM`, `FETCH`, empty-string/NULL behavior, `DECODE` and date types.

### T-SQL
Inspect `TOP`, `DATEADD`, `ISNULL`, `OFFSET/FETCH`, implicit conversions and window ordering.

### DuckDB
Use as a practical runtime oracle for portable analytical SQL, but do not treat it as proof of another engine's semantics.

### Hive / Spark / Trino / Databricks
Inspect array aggregations, distributed-engine-specific functions, interval syntax, collection functions and ordering guarantees.

### Snowflake / Redshift / ClickHouse
Prioritize type coercion, date functions, aggregation behavior and engine-specific function availability before claiming equivalence.

## Hard semantic invariants for PR 2

1. SQL literals, quoted identifiers and comments are immutable under rewrites.
2. Parenthesis depth is preserved unless the transformation explicitly changes expression structure.
3. Boolean precedence must be represented structurally, not inferred from string order.
4. A top-N conversion must retain an equivalent ordering contract before claiming equivalence.
5. Aggregate conversions must declare behavior for NULL, empty input, DISTINCT and ordering.
6. Unknown or ambiguous dialect constructs must return explicit warnings/errors rather than silently guessing.
7. Every semantic bug fixed becomes a permanent regression case.
