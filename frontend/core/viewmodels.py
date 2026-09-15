"""Frontend ViewModels.

These adapters transform backend domain objects (TranspileResult,
SemanticDiff, NL2SQLResult, etc.) into presentation-friendly structures
that the UI layer consumes.  The UI must never reference backend field
names directly — all access goes through the ViewModel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from backend.core.semantic_diff import SemanticDiff, StructuredSemanticDifference

# ── Conversion ViewModel ───────────────────────────────────────────────

StatusKind = Literal["valid", "warning", "error", "info", "neutral"]
SyntaxStatus = Literal["ok", "error", "pending"]
ASTStatus = Literal["ok", "error", "pending"]
SemanticStatus = Literal["equivalent", "different", "unknown", "parse_error", "pending"]
RuntimeStatus = Literal["not_executed", "ok", "error", "pending"]


@dataclass
class ConversionViewModel:
    """Presentation model for a single SQL conversion result."""

    status: StatusKind
    source_dialect: str
    target_dialect: str
    source_sql: str
    target_sql: str | None
    syntax_status: SyntaxStatus
    ast_status: ASTStatus
    semantic_status: SemanticStatus
    semantic_label: str = ""
    runtime_status: RuntimeStatus = "not_executed"
    warnings: list[str] = field(default_factory=list)
    transformations: list[str] = field(default_factory=list)
    compatibility_notes: list[str] = field(default_factory=list)
    error_message: str | None = None
    semantic_findings: list[StructuredSemanticDifference] = field(default_factory=list)
    raw_backend_result: Any | None = None

    @classmethod
    def from_transpile_result(cls, result: Any) -> ConversionViewModel:
        """Build a ViewModel from a backend TranspileResult."""
        if result.success:
            status: StatusKind = "valid"
            error_message = None
            semantic_status: SemanticStatus = "pending"
            semantic_label = ""
            findings: list[StructuredSemanticDifference] = []
        else:
            status = "error"
            error_message = result.error or "Conversion failed"
            semantic_status = "parse_error"
            semantic_label = "Parse Error"
            findings = []

        return cls(
            status=status,
            source_dialect=result.source_dialect,
            target_dialect=result.target_dialect,
            source_sql=result.source_sql,
            target_sql=result.target_sql,
            syntax_status="ok" if result.success else "error",
            ast_status="ok" if result.success else "error",
            semantic_status=semantic_status,
            semantic_label=semantic_label,
            warnings=list(result.warnings),
            transformations=list(result.transformations),
            compatibility_notes=list(result.compatibility_notes),
            error_message=error_message,
            semantic_findings=findings,
            raw_backend_result=result,
        )

    @classmethod
    def from_semantic_diff(cls, base: ConversionViewModel, diff: SemanticDiff) -> ConversionViewModel:
        """Enrich a ConversionViewModel with semantic diff results."""
        from frontend.core.design_tokens import (
            SEMANTIC_STATUS_COLOR,
            SEMANTIC_STATUS_LABELS,
        )

        semantic_status_map: dict[str, SemanticStatus] = {
            "equivalent": "equivalent",
            "structurally_equivalent": "equivalent",
            "different": "different",
            "potentially_different": "unknown",
            "definitely_different": "different",
            "parse_error": "parse_error",
            "unknown": "unknown",
        }
        new_semantic = semantic_status_map.get(diff.semantic_classification, "unknown")
        label = SEMANTIC_STATUS_LABELS.get(diff.semantic_classification, diff.semantic_classification)
        color_key = SEMANTIC_STATUS_COLOR.get(diff.semantic_classification, "neutral")
        status: StatusKind = color_key  # type: ignore[assignment]

        enriched = cls(
            status=status,
            source_dialect=base.source_dialect,
            target_dialect=base.target_dialect,
            source_sql=base.source_sql,
            target_sql=base.target_sql,
            syntax_status=base.syntax_status,
            ast_status=base.ast_status,
            semantic_status=new_semantic,
            semantic_label=label,
            warnings=base.warnings,
            transformations=base.transformations,
            compatibility_notes=base.compatibility_notes,
            error_message=base.error_message,
            semantic_findings=list(diff.structured_differences),
            raw_backend_result=base.raw_backend_result,
        )
        return enriched


# ── Batch Conversion ViewModel ─────────────────────────────────────────

@dataclass
class BatchResultItem:
    statement_index: int
    original_sql: str
    converted_sql: str | None
    success: bool
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class BatchConversionViewModel:
    total: int
    succeeded: int
    failed: int
    items: list[BatchResultItem] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.succeeded / self.total if self.total else 0.0

    @classmethod
    def from_results(cls, statements: list[str], results: list[Any]) -> BatchConversionViewModel:
        items = []
        succeeded = 0
        for i, r in enumerate(results):
            ok = getattr(r, "success", False)
            if ok:
                succeeded += 1
            items.append(BatchResultItem(
                statement_index=i + 1,
                original_sql=statements[i] if i < len(statements) else "",
                converted_sql=r.target_sql if ok else None,
                success=ok,
                error=r.error if not ok else None,
                warnings=list(r.warnings) if ok else [],
            ))
        return cls(
            total=len(results),
            succeeded=succeeded,
            failed=len(results) - succeeded,
            items=items,
        )


# ── NL2SQL ViewModel ───────────────────────────────────────────────────

ConfidenceLevel = Literal["high", "review", "low"]


@dataclass
class NL2SQLViewModel:
    success: bool
    input_text: str
    sql: str | None
    dialect: str
    explanation: str
    confidence: float
    suggestions: list[str]
    parsed_elements: dict[str, Any]

    @property
    def status(self) -> StatusKind:
        return "valid" if self.success else "error"

    @property
    def confidence_level(self) -> ConfidenceLevel:
        """Map overall confidence to a display level."""
        if self.confidence >= 0.8:
            return "high"
        elif self.confidence >= 0.5:
            return "review"
        return "low"

    @property
    def confidence_label(self) -> str:
        return {
            "high": "High confidence",
            "review": "Review recommended",
            "low": "Low confidence",
        }[self.confidence_level]

    @property
    def tables(self) -> list[str]:
        """Extract table names from parsed_elements."""
        pe = self.parsed_elements
        return list({t for t in pe.get("tables", []) if t})

    @property
    def columns(self) -> list[str]:
        """Extract column names from parsed_elements."""
        pe = self.parsed_elements
        return list({c for c in pe.get("columns", []) if c})

    @property
    def values(self) -> list[str]:
        """Extract numeric/string values from parsed_elements."""
        pe = self.parsed_elements
        return list({str(v) for v in pe.get("numbers", []) if v})

    @property
    def is_chinese(self) -> bool:
        return bool(self.parsed_elements.get("is_chinese"))

    @property
    def token_count(self) -> int:
        return int(self.parsed_elements.get("token_count", 0))

    @classmethod
    def from_nl2sql_result(cls, result: Any) -> NL2SQLViewModel:
        return cls(
            success=result.success,
            input_text=result.input_text,
            sql=result.sql,
            dialect=result.dialect,
            explanation=result.explanation,
            confidence=result.confidence,
            suggestions=list(result.suggestions),
            parsed_elements=dict(result.parsed_elements),
        )

    def clean_sql(self) -> str:
        """Return SQL without any comment prefix that backend may add."""
        if not self.sql:
            return ""
        # Backend sometimes prefixes with "-- Generated for DIALECT\n"
        lines = self.sql.splitlines()
        sql_lines = [l for l in lines if not l.startswith("--")]
        return "\n".join(sql_lines).strip() or self.sql


# ── Semantic Diff ViewModel ────────────────────────────────────────────

FindingSeverity = Literal["error", "warning"]


@dataclass
class SemanticFindingViewModel:
    """Presentation model for one structured semantic difference finding."""

    index: int
    category: str
    severity: FindingSeverity
    source_fragment: str
    target_fragment: str
    explanation: str
    confidence: float
    evidence: str | None

    @classmethod
    def from_backend(cls, index: int, diff: StructuredSemanticDifference) -> SemanticFindingViewModel:
        return cls(
            index=index,
            category=diff.category,
            severity=diff.severity,  # type: ignore[arg-type]
            source_fragment=diff.source_fragment or "",
            target_fragment=diff.target_fragment or "",
            explanation=diff.explanation or "",
            confidence=diff.confidence,
            evidence=diff.evidence,
        )

    @property
    def severity_label(self) -> str:
        return "HIGH" if self.severity == "error" else "MEDIUM"

    @property
    def category_label(self) -> str:
        return self.category.replace("_", " ").title()


SemanticClassification = Literal[
    "equivalent",
    "structurally_equivalent",
    "potentially_different",
    "definitely_different",
    "unknown",
    "parse_error",
]


@dataclass
class SemanticDiffViewModel:
    """Presentation model for a full semantic diff comparison."""

    classification: SemanticClassification
    classification_label: str
    overall_status: StatusKind
    confidence: float
    source_sql: str
    target_sql: str
    source_dialect: str
    target_dialect: str
    parse_error: str | None
    differences: list[str]
    findings: list[SemanticFindingViewModel]
    evidence: str | None

    @classmethod
    def from_backend(
        cls,
        source_sql: str,
        target_sql: str,
        source_dialect: str,
        target_dialect: str,
        diff: SemanticDiff,
    ) -> SemanticDiffViewModel:
        from frontend.core.design_tokens import (
            SEMANTIC_STATUS_COLOR,
            SEMANTIC_STATUS_LABELS,
        )

        label = SEMANTIC_STATUS_LABELS.get(diff.semantic_classification, diff.semantic_classification)
        color_key = SEMANTIC_STATUS_COLOR.get(diff.semantic_classification, "neutral")
        status: StatusKind = color_key  # type: ignore[assignment]

        findings = [
            SemanticFindingViewModel.from_backend(i, sd)
            for i, sd in enumerate(diff.structured_differences)
        ]

        return cls(
            classification=diff.semantic_classification,  # type: ignore[arg-type]
            classification_label=label,
            overall_status=status,
            confidence=diff.confidence,
            source_sql=source_sql,
            target_sql=target_sql,
            source_dialect=source_dialect,
            target_dialect=target_dialect,
            parse_error=diff.parse_error,
            differences=list(diff.differences),
            findings=findings,
            evidence=diff.evidence,
        )

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")


# ── Lineage ViewModel ──────────────────────────────────────────────────

@dataclass
class LineageTable:
    name: str
    alias: str | None = None


@dataclass
class LineageOutputColumn:
    name: str
    expression: str = ""
    source_table: str | None = None
    source_column: str | None = None


@dataclass
class LineageViewModel:
    dialect: str
    sql: str
    tables: list[LineageTable] = field(default_factory=list)
    output_columns: list[LineageOutputColumn] = field(default_factory=list)
    column_references: dict[str, list[str]] = field(default_factory=dict)
    mermaid_safe: str = ""

    @classmethod
    def empty(cls, dialect: str, sql: str) -> LineageViewModel:
        return cls(dialect=dialect, sql=sql)


# ── Query Analysis ViewModel ───────────────────────────────────────────

@dataclass
class QueryAnalysisResult:
    dialect: str
    query_type: str = "SELECT"
    tables: list[str] = field(default_factory=list)
    join_count: int = 0
    has_aggregation: bool = False
    has_sorting: bool = False
    limit: str | None = None
    hints: list[str] = field(default_factory=list)
    error: str | None = None


# ── Helper: sanitize Mermaid identifiers ──────────────────────────────

_MERMAID_SAFE_REPLACEMENTS = {
    '"': "",
    "'": "",
    "`": "",
    "\\": "",
    "/": "_",
    " ": "_",
    "-": "_",
    ".": "_",
    ",": "",
    "(": "",
    ")": "",
    "[": "",
    "]": "",
    "{": "",
    "}": "",
    "<": "",
    ">": "",
    "|": "_",
    "\n": "",
    "\r": "",
    "\t": "",
}


def sanitize_mermaid_label(text: str) -> str:
    """Sanitize a string for use as a Mermaid node label or identifier."""
    result = str(text)
    for bad, repl in _MERMAID_SAFE_REPLACEMENTS.items():
        result = result.replace(bad, repl)
    # Collapse underscores
    while "__" in result:
        result = result.replace("__", "_")
    result = result.strip("_")
    return result or "node"


def sanitize_mermaid_id(text: str) -> str:
    """Sanitize a string for use as a Mermaid node ID (alphanumeric + underscore)."""
    import re
    result = sanitize_mermaid_label(text)
    result = re.sub(r"[^a-zA-Z0-9_]", "_", result)
    # Must start with a letter
    if result and not result[0].isalpha():
        result = "n_" + result
    return result or "node"
