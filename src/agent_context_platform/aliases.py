from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AliasExpansion:
    term: str
    expands_to: tuple[str, ...]


class DomainVocabulary:
    def __init__(self, expansions: list[AliasExpansion] | None = None):
        self._expansions = tuple(expansions or ())

    @property
    def terms(self) -> tuple[str, ...]:
        values: list[str] = []
        for expansion in self._expansions:
            values.append(expansion.term)
            values.extend(expansion.expands_to)
        return tuple(values)

    def expand_query(self, query: str) -> list[AliasExpansion]:
        normalized = query.lower()
        matched: list[AliasExpansion] = []
        for expansion in self._expansions:
            if expansion.term.lower() in normalized:
                matched.append(expansion)
                continue
            if any(value.lower() in normalized for value in expansion.expands_to):
                matched.append(expansion)
        return matched

    @classmethod
    def empty(cls) -> "DomainVocabulary":
        return cls()

    @classmethod
    def from_file(cls, path: str | Path) -> "DomainVocabulary":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_mapping(raw)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any]) -> "DomainVocabulary":
        if not isinstance(raw, dict):
            raise ValueError("alias file must contain a JSON object")
        raw_aliases = raw.get("aliases", [])
        if not isinstance(raw_aliases, list):
            raise ValueError("aliases must be a list")

        expansions: list[AliasExpansion] = []
        for item in raw_aliases:
            if not isinstance(item, dict):
                raise ValueError("each alias entry must be an object")
            term = str(item.get("term", "")).strip()
            raw_expands_to = item.get("expands_to", [])
            if not isinstance(raw_expands_to, list):
                raise ValueError("alias expands_to must be a list")
            expands_to = tuple(
                str(value).strip()
                for value in raw_expands_to
                if str(value).strip()
            )
            if term and expands_to:
                expansions.append(AliasExpansion(term=term, expands_to=expands_to))
        return cls(expansions)
