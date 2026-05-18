"""Pydantic models for ingestion pipeline."""
from datetime import date
from typing import Literal

from pydantic import BaseModel

SourceType = Literal[
    "law",
    "presidential_decree",
    "fek",
    "circular",
    "court_decision",
    "ministerial_decision",
    "technical_spec",
    "other",
]
Scope = Literal["public", "private"]


class DocumentMetadata(BaseModel):
    source_file: str
    source_type: SourceType
    scope: Scope
    title: str | None = None
    law_number: str | None = None
    fek_ref: str | None = None
    issue_date: date | None = None
    issuing_body: str | None = None
    total_pages: int


class Chunk(BaseModel):
    chunk_id: str
    document: DocumentMetadata
    text: str
    page_start: int
    page_end: int
    article: str | None = None
    paragraph: str | None = None
    char_count: int
    token_count: int
