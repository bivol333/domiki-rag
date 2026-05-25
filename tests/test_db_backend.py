"""Tests for the LogDb abstraction in src/observability/database.py.

Covers:
  - Factory selects the right backend based on env vars / explicit path
  - Factory falls back to st.secrets when env vars are absent
  - _SqliteLogDb: schema init, insert, select, update, rowcount, lastrowid
  - _turso_arg / _turso_val type conversion helpers
  - _TursoLogDb is returned when TURSO_DATABASE_URL is set (no network needed)
"""
import os

import pytest

import src.observability.database as db_module
from src.observability.database import (
    DEFAULT_DB_PATH,
    LogDb,
    _SqliteLogDb,
    _TursoLogDb,
    _turso_arg,
    _turso_val,
    get_log_db,
    init_db,
)


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------

def test_get_log_db_explicit_path_returns_sqlite(tmp_path):
    db_path = tmp_path / "explicit.db"
    db = get_log_db(db_path)
    try:
        assert isinstance(db, _SqliteLogDb)
    finally:
        db.close()


def test_get_log_db_no_turso_url_returns_sqlite(monkeypatch):
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    db = get_log_db()
    try:
        assert isinstance(db, _SqliteLogDb)
    finally:
        db.close()


def test_get_log_db_with_turso_url_returns_turso(monkeypatch):
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://test-db-org.turso.io")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "fake-token")
    db = get_log_db()
    # Don't close — no network connection is opened until a request is made
    assert isinstance(db, _TursoLogDb)


def test_get_log_db_falls_back_to_st_secrets(monkeypatch):
    """When TURSO_DATABASE_URL is absent from env but present in st.secrets, use Turso."""
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)

    _secrets = {
        "TURSO_DATABASE_URL": "libsql://test-db-org.turso.io",
        "TURSO_AUTH_TOKEN": "secret-token",
    }
    monkeypatch.setattr(db_module, "_get_st_secret", lambda key: _secrets.get(key, ""))

    db = get_log_db()
    assert isinstance(db, _TursoLogDb)


def test_get_log_db_st_secrets_empty_returns_sqlite(monkeypatch):
    """When both env and st.secrets have no Turso URL, fall back to SQLite."""
    monkeypatch.delenv("TURSO_DATABASE_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(db_module, "_get_st_secret", lambda key: "")

    db = get_log_db()
    try:
        assert isinstance(db, _SqliteLogDb)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# _SqliteLogDb round-trip
# ---------------------------------------------------------------------------

@pytest.fixture()
def sqlite_db(tmp_path) -> _SqliteLogDb:
    db = _SqliteLogDb(tmp_path / "test.db")
    db.executescript([
        """CREATE TABLE IF NOT EXISTS t (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            note TEXT
        )"""
    ])
    yield db
    db.close()


def test_sqlite_insert_returns_lastrowid(sqlite_db):
    cur = sqlite_db.execute("INSERT INTO t (name, count) VALUES (?, ?)", ("alpha", 1))
    assert cur.lastrowid == 1
    cur2 = sqlite_db.execute("INSERT INTO t (name, count) VALUES (?, ?)", ("beta", 2))
    assert cur2.lastrowid == 2


def test_sqlite_select_fetchone(sqlite_db):
    sqlite_db.execute("INSERT INTO t (name, count) VALUES (?, ?)", ("alpha", 42))
    row = sqlite_db.execute("SELECT * FROM t WHERE name=?", ("alpha",)).fetchone()
    assert row is not None
    assert row["name"] == "alpha"
    assert row["count"] == 42
    assert row["note"] is None


def test_sqlite_select_fetchall(sqlite_db):
    sqlite_db.execute("INSERT INTO t (name, count) VALUES (?, ?)", ("a", 1))
    sqlite_db.execute("INSERT INTO t (name, count) VALUES (?, ?)", ("b", 2))
    rows = sqlite_db.execute("SELECT * FROM t ORDER BY name").fetchall()
    assert len(rows) == 2
    assert rows[0]["name"] == "a"
    assert rows[1]["name"] == "b"


def test_sqlite_update_rowcount(sqlite_db):
    sqlite_db.execute("INSERT INTO t (name, count) VALUES (?, ?)", ("x", 0))
    cur = sqlite_db.execute("UPDATE t SET count=? WHERE name=?", (99, "x"))
    assert cur.rowcount == 1


def test_sqlite_update_rowcount_zero_when_no_match(sqlite_db):
    cur = sqlite_db.execute("UPDATE t SET count=? WHERE name=?", (99, "nonexistent"))
    assert cur.rowcount == 0


def test_sqlite_count_star(sqlite_db):
    sqlite_db.execute("INSERT INTO t (name, count) VALUES (?, ?)", ("a", 1))
    sqlite_db.execute("INSERT INTO t (name, count) VALUES (?, ?)", ("b", 2))
    row = sqlite_db.execute("SELECT COUNT(*) AS n FROM t").fetchone()
    assert row is not None
    assert int(row["n"]) == 2


def test_init_db_creates_queries_table(tmp_path):
    db_path = tmp_path / "logs.db"
    init_db(db_path)
    db = _SqliteLogDb(db_path)
    try:
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='queries'"
        ).fetchone()
        assert row is not None
        assert row["name"] == "queries"
    finally:
        db.close()


def test_init_db_is_idempotent(tmp_path):
    db_path = tmp_path / "logs.db"
    init_db(db_path)
    init_db(db_path)  # second call should not raise


# ---------------------------------------------------------------------------
# _turso_arg type conversion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    (None,      {"type": "null",    "value": None}),
    (42,        {"type": "integer", "value": "42"}),
    (True,      {"type": "integer", "value": "1"}),
    (False,     {"type": "integer", "value": "0"}),
    (3.14,      {"type": "float",   "value": "3.14"}),
    ("hello",   {"type": "text",    "value": "hello"}),
    ("",        {"type": "text",    "value": ""}),
])
def test_turso_arg(value, expected):
    assert _turso_arg(value) == expected


# ---------------------------------------------------------------------------
# _turso_val type conversion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ({"type": "null",    "value": None},   None),
    ({"type": "integer", "value": "7"},    7),
    ({"type": "integer", "value": "0"},    0),
    ({"type": "float",   "value": "2.5"},  2.5),
    ({"type": "text",    "value": "hi"},   "hi"),
    ({"type": "text",    "value": ""},     ""),
    # Non-dict passthrough
    ("raw",  "raw"),
    (123,    123),
    (None,   None),
])
def test_turso_val(value, expected):
    assert _turso_val(value) == expected


# ---------------------------------------------------------------------------
# _TursoLogDb construction (no network)
# ---------------------------------------------------------------------------

def test_turso_url_scheme_normalisation():
    db = _TursoLogDb("libsql://mydb-org.turso.io", "token")
    assert db._pipeline_url == "https://mydb-org.turso.io/v2/pipeline"


def test_turso_https_url_unchanged():
    db = _TursoLogDb("https://mydb-org.turso.io", "token")
    assert db._pipeline_url == "https://mydb-org.turso.io/v2/pipeline"


def test_turso_close_is_noop():
    db = _TursoLogDb("libsql://mydb-org.turso.io", "token")
    db.close()  # should not raise
