"""SQLite connection helper and schema initialization for query logs."""
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/logs.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    session_id TEXT NOT NULL,
    query TEXT NOT NULL,
    answer TEXT NOT NULL,
    chunks_used TEXT NOT NULL,
    refused INTEGER NOT NULL,
    feedback TEXT,
    feedback_comment TEXT
);

CREATE INDEX IF NOT EXISTS idx_timestamp ON queries(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_session ON queries(session_id);
CREATE INDEX IF NOT EXISTS idx_refused ON queries(refused);
CREATE INDEX IF NOT EXISTS idx_feedback ON queries(feedback);
"""


def get_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode and sensible defaults."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(db_path),
        timeout=10.0,
        isolation_level=None,  # autocommit; explicit transactions via BEGIN/COMMIT
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path = DEFAULT_DB_PATH) -> None:
    """Create the schema if missing. Idempotent."""
    conn = get_connection(db_path)
    try:
        conn.executescript(_SCHEMA)
        logger.info("Initialized query log database at %s", db_path)
    finally:
        conn.close()
