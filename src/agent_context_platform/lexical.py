from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from agent_context_platform.models import IndexedItem


_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[._:-][A-Za-z0-9]+)*|[0-9]+")
_CHINESE_SEGMENT_RE = re.compile(r"[\u4e00-\u9fff]+")
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_SEPARATORS_RE = re.compile(r"[._:/\\#@$+,\-\s]+")


@dataclass(frozen=True)
class LexicalTokenSet:
    tokens: tuple[str, ...]
    symbol_terms: tuple[str, ...]


@dataclass(frozen=True)
class LexicalScore:
    score: float
    raw_score: float
    matched_tokens: tuple[str, ...]
    matched_fields: tuple[str, ...]


@dataclass(frozen=True)
class FieldTokens:
    field: str
    weight: float
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class CandidateDocument:
    item: IndexedItem
    fields: tuple[FieldTokens, ...]
    token_counts: Counter[str] = field(init=False)
    field_hits: dict[str, set[str]] = field(init=False)
    length: float = field(init=False)

    def __post_init__(self) -> None:
        counts: Counter[str] = Counter()
        field_hits: dict[str, set[str]] = {}
        length = 0.0
        for field_tokens in self.fields:
            field_counter = Counter(field_tokens.tokens)
            for token, count in field_counter.items():
                counts[token] += count * field_tokens.weight
                field_hits.setdefault(token, set()).add(field_tokens.field)
                length += count * field_tokens.weight
        object.__setattr__(self, "token_counts", counts)
        object.__setattr__(self, "field_hits", field_hits)
        object.__setattr__(self, "length", max(length, 1.0))


def tokenize_query(text: str, domain_terms: tuple[str, ...] = ()) -> LexicalTokenSet:
    tokens = _tokenize_text(text, domain_terms=domain_terms)
    return LexicalTokenSet(
        tokens=tuple(sorted(set(tokens))),
        symbol_terms=tuple(sorted(_symbol_terms(text))),
    )


def tokenize_item(item: IndexedItem, domain_terms: tuple[str, ...] = ()) -> CandidateDocument:
    fields = [
        FieldTokens("title", 3.0, tuple(_tokenize_text(item.title, domain_terms=domain_terms))),
        FieldTokens(
            "summary", 1.8, tuple(_tokenize_text(item.summary, domain_terms=domain_terms))
        ),
        FieldTokens(
            "content", 1.0, tuple(_tokenize_text(item.content, domain_terms=domain_terms))
        ),
        FieldTokens(
            "metadata", 1.5, tuple(_tokenize_metadata(item.metadata, domain_terms))
        ),
    ]
    source = item.source
    if source.symbol:
        fields.append(
            FieldTokens(
                "symbol", 4.0, tuple(_tokenize_text(source.symbol, domain_terms=domain_terms))
            )
        )
    if source.table:
        fields.append(
            FieldTokens(
                "table", 4.0, tuple(_tokenize_text(source.table, domain_terms=domain_terms))
            )
        )
    if source.column:
        fields.append(
            FieldTokens(
                "column", 4.0, tuple(_tokenize_text(source.column, domain_terms=domain_terms))
            )
        )
    if source.heading_path:
        fields.append(
            FieldTokens(
                "heading_path",
                3.0,
                tuple(_tokenize_text(source.heading_path, domain_terms=domain_terms)),
            )
        )
    if source.path:
        fields.append(
            FieldTokens("path", 1.2, tuple(_tokenize_text(source.path, domain_terms=domain_terms)))
        )
    return CandidateDocument(item=item, fields=tuple(fields))


