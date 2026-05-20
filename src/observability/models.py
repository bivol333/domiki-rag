"""Pydantic models for the query log."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Feedback = Literal["positive", "negative"]


class QueryLogEntry(BaseModel):
    id: int | None = None
    timestamp: datetime
    session_id: str
    query: str
    answer: str
    chunks_used: list[dict]
    refused: bool
    feedback: Feedback | None = None
    feedback_comment: str | None = None
