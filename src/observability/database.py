"""Database backend for query logs.

Supports two backends:
  - _SqliteLogDb  — local SQLite file (used in tests and local development)
  - _TursoLogDb   — Turso/libSQL cloud DB via HTTP (used in production)

Factory `get_log_db()` selects the backend automatically:
  - If called with an explicit db_path  → SQLite at that path (tests)
  - If TURSO_DATABASE_URL env var is set → Turso (Streamlit Cloud)
  - If TURSO_DATABASE_URL in st.secrets  → Turso (Streamlit Cloud secrets fallback)
  - Otherwise                            → SQLite at data/logs.db (local dev)
"""
import json
import logging
import os
import sqlite3
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/logs.db")

# Individual DDL statements — kept separate so both backends can execute them
# without needing executescript (which is SQLite-only syntax).
_SCHEMA_STMTS: list[str] = [
    """CREATE TABLE IF NOT EXISTS queries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        session_id TEXT NOT NULL,
        query TEXT NOT NULL,
        answer TEXT NOT NULL,
        chunks_used TEXT NOT NULL,
        refused INTEGER NOT NULL,
        feedback TEXT,
        feedback_comment TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_timestamp ON queries(timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_session ON queries(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_refused ON queries(refused)",
    "CREATE INDEX IF NOT EXISTS idx_feedback ON queries(feedback)",
]


# ---------------------------------------------------------------------------
# Cursor abstraction
# ---------------------------------------------------------------------------

class _Cursor:
    """Minimal cursor returned by LogDb.execute().

    Mirrors the subset of sqlite3.Cursor that QueryLogger uses:
      cursor.lastrowid, cursor.rowcount, cursor.fetchone(), cursor.fetchall()
    Rows are plain dicts (str → Python value).
    """

    def __init__(
        self,
        rows: list[dict],
        lastrowid: int | None,
        rowcount: int,
    ) -> None:
        self._rows = rows
        self.lastrowid = lastrowid
        self.rowcount = rowcount

    def fetchone(self) -> dict | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict]:
        return self._rows


# ---------------------------------------------------------------------------
# Abstract backend
# ---------------------------------------------------------------------------

class LogDb(ABC):
    """Minimal database interface used by QueryLogger."""

    @abstractmethod
    def execute(self, sql: str, params: tuple = ()) -> _Cursor:
        """Execute one SQL statement with optional positional params."""

    @abstractmethod
    def executescript(self, statements: list[str]) -> None:
        """Execute a list of DDL/DML statements (used for schema init)."""

    @abstractmethod
    def close(self) -> None:
        """Release any resources held by this backend instance."""


# ---------------------------------------------------------------------------
# SQLite backend
# ---------------------------------------------------------------------------

class _SqliteLogDb(LogDb):
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path),
            timeout=10.0,
            isolation_level=None,  # autocommit
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def execute(self, sql: str, params: tuple = ()) -> _Cursor:
        cur = self._conn.execute(sql, params)
        # Eagerly fetch so callers can call .fetchone()/.fetchall() on _Cursor.
        raw = cur.fetchall() or []
        rows = [dict(r) for r in raw]
        return _Cursor(rows, cur.lastrowid, cur.rowcount)

    def executescript(self, statements: list[str]) -> None:
        for stmt in statements:
            self._conn.execute(stmt)

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Turso (libSQL cloud) backend
# ---------------------------------------------------------------------------

def _turso_val(v: object) -> object:
    """Convert a Turso typed-value object {type, value} to a Python value."""
    if not isinstance(v, dict):
        return v
    t = v.get("type", "text")
    val = v.get("value")
    if t == "null" or val is None:
        return None
    if t == "integer":
        return int(val)
    if t == "float":
        return float(val)
    return str(val)  # text, blob → str


def _turso_arg(v: object) -> dict:
    """Convert a Python value to a Turso typed-argument object."""
    if v is None:
        return {"type": "null", "value": None}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": str(v)}
    return {"type": "text", "value": str(v)}


class _TursoLogDb(LogDb):
    """Turso/libSQL cloud backend via the HTTP /v2/pipeline API."""

    def __init__(self, url: str, auth_token: str) -> None:
        # Accept both libsql:// and https:// schemes
        base = url.replace("libsql://", "https://").rstrip("/")
        self._pipeline_url = f"{base}/v2/pipeline"
        self._token = auth_token

    def _request(self, requests: list[dict]) -> list[dict]:
        payload = json.dumps({"requests": requests}).encode()
        req = urllib.request.Request(
            self._pipeline_url,
            data=payload,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except Exception as exc:
            logger.error(
                "Turso HTTP request failed (url=%s): %s",
                self._pipeline_url,
                exc,
            )
            raise
        return data.get("results", [])

    def execute(self, sql: str, params: tuple = ()) -> _Cursor:
        results = self._request([
            {
                "type": "execute",
                "stmt": {
                    "sql": sql,
                    "args": [_turso_arg(p) for p in params],
                },
            },
            {"type": "close"},
        ])
        if not results:
            return _Cursor([], None, 0)

        res = results[0]
        if res.get("type") == "error":
            msg = res.get("error", {}).get("message", str(res))
            raise RuntimeError(f"Turso execute error: {msg}")

        result = res.get("response", {}).get("result", {})
        cols = [c["name"] for c in result.get("cols", [])]
        rows = [
            {cols[i]: _turso_val(cell) for i, cell in enumerate(row)}
            for row in result.get("rows", [])
        ]
        raw_id = result.get("last_insert_rowid")
        lastrowid = int(raw_id) if raw_id is not None else None
        rowcount = int(result.get("affected_row_count", 0))
        return _Cursor(rows, lastrowid, rowcount)

    def executescript(self, statements: list[str]) -> None:
        requests: list[dict] = [
            {
                "type": "execute",
                "stmt": {"sql": stmt, "args": []},
            }
            for stmt in statements
        ] + [{"type": "close"}]
        results = self._request(requests)
        for r in results:
            if r.get("type") == "error":
                msg = r.get("error", {}).get("message", str(r))
                raise RuntimeError(f"Turso schema error: {msg}")

    def close(self) -> None:
        pass  # Stateless HTTP; nothing to release


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def _get_st_secret(key: str) -> str:
    """Read a secret from st.secrets. Returns '' on any failure (no Streamlit context, key absent, etc.)."""
    try:
        import streamlit as st  # noqa: PLC0415
        val = st.secrets.get(key, "")  # type: ignore[attr-defined]
        return (val or "").strip()
    except Exception:
        return ""


def get_log_db(db_path: Path | None = None) -> LogDb:
    """Return the appropriate LogDb backend.

    Selection order:
      1. Explicit db_path          → _SqliteLogDb at that path (tests / local scripts)
      2. TURSO_DATABASE_URL in env → _TursoLogDb (Streamlit Cloud production)
      3. TURSO_DATABASE_URL in st.secrets → _TursoLogDb (Streamlit Cloud secrets fallback)
      4. Fallback                  → _SqliteLogDb at DEFAULT_DB_PATH (local dev, no cloud creds)
    """
    if db_path is not None:
        return _SqliteLogDb(Path(db_path))

    turso_url = os.environ.get("TURSO_DATABASE_URL", "").strip()
    turso_token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()

    # Streamlit Cloud may not reliably inject secrets into os.environ — fall back to st.secrets.
    if not turso_url:
        turso_url = _get_st_secret("TURSO_DATABASE_URL")
    if not turso_token:
        turso_token = _get_st_secret("TURSO_AUTH_TOKEN")

    if turso_url:
        # Normalize now so the logged URL matches what we actually connect to.
        https_url = turso_url.replace("libsql://", "https://").rstrip("/")
        logger.info("Using Turso backend: %s", https_url)
        return _TursoLogDb(turso_url, turso_token)

    logger.info(
        "Using local SQLite fallback (no TURSO_DATABASE_URL found): %s",
        DEFAULT_DB_PATH,
    )
    return _SqliteLogDb(DEFAULT_DB_PATH)


def init_db(db_path: Path | None = None) -> None:
    """Create the schema if missing. Idempotent — safe to call on every startup."""
    db = get_log_db(db_path)
    try:
        db.executescript(_SCHEMA_STMTS)
        logger.info("Query log schema initialized")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Legacy shim — kept so scripts/init_db.py and any future callers still work
# ---------------------------------------------------------------------------

def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Deprecated: open a raw SQLite connection. Use get_log_db() instead."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