def score_documents(
    query_tokens: tuple[str, ...],
    items: list[IndexedItem],
    *,
    domain_terms: tuple[str, ...] = (),
) -> dict[tuple[str | None, str], LexicalScore]:
    if not query_tokens or not items:
        return {}

    documents = [tokenize_item(item, domain_terms=domain_terms) for item in items]
    document_frequency: Counter[str] = Counter()
    for document in documents:
        for token in set(document.token_counts):
            document_frequency[token] += 1

    average_length = sum(document.length for document in documents) / len(documents)
    raw_scores: dict[tuple[str | None, str], LexicalScore] = {}
    for document in documents:
        raw_score = 0.0
        matched_tokens: set[str] = set()
        matched_fields: set[str] = set()
        for token in query_tokens:
            term_frequency = document.token_counts.get(token, 0.0)
            if term_frequency <= 0:
                continue
            matched_tokens.add(token)
            matched_fields.update(document.field_hits.get(token, set()))
            idf = math.log(
                1.0
                + (len(documents) - document_frequency[token] + 0.5)
                / (document_frequency[token] + 0.5)
            )
            raw_score += idf * _bm25_tf(term_frequency, document.length, average_length)
        if raw_score <= 0:
            continue
        raw_scores[(document.item.source.repo, document.item.id)] = LexicalScore(
            score=raw_score,
            raw_score=raw_score,
            matched_tokens=tuple(sorted(matched_tokens)),
            matched_fields=tuple(sorted(matched_fields)),
        )

    if not raw_scores:
        return {}
    max_score = max(score.raw_score for score in raw_scores.values())
    return {
        key: LexicalScore(
            score=round(score.raw_score / max_score, 6),
            raw_score=round(score.raw_score, 6),
            matched_tokens=score.matched_tokens,
            matched_fields=score.matched_fields,
        )
        for key, score in raw_scores.items()
    }


def _bm25_tf(
    term_frequency: float,
    document_length: float,
    average_document_length: float,
    *,
    k1: float = 1.2,
    b: float = 0.75,
) -> float:
    denominator = term_frequency + k1 * (
        1.0 - b + b * (document_length / max(average_document_length, 1.0))
    )
    return (term_frequency * (k1 + 1.0)) / denominator


def _tokenize_metadata(metadata: dict[str, Any], domain_terms: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for value in metadata.values():
        if isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value)
        elif isinstance(value, dict):
            values.extend(str(item) for item in value.values())
        else:
            values.append(str(value))
    return _tokenize_text(" ".join(values), domain_terms=domain_terms)


def _tokenize_text(text: str, *, domain_terms: tuple[str, ...] = ()) -> list[str]:
    normalized_domain_terms = {
        term.strip().lower() for term in domain_terms if len(term.strip()) > 1
    }
    tokens: list[str] = []
    lowered = text.lower()
    for term in normalized_domain_terms:
        if term in lowered:
            tokens.extend(_tokenize_domain_term(term))

    for match in _ASCII_TOKEN_RE.finditer(text):
        tokens.extend(_split_engineering_token(match.group(0)))

    for segment in _CHINESE_SEGMENT_RE.findall(text):
        tokens.extend(_split_chinese_segment(segment, normalized_domain_terms))

    return [token for token in tokens if len(token) > 1]


def _split_engineering_token(token: str) -> list[str]:
    pieces: list[str] = []
    raw_parts = [part for part in _SEPARATORS_RE.split(token) if part]
    for raw_part in raw_parts:
        pieces.append(raw_part.lower())
        pieces.extend(part.lower() for part in _CAMEL_BOUNDARY_RE.split(raw_part) if part)
    if len(raw_parts) > 1:
        pieces.append(".".join(part.lower() for part in raw_parts))
    return sorted(set(piece for piece in pieces if len(piece) > 1))


def _split_chinese_segment(segment: str, domain_terms: set[str]) -> list[str]:
    tokens: list[str] = []
    lowered = segment.lower()
    for term in domain_terms:
        if _contains_chinese(term) and term in lowered:
            tokens.append(term)
    if len(segment) > 1:
        tokens.append(lowered)
        tokens.extend(lowered[index : index + 2] for index in range(len(lowered) - 1))
    return tokens


def _tokenize_domain_term(term: str) -> list[str]:
    if _contains_chinese(term):
        return _split_chinese_segment(term, {term})
    return _split_engineering_token(term)


def _symbol_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for match in _ASCII_TOKEN_RE.finditer(text):
        token = match.group(0).strip()
        if len(token) <= 1:
            continue
        terms.add(token)
        terms.add(token.lower())
        terms.update(_split_engineering_token(token))
    return terms


def _contains_chinese(text: str) -> bool:
    return bool(_CHINESE_SEGMENT_RE.search(text))
