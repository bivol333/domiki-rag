"""Light-weight preprocessing of user queries before retrieval."""
import re
import unicodedata

from pydantic import BaseModel

from src.common.tokenizer import tokenize_greek

# Match the same patterns as structure_detector
_ARTICLE_RE = re.compile(r"[Άά]ρθρ[οο]\s+(\d+[α-ωΑ-Ω]?)", re.IGNORECASE | re.UNICODE)
_LAW_RE = re.compile(
    r"(?:Ν\.?(?:όμος)?|ν\.?(?:όμος)?)\s*(\d+)\s*/\s*(\d{2,4})",
    re.IGNORECASE | re.UNICODE,
)
_STOP_WORDS = frozenset(
    [
        "και", "ή", "αν", "για", "από", "με", "στο", "στη", "στα", "στον",
        "στους", "στις", "του", "της", "των", "τον", "την", "τα", "το",
        "που", "ότι", "ως", "μου", "μας", "σας", "τους", "τις", "να",
        "θα", "δε", "δεν", "μη", "μην", "είναι", "είναι", "έχει",
        "μπορώ", "μπορεί", "μπορούν", "πρέπει", "πώς", "ποια", "ποιο",
        "ποιος", "ποιοι", "ποιες",
    ]
)


def _expand_year(year: str) -> str:
    if len(year) == 2:
        return f"19{year}" if int(year) > 50 else f"20{year}"
    return year


class ProcessedQuery(BaseModel):
    raw: str
    normalized: str
    detected_articles: list[str]
    detected_law_refs: list[str]
    keywords: list[str]


def process_query(query: str) -> ProcessedQuery:
    """Normalize query and extract structure hints for retrieval filtering."""
    normalized = unicodedata.normalize("NFC", query.strip())

    articles = [f"Άρθρο {m.group(1)}" for m in _ARTICLE_RE.finditer(normalized)]

    law_refs = []
    for m in _LAW_RE.finditer(normalized):
        year = _expand_year(m.group(2))
        law_refs.append(f"Ν. {m.group(1)}/{year}")

    tokens = tokenize_greek(normalized)
    keywords = [t for t in tokens if t not in _STOP_WORDS and len(t) >= 3]

    return ProcessedQuery(
        raw=query,
        normalized=normalized,
        detected_articles=articles,
        detected_law_refs=law_refs,
        keywords=keywords,
    )
