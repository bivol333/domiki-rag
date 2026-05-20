"""QueryLogger: persist queries, answers, and feedback to SQLite."""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

from src.generation.models import AnswerResponse
from src.observability.database import DEFAULT_DB_PATH, get_connection, init_db
from src.observability.models import QueryLogEntry

logger = logging.getLogger(__name__)


def _chunks_metadata(response: AnswerResponse) -> list[dict]:
    """Reduce source_chunks to small per-row JSON: id, article, law, pages."""
    out: list[dict] = []
    for rh in response.source_chunks:
        h = rh.hit
        out.append({
            "chunk_id": h.chunk_id,
            "article": h.article,
            "law_number": h.law_number,
            "paragraph": h.paragraph,
            "page_start": h.page_start,
            "page_end": h.page_end,
            "source_file": h.source_file,
            "rerank_score": rh.rerank_score,
        })
    return out


def _row_to_entry(row) -> QueryLogEntry:
    return QueryLogEntry(
        id=row["id"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        session_id=row["session_id"],
        query=row["query"],
        answer=row["answer"],
        chunks_used=json.loads(row["chunks_used"]),
        refused=bool(row["refused"]),
        feedback=row["feedback"],
        feedback_comment=row["feedback_comment"],
    )


class QueryLogger:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            init_db(self.db_path)

    def log(self, session_id: str, query: str, response: AnswerResponse) -> int:
        """Insert a new row. Returns the row id."""
        timestamp = datetime.now().isoformat()
        chunks_json = json.dumps(_chunks_metadata(response), ensure_ascii=False)
        conn = get_connection(self.db_path)
        try:
            cursor = conn.execute(
                """
                INSERT INTO queries
                    (timestamp, session_id, query, answer, chunks_used, refused)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    session_id,
                    query,
                    response.answer_text,
                    chunks_json,
                    1 if response.refused else 0,
                ),
            )
            query_id = cursor.lastrowid
        finally:
            conn.close()
        logger.info("Logged query id=%d session=%s", query_id, session_id[:12])
        return query_id

    def add_feedback(
        self,
        query_id: int,
        feedback: Literal["positive", "negative"],
        comment: str | None = None,
    ) -> None:
        """Set feedback for a row. Overwrites existing feedback if present."""
        if feedback not in ("positive", "negative"):
            raise ValueError(f"feedback must be 'positive' or 'negative', got {feedback!r}")
        conn = get_connection(self.db_path)
        try:
            cursor = conn.execute(
                "UPDATE queries SET feedback=?, feedback_comment=? WHERE id=?",
                (feedback, comment, query_id),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"No query with id={query_id}")
        finally:
            conn.close()

    def get_by_id(self, query_id: int) -> QueryLogEntry | None:
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM queries WHERE id=?", (query_id,),
            ).fetchone()
        finally:
            conn.close()
        return _row_to_entry(row) if row else None

    def get_session_history(
        self,
        session_id: str,
        limit: int = 20,
    ) -> list[QueryLogEntry]:
        """Most recent first."""
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT * FROM queries
                WHERE session_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        finally:
            conn.close()
        return [_row_to_entry(r) for r in rows]

    def _build_filters(
        self,
        refused_only: bool,
        feedback_filter: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> tuple[str, list]:
        clauses: list[str] = []
        params: list = []
        if refused_only:
            clauses.append("refused=1")
        if feedback_filter is not None:
            if feedback_filter == "none":
                clauses.append("feedback IS NULL")
            else:
                clauses.append("feedback=?")
                params.append(feedback_filter)
        if date_from is not None:
            clauses.append("timestamp >= ?")
            params.append(date_from.isoformat())
        if date_to is not None:
            clauses.append("timestamp <= ?")
            params.append(date_to.isoformat())
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    def get_all_queries(
        self,
        limit: int = 100,
        offset: int = 0,
        refused_only: bool = False,
        feedback_filter: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[QueryLogEntry]:
        """For admin view. feedback_filter: 'positive', 'negative', 'none', or None."""
        where, params = self._build_filters(refused_only, feedback_filter, date_from, date_to)
        sql = f"SELECT * FROM queries{where} ORDER BY id DESC LIMIT ? OFFSET ?"
        conn = get_connection(self.db_path)
        try:
            rows = conn.execute(sql, (*params, limit, offset)).fetchall()
        finally:
            conn.close()
        return [_row_to_entry(r) for r in rows]

    def count_total(
        self,
        refused_only: bool = False,
        feedback_filter: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        where, params = self._build_filters(refused_only, feedback_filter, date_from, date_to)
        sql = f"SELECT COUNT(*) AS n FROM queries{where}"
        conn = get_connection(self.db_path)
        try:
            row = conn.execute(sql, params).fetchone()
        finally:
            conn.close()
        return int(row["n"])
