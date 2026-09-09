# Test Gap Report

**Baseline commit:** `3f0bbd87e7c7d8ede8c72eb8b1604593c2f0c162`  
**Audit branch:** `audit/architecture-baseline`  
**Status:** inventory and gap analysis only; PR 1 does not alter test expectations or implementation.

## 1. Current test inventory

The repository already contains broad test families for API behavior, hardening, boolean semantics, cache, scanner safety, dialect conversion, NL2SQL semantics, parser fallback, post-processing, properties, runtime semantics, semantic diff, security statement boundaries, readiness and rate limiting.

The current repository therefore has good breadth but the semantic tests are **fragmented** rather than organized around a single source-of-truth corpus.

## 2. Existing matrix coverage

`backend/tests/test_dialect_matrix.py` constructs:

```python
[(source, target) for source in SUPPORTED_DIALECTS for target in SUPPORTED_DIALECTS]
```

and therefore covers 12 × 12 = **144 conversion pairs** for one dialect-neutral SELECT. The test asserts conversion success and target parser acceptance. It explicitly documents that this is **not a semantic-equivalence claim**.

Coverage classification:

| Metric | Current state | Assessment |
|---|---:|---|
| Configured dialects | 12 | Good source of truth |
| Basic source→target pairs | 144 / 144 | Good syntax gate |
| Feature-level semantic matrix | Not established | Major gap |
| Golden semantic corpus | Not established | Major gap |
| AST semantic equivalence | Partial utility only | Major gap |
| Runtime evidence | PostgreSQL ↔ DuckDB | Narrow |
| DML runtime evidence | No comparable broad suite found | Gap |
| Property-based tests | Present | Good foundation |
| Literal/comment rewrite safety | Present for selected rules | Must become universal invariant |

## 3. Runtime semantic coverage

The current runtime semantic suite uses an in-memory DuckDB database and a PostgreSQL CI service. It exercises one employee aggregation query in both directions, checks AST semantic diff, and compares actual result rows.

This is valuable evidence but it is not a broad runtime equivalence framework. In particular, it does not establish behavior for Oracle, T-SQL, MySQL, Hive/Spark-family engines, Trino, Snowflake, Redshift, ClickHouse or Databricks.

## 4. Required target structure

Create:

```text
backend/tests/semantic/
├── corpus/
│   ├── README.md
│   └── *.json or *.yaml
├── test_golden_sql.py
├── test_dialect_matrix.py
├── test_semantic_diff.py
└── test_runtime_semantics.py
```

The existing top-level tests should remain during migration and be moved only when each case has an equivalent corpus representation; do not delete coverage merely to consolidate files.

## 5. Golden Corpus schema

Every corpus case should contain at least:

```yaml
id: mysql_group_concat_ordered
source_dialect: mysql
target_dialect: postgres
feature: aggregate
source_sql: "..."
expected_sql: "..."          # optional for formatting-specific cases
semantic_expectation: equivalent | warning | different
expected_warning_codes: []
notes: "..."
```

For semantic tests that cannot safely assert exact SQL, assert structured expectations instead:

- predicate tree
- projected columns
- aggregation functions
- group keys
- order keys/directions
- row-limit semantics
- null predicates
- casts/types
- function identities

## 6. P0 feature gaps

### Dates/timestamps
Add positive, negative and boundary cases for:

- `DATE_SUB`
- `DATE_ADD`
- `ADD_MONTHS`
- `CURRENT_DATE`
- `CURRENT_TIMESTAMP`
- month/year arithmetic
- interval literals
- timestamp/time-zone behavior
- end-of-month behavior

Targets: PostgreSQL, MySQL, Oracle, T-SQL, DuckDB plus at least parser-only coverage for other dialects.

### NULL semantics
Cover:

- `IS NULL`
- `IS NOT NULL`
- `COALESCE`
- MySQL `IFNULL`
- Oracle `NVL`
- T-SQL `ISNULL`
- NULL inside aggregates
- NULL comparison (`= NULL`, `<> NULL`) negative cases

### Boolean precedence
Cover nested combinations of `AND`, `OR`, `NOT`, predicates in function calls, parenthesized expressions, and generated NL2SQL conditions.

### Top-N
Cover:

- `TOP n`
- `TOP (n)`
- `FETCH FIRST n ROWS ONLY`
- `LIMIT n`
- Oracle `ROWNUM`
- explicit `ORDER BY`
- no `ORDER BY`
- `WITH TIES` / dialect-specific unsupported semantics
- top-N inside subqueries

### Aggregation
Cover:

- `COUNT(*)`
- `COUNT(expr)`
- `SUM`/`AVG` NULL behavior
- `GROUP_CONCAT` / `STRING_AGG` / `LISTAGG`
- DISTINCT aggregates
- ordered aggregates
- empty groups

### DML
Establish golden expectations for:

- INSERT values
- INSERT SELECT
- UPDATE with predicates
- DELETE with predicates
- DML without WHERE as an explicit policy case
- dialect-specific returning/output clauses

## 7. Rule rewrite invariant tests

Every rewrite rule must have:

1. positive case
2. negative/non-match case
3. single-quoted literal case
4. double/backtick/bracket identifier case where applicable
5. line comment case
6. block comment case
7. nested function case
8. nested parentheses case

The existing quote-safety tests are a good seed, but they should be generated from rule metadata rather than maintained only for one example rule.

## 8. Semantic-diff test gaps

Current tests cover one clearly equivalent query, one changed predicate, and parse failure. The next corpus must add classification cases for:

- formatting-only difference
- identifier quoting difference
- reordered commutative predicates
- `AND`/`OR` precedence difference
- NULL behavior difference
- cast/type coercion difference
- aggregate difference
- order-by difference
- limit/top difference
- join condition difference
- definitely incompatible syntax

## 9. Property-based test targets

Extend existing Hypothesis coverage to generate:

- nested function expressions
- nested boolean predicates
- quoted identifiers
- literals containing SQL-looking tokens
- comments containing function names
- arbitrary parenthesis depth within configured limits
- combinations of NULL predicates and boolean operators

Properties should include:

- scanner does not modify protected regions
- rewrite preserves balanced structure unless the rule explicitly changes it
- target parse succeeds for cases classified as syntax-equivalent
- no silent partial mapping occurs in type/function lookup

## 10. Required CI evidence model

CI should eventually publish counts for:

```text
syntax_pairs_tested
ast_pairs_tested
golden_cases_total
golden_cases_passed
runtime_cases_total
runtime_cases_passed
semantic_warnings
unsupported_cases
```

A passing test suite must not hide unsupported dialect/feature cases. Unsupported semantics should appear as explicit, reviewable results.

## 11. Release-quality test gate

Before 1.1.0, the semantic gate should require:

- all 144 basic pairs remain green
- all P0 corpus cases green
- no known P0 semantic warning downgraded to success without explicit evidence
- semantic-diff classifications stable
- runtime suites green where engines are available
- no regression in scanner safety
- property-based suite green
- package/wheel smoke test green
