"""Session State Adapter for SQL Dialect Master v2.

Provides a typed, centralized boundary between raw Streamlit session state
and application domain state.  Widget-local keys (passed to ``st.*`` widgets)
remain managed by Streamlit directly — only cross-rerun / cross-page
application state flows through this adapter.

Design:
    Streamlit widget state
            |
            |  raw session_state (widget keys)
            v
    SessionState adapter          <--- canonical boundary
            |
            v
    typed application state
            |
            v
    pages (read/write via adapter)

HistoryEntry contract:
    identity   str   — opaque stable key (hex, 8+ chars)
    sql        str   — source SQL
    source_dialect str
    target_dialect str
    result_sql str | None
    status     StatusKind
    created_at str   — ISO-8601
    is_favorite bool — mirrors favorites membership

Legacy raw dict shape (still accepted):
    {identity, sql, src, tgt, result, status, created_at, is_favorite}

Current state version: 1
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import streamlit as st

from frontend.core.navigation import (
    NavigationIntent,
    consume_navigation_intent,
    get_pending_intent,
)
from frontend.core.statuses import StatusKind, normalize_status

# ── Versioning ────────────────────────────────────────────────────────

_STATE_VERSION_KEY = "sdm_state_version"
_CURRENT_VERSION = 1
MAX_HISTORY_ENTRIES = 100

# ── Type aliases ──────────────────────────────────────────────────────

# ── Domain models ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class HistoryEntry:
    """Immutable history entry with stable identity.

    NOTE: `is_favorite` is intentionally NOT a persisted field.
    Favorite status is tracked solely in the `favorites` list
    (sdm_favorites) and accessed via `state.is_favorite(identity)`.
    This prevents dual-source-of-truth for favorite state.
    """

    identity: str
    sql: str
    source_dialect: str
    target_dialect: str
    result_sql: str | None = None
    status: StatusKind = "neutral"
    created_at: str = ""

    @classmethod
    def from_raw_dict(cls, raw: dict[str, Any]) -> "HistoryEntry":
        """Build a HistoryEntry from a legacy runtime dict."""
        return cls(
            identity=str(raw.get("identity", "")) if raw.get("identity") is not None else "",
            sql=raw.get("sql", "") if isinstance(raw.get("sql", ""), str) else "",
            source_dialect=raw.get("src", raw.get("source_dialect", ""))
            if isinstance(raw.get("src", raw.get("source_dialect", "")), str) else "",
            target_dialect=raw.get("tgt", raw.get("target_dialect", ""))
            if isinstance(raw.get("tgt", raw.get("target_dialect", "")), str) else "",
            result_sql=(raw.get("result") if isinstance(raw.get("result"), str)
                        else raw.get("result_sql") if isinstance(raw.get("result_sql"), str)
                        else None),
            status=normalize_status(raw.get("status", "neutral")),
            created_at=raw.get("created_at", "") if isinstance(raw.get("created_at", ""), str) else "",
        )

    def to_raw_dict(self) -> dict[str, Any]:
        """Serialize to the raw dict shape stored in session state.

        NOTE: `is_favorite` is intentionally omitted. Favorite status is
        tracked solely in the `favorites` list, not on individual entries.
        """
        return {
            "identity": self.identity,
            "sql": self.sql,
            "src": self.source_dialect,
            "tgt": self.target_dialect,
            "result": self.result_sql,
            "status": self.status,
            "created_at": self.created_at,
        }


# ── Legacy state model classes (backward-compatible, not wired into runtime) ──
#
# These classes exist for test compatibility and documentation.  Production
# code should use SessionState.get() instead.  They mirror the original
# intent of state.py and are intentionally NOT instantiated by pages.


@dataclass(frozen=True)
class ConversionState:
    """LEGACY — use SessionState instead. Kept for test compatibility."""

    source_dialect: str = "postgres"
    target_dialect: str = "mysql"
    source_sql: str = ""
    target_sql: str | None = None
    last_result: Any | None = None
    formatted_source: str | None = None
    batch_source: str = ""
    batch_target: str = "mysql"
    batch_results: list[Any] | None = None


@dataclass
class NL2SQLState:
    """LEGACY — use SessionState instead. Kept for test compatibility."""

    target_dialect: str = "postgres"
    natural_language: str = ""
    table_hint: str = ""
    last_result: Any | None = None
    loading: bool = False
    error: str | None = None


@dataclass(frozen=True)
class LineageState:
    """LEGACY — use SessionState instead. Kept for test compatibility."""

    dialect: str = "postgres"
    sql: str = ""
    last_tables: list[dict[str, str]] = field(default_factory=list)
    last_output_cols: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExplainState:
    """LEGACY — use SessionState instead. Kept for test compatibility."""

    sql: str = ""
    dialect_a: str = "postgres"
    dialect_b: str = "mysql"
    plan_a: dict[str, Any] | None = None
    plan_b: dict[str, Any] | None = None


@dataclass(frozen=True)
class FunctionsState:
    """LEGACY — use widget keys instead. Kept for test compatibility."""

    search_query: str = ""
    category_filter: str = "all"


@dataclass(frozen=True)
class TypesState:
    """LEGACY — use widget keys instead. Kept for test compatibility."""

    source_dialect: str = "postgres"
    target_dialect: str = "mysql"
    selected_type: str = ""
    category_filter: str = "all"


@dataclass(frozen=True)
class SettingsState:
    """LEGACY — use SessionState.theme instead. Kept for test compatibility."""

    theme: Literal["dark", "light"] = "dark"
    keybindings_visible: bool = False


@dataclass
class AppState:
    """LEGACY — use SessionState instead. Kept for test compatibility."""

    theme: Literal["dark", "light"] = "dark"
    history: list[HistoryEntry] = field(default_factory=list)
    favorites: list[str] = field(default_factory=list)  # FIXED: was list[int]
    conversion: ConversionState = field(default_factory=ConversionState)
    nl2sql: NL2SQLState = field(default_factory=NL2SQLState)
    lineage: LineageState = field(default_factory=LineageState)
    explain: ExplainState = field(default_factory=ExplainState)
    functions: FunctionsState = field(default_factory=FunctionsState)
    types: TypesState = field(default_factory=TypesState)
    settings: SettingsState = field(default_factory=SettingsState)
    navigation: NavigationIntent = field(default_factory=NavigationIntent)

    def current_theme_name(self) -> Literal["dark", "light"]:
        return self.theme

    def history_count(self) -> int:
        return len(self.history)

    def favorite_count(self) -> int:
        return len(self.favorites)


# ── SessionState ───────────────────────────────────────────────────────


class SessionState:
    """Typed adapter over Streamlit session state.

    Use ``SessionState.get()`` to obtain the singleton instance for the
    current Streamlit session.  All application-level state flows through
    this class — widget-local keys remain managed by Streamlit directly.
    """

    # Application-state keys (managed by this adapter)
    _KEY_THEME = "sdm_theme"
    _KEY_HISTORY = "sdm_history"
    _KEY_FAVORITES = "sdm_favorites"
    _KEY_NAVIGATION = "sdm_navigation_intent"
    _KEY_FINDING = "sdm_selected_finding_index"
    _KEY_CONVERT_VM = "convert_last_vm"
    _KEY_CONVERT_TARGET_SQL = "convert_target_sql"
    _KEY_CONVERT_FINGERPRINT = "convert_last_fingerprint"
    _KEY_BATCH_VM = "batch_last_vm"
    _KEY_BATCH_FINGERPRINT = "batch_last_fingerprint"
    _KEY_NL_VM = "nl_last_vm"
    _KEY_NL_FINGERPRINT = "nl_last_fingerprint"
    _KEY_NL_ERROR = "nl_generation_error"
    _KEY_DIFF_VM = "diff_last_vm"
    _KEY_DIFF_FINGERPRINT = "diff_last_fingerprint"
    _KEY_LINEAGE_VM = "lineage_last_vm"
    _KEY_QA_RESULT = "qa_last_result"

    # Widget-local keys (NOT managed by this adapter)
    # convert_src, convert_tgt, convert_src_sql, batch_sql_input,
    # batch_src, batch_tgt, nl_example_sel, nl_input_text, nl_dialect,
    # nl_table_hint, diff_src_sql, diff_tgt_sql, diff_src_dialect,
    # diff_tgt_dialect, lineage_dialect, lineage_sql, qa_dialect, qa_sql,
    # hist_search, hist_filter, settings_theme_sel

    def __init__(self) -> None:
        self._raw: dict[str, Any] = st.session_state

    # ── Lifecycle ────────────────────────────────────────────────────

    @classmethod
    def get(cls) -> "SessionState":
        """Return the singleton SessionState for the current session."""
        return cls()

    def ensure_defaults(self) -> None:
        """Initialize missing application-state keys with safe defaults.

        NOTE: Does NOT write the state version key. That is the responsibility
        of `migrate()`. This separation ensures migration can read the
        existing version before it gets overwritten.
        """
        raw = self._raw
        # Theme default — only set if missing (preserve user's choice)
        if self._KEY_THEME not in raw:
            raw[self._KEY_THEME] = "dark"
        # History default
        self._normalize_history()
        # Favorites default
        if self._KEY_FAVORITES not in raw:
            raw[self._KEY_FAVORITES] = []
        # Navigation intent — reset stale intents on fresh session
        if self._KEY_NAVIGATION not in raw or not isinstance(
            raw[self._KEY_NAVIGATION], NavigationIntent
        ):
            raw[self._KEY_NAVIGATION] = NavigationIntent()
        # Finding selection
        if self._KEY_FINDING not in raw:
            raw[self._KEY_FINDING] = None
        # Workspace VMs
        if self._KEY_CONVERT_VM not in raw:
            raw[self._KEY_CONVERT_VM] = None
        if self._KEY_CONVERT_TARGET_SQL not in raw:
            raw[self._KEY_CONVERT_TARGET_SQL] = ""
        if self._KEY_CONVERT_FINGERPRINT not in raw:
            raw[self._KEY_CONVERT_FINGERPRINT] = None
        if self._KEY_BATCH_VM not in raw:
            raw[self._KEY_BATCH_VM] = None
        if self._KEY_BATCH_FINGERPRINT not in raw:
            raw[self._KEY_BATCH_FINGERPRINT] = None
        if self._KEY_NL_VM not in raw:
            raw[self._KEY_NL_VM] = None
        if self._KEY_NL_FINGERPRINT not in raw:
            raw[self._KEY_NL_FINGERPRINT] = None
        if self._KEY_NL_ERROR not in raw:
            raw[self._KEY_NL_ERROR] = None
        if self._KEY_DIFF_VM not in raw:
            raw[self._KEY_DIFF_VM] = None
        if self._KEY_DIFF_FINGERPRINT not in raw:
            raw[self._KEY_DIFF_FINGERPRINT] = None
        if self._KEY_LINEAGE_VM not in raw:
            raw[self._KEY_LINEAGE_VM] = None
        if self._KEY_QA_RESULT not in raw:
            raw[self._KEY_QA_RESULT] = None

    def migrate(self) -> None:
        """Upgrade legacy session state to the current schema version.

        IMPORTANT: Must be called AFTER ensure_defaults() has read the
        existing version but BEFORE it overwrites with the current version.
        See __init__ for the correct call order.
        """
        raw = self._raw
        # Read version BEFORE ensure_defaults writes the current version.
        # If the user calls migrate() directly, check what's there.
        version = raw.get(_STATE_VERSION_KEY, 0)
        if version >= _CURRENT_VERSION:
            return

        # Migrate favorites from int indices to string identities
        favorites = raw.get(self._KEY_FAVORITES, [])
        if isinstance(favorites, list) and favorites:
            if isinstance(favorites[0], int):
                # Legacy int-index favorites → empty (identities lost)
                raw[self._KEY_FAVORITES] = []
                logger = __import__("logging").getLogger(__name__)
                logger.warning(
                    "Migrated legacy int-based favorites to empty list "
                    "(identities cannot be recovered)"
                )

        # Migrate history entries to canonical shape
        self._normalize_history()

        raw[_STATE_VERSION_KEY] = _CURRENT_VERSION

    # ── Theme ──────────────────────────────────────────────────────────

    @property
    def theme(self) -> str:
        return self._raw.get(self._KEY_THEME, "dark")

    @theme.setter
    def theme(self, value: str) -> None:
        self._raw[self._KEY_THEME] = value

    # ── History ────────────────────────────────────────────────────────

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._normalize_history())

    @history.setter
    def history(self, value: list[dict[str, Any]]) -> None:
        self._raw[self._KEY_HISTORY] = list(value) if isinstance(value, list) else []
        self._normalize_history()

    def _normalize_history(self) -> list[dict[str, Any]]:
        """Repair malformed history state at the session boundary.

        Streamlit sessions can outlive code versions and may contain ``None``,
        non-dict values, or widget-hostile identities.  Keep only dictionaries,
        normalize display fields, give each entry a bounded stable identity,
        and retain the newest entries when a session grows without bound.
        """
        import re
        import uuid

        raw_history = self._raw.get(self._KEY_HISTORY)
        if not isinstance(raw_history, list):
            self._raw[self._KEY_HISTORY] = []
            return []
        cleaned: list[dict[str, Any]] = []
        seen_identities: set[str] = set()
        identity_re = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
        for value in raw_history:
            if not isinstance(value, dict):
                continue
            entry = dict(value)
            # Session data may come from an older app version or manual edits.
            # Never pass None, numbers, or containers into string widgets.
            for key, fallback in (("sql", ""), ("src", "postgres"), ("tgt", "mysql"),
                                  ("created_at", ""), ("error", "")):
                candidate = entry.get(key, fallback)
                entry[key] = candidate if isinstance(candidate, str) else fallback
            from backend.core.config import SUPPORTED_DIALECTS

            for key, legacy_key, fallback in (
                ("src", "source_dialect", "postgres"),
                ("tgt", "target_dialect", "mysql"),
            ):
                candidate = value.get(key, value.get(legacy_key, fallback))
                normalized = candidate.strip().lower() if isinstance(candidate, str) else fallback
                entry[key] = normalized if normalized in SUPPORTED_DIALECTS else fallback
            result = entry.get("result", entry.get("result_sql"))
            entry["result"] = result if isinstance(result, str) else None
            entry["status"] = normalize_status(entry.get("status", "neutral"))
            identity = entry.get("identity")
            if (
                not isinstance(identity, str)
                or not identity_re.fullmatch(identity)
                or identity in seen_identities
            ):
                entry["identity"] = uuid.uuid4().hex[:8]
            seen_identities.add(entry["identity"])
            cleaned.append(entry)
        if len(cleaned) > MAX_HISTORY_ENTRIES:
            cleaned = cleaned[-MAX_HISTORY_ENTRIES:]
        self._raw[self._KEY_HISTORY] = cleaned
        return cleaned

    def add_history_entry(
        self,
        sql: str,
        source_dialect: str,
        target_dialect: str,
        result_sql: str | None = None,
        status: StatusKind = "neutral",
        created_at: str = "",
        error_message: str | None = None,
    ) -> str:
        """Add a history entry and return its identity string."""
        import uuid
        identity = uuid.uuid4().hex[:8]
        entry: dict[str, Any] = {
            "identity": identity,
            "sql": sql,
            "src": source_dialect,
            "tgt": target_dialect,
            "result": result_sql,
            "status": status,
            "created_at": created_at,
            "error": error_message or "",
            # NOTE: is_favorite is NOT persisted here.
            # Favorite status is tracked solely in the `favorites` list.
            # Access via state.is_favorite(identity).
        }
        if self._KEY_HISTORY not in self._raw:
            self._raw[self._KEY_HISTORY] = []
        self._raw[self._KEY_HISTORY].append(entry)
        self._normalize_history()
        return identity

    def remove_history_entry(self, identity: str) -> bool:
        """Remove a history entry by identity. Returns True if found."""
        history = self._normalize_history()
        before = len(history)
        self._raw[self._KEY_HISTORY] = [
            e for e in history if e.get("identity") != identity
        ]
        removed = before - len(self._raw[self._KEY_HISTORY])
        if removed > 0:
            # Also remove from favorites
            self._remove_favorite(identity)
        return removed > 0

    def history_count(self) -> int:
        return len(self._normalize_history())

    # ── Favorites ──────────────────────────────────────────────────────

    @property
    def favorites(self) -> list[str]:
        """Return favorites as a list of history entry identity strings."""
        raw = self._raw.get(self._KEY_FAVORITES)
        # Handle None or non-list types safely
        if not isinstance(raw, list):
            self._raw[self._KEY_FAVORITES] = []
            return []
        # Ensure all items are strings; filter out non-strings
        if raw and not isinstance(raw[0], str):
            # Legacy int-based or mixed — migrate to empty
            self._raw[self._KEY_FAVORITES] = []
            return []
        # Filter to ensure only strings remain
        result = [f for f in raw if isinstance(f, str)]
        if len(result) != len(raw):
            self._raw[self._KEY_FAVORITES] = result
        return result

    @favorites.setter
    def favorites(self, value: list[str]) -> None:
        # Validate: must be list[str]
        if not isinstance(value, list):
            raise TypeError(f"favorites must be list[str], got {type(value).__name__}")
        for item in value:
            if not isinstance(item, str):
                raise TypeError(
                    f"favorites items must be str, got {type(item).__name__}"
                )
        self._raw[self._KEY_FAVORITES] = list(value)

    def add_favorite(self, identity: str) -> None:
        """Add a history entry identity to favorites (idempotent)."""
        favs = self.favorites
        if identity not in favs:
            self._raw[self._KEY_FAVORITES] = favs + [identity]

    def remove_favorite(self, identity: str) -> None:
        """Remove a history entry identity from favorites."""
        favs = self.favorites
        if identity in favs:
            self._raw[self._KEY_FAVORITES] = [f for f in favs if f != identity]

    def toggle_favorite(self, identity: str) -> None:
        """Toggle favorite status for a history entry identity."""
        if identity in self.favorites:
            self.remove_favorite(identity)
        else:
            self.add_favorite(identity)

    def is_favorite(self, identity: str) -> bool:
        return identity in self.favorites

    def favorite_count(self) -> int:
        return len(self.favorites)

    def _remove_favorite(self, identity: str) -> None:
        """Internal: remove identity from favorites without validation."""
        favs = self._raw.get(self._KEY_FAVORITES, [])
        if isinstance(favs, list) and identity in favs:
            self._raw[self._KEY_FAVORITES] = [f for f in favs if f != identity]

    # ── Conversion ─────────────────────────────────────────────────────

    @property
    def convert_last_vm(self) -> Any:
        return self._raw.get(self._KEY_CONVERT_VM)

    @convert_last_vm.setter
    def convert_last_vm(self, value: Any) -> None:
        self._raw[self._KEY_CONVERT_VM] = value

    @property
    def convert_target_sql(self) -> str:
        return self._raw.get(self._KEY_CONVERT_TARGET_SQL, "")

    @convert_target_sql.setter
    def convert_target_sql(self, value: str) -> None:
        self._raw[self._KEY_CONVERT_TARGET_SQL] = value or ""

    @property
    def convert_last_fingerprint(self) -> str | None:
        value = self._raw.get(self._KEY_CONVERT_FINGERPRINT)
        return value if isinstance(value, str) else None

    @convert_last_fingerprint.setter
    def convert_last_fingerprint(self, value: str | None) -> None:
        self._raw[self._KEY_CONVERT_FINGERPRINT] = value

    @property
    def batch_last_vm(self) -> Any:
        return self._raw.get(self._KEY_BATCH_VM)

    @batch_last_vm.setter
    def batch_last_vm(self, value: Any) -> None:
        self._raw[self._KEY_BATCH_VM] = value

    @property
    def batch_last_fingerprint(self) -> str | None:
        value = self._raw.get(self._KEY_BATCH_FINGERPRINT)
        return value if isinstance(value, str) else None

    @batch_last_fingerprint.setter
    def batch_last_fingerprint(self, value: str | None) -> None:
        self._raw[self._KEY_BATCH_FINGERPRINT] = value

    # ── NL2SQL ──────────────────────────────────────────────────────────

    @property
    def nl_last_vm(self) -> Any:
        return self._raw.get(self._KEY_NL_VM)

    @nl_last_vm.setter
    def nl_last_vm(self, value: Any) -> None:
        self._raw[self._KEY_NL_VM] = value

    @property
    def nl_last_fingerprint(self) -> str | None:
        value = self._raw.get(self._KEY_NL_FINGERPRINT)
        return value if isinstance(value, str) else None

    @nl_last_fingerprint.setter
    def nl_last_fingerprint(self, value: str | None) -> None:
        self._raw[self._KEY_NL_FINGERPRINT] = value

    @property
    def nl_generation_error(self) -> str | None:
        return self._raw.get(self._KEY_NL_ERROR)

    @nl_generation_error.setter
    def nl_generation_error(self, value: str | None) -> None:
        self._raw[self._KEY_NL_ERROR] = value

    # ── Diff ────────────────────────────────────────────────────────────

    @property
    def diff_last_vm(self) -> Any:
        return self._raw.get(self._KEY_DIFF_VM)

    @diff_last_vm.setter
    def diff_last_vm(self, value: Any) -> None:
        self._raw[self._KEY_DIFF_VM] = value

    @property
    def diff_last_fingerprint(self) -> str | None:
        value = self._raw.get(self._KEY_DIFF_FINGERPRINT)
        return value if isinstance(value, str) else None

    @diff_last_fingerprint.setter
    def diff_last_fingerprint(self, value: str | None) -> None:
        self._raw[self._KEY_DIFF_FINGERPRINT] = value

    @property
    def selected_finding_index(self) -> int | None:
        return self._raw.get(self._KEY_FINDING)

    @selected_finding_index.setter
    def selected_finding_index(self, value: int | None) -> None:
        self._raw[self._KEY_FINDING] = value

    # ── Lineage ─────────────────────────────────────────────────────────

    @property
    def lineage_last_vm(self) -> Any:
        return self._raw.get(self._KEY_LINEAGE_VM)

    @lineage_last_vm.setter
    def lineage_last_vm(self, value: Any) -> None:
        self._raw[self._KEY_LINEAGE_VM] = value

    # ── Query Analysis ──────────────────────────────────────────────────

    @property
    def qa_last_result(self) -> Any:
        return self._raw.get(self._KEY_QA_RESULT)

    @qa_last_result.setter
    def qa_last_result(self, value: Any) -> None:
        self._raw[self._KEY_QA_RESULT] = value

    # ── Navigation (delegates to navigation.py) ────────────────────────

    def get_pending_intent(self) -> NavigationIntent:
        """Read the current pending navigation intent."""
        return get_pending_intent()

    def consume_navigation_intent(self) -> NavigationIntent | None:
        """Atomically read and clear the pending navigation intent."""
        return consume_navigation_intent()

    def clear_finding_selection(self) -> None:
        """Clear the selected finding index."""
        self._raw[self._KEY_FINDING] = None

    # ── Raw access (for pages that still need it) ──────────────────────

    def get_raw(self, key: str) -> Any:
        """Access a raw session-state key (use sparingly)."""
        return self._raw.get(key)

    def set_raw(self, key: str, value: Any) -> None:
        """Set a raw session-state key (use sparingly)."""
        self._raw[key] = value

    def has_raw(self, key: str) -> bool:
        return key in self._raw


# ── Module-level convenience ───────────────────────────────────────────

def get_session_state() -> SessionState:
    """Return the current session's SessionState adapter."""
    return SessionState.get()


__all__ = [
    "SessionState",
    "HistoryEntry",
    "StatusKind",
    "get_session_state",
    # Legacy references (kept for import stability)
    "ConversionState",
    "NL2SQLState",
    "LineageState",
    "ExplainState",
    "FunctionsState",
    "TypesState",
    "SettingsState",
    "AppState",
]
