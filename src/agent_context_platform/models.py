from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AssetType(str, Enum):
    CODE = "code"
    DB_SCHEMA = "db_schema"
    DOC = "doc"


class SourceType(str, Enum):
    CODE = "code"
    DB_SCHEMA = "db_schema"
    DOC = "doc"


class SourceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: SourceType
    repo: str | None = None
    path: str | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    symbol: str | None = None
    table: str | None = None
    column: str | None = None
    heading_path: str | None = None

    @model_validator(mode="after")
    def validate_required_reference_fields(self) -> "SourceCitation":
        # 来源引用是 Agent 的工程依据，按资产类型强制保留可追溯定位字段。
        if self.start_line is not None and self.end_line is not None:
            if self.end_line < self.start_line:
                raise ValueError("end_line must be greater than or equal to start_line")

        if self.source_type is SourceType.CODE:
            if not self.path or self.start_line is None or self.end_line is None:
                raise ValueError("code source requires path, start_line and end_line")

        if self.source_type is SourceType.DB_SCHEMA:
            if not self.table:
                raise ValueError("db_schema source requires table")
            if self.column and not self.table:
                raise ValueError("db_schema column source requires table")

        if self.source_type is SourceType.DOC:
            if (
                not self.path
                or not self.heading_path
                or self.start_line is None
                or self.end_line is None
            ):
                raise ValueError(
                    "doc source requires path, heading_path, start_line and end_line"
                )

        return self


class IndexedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    asset_type: AssetType
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: SourceCitation

    @model_validator(mode="after")
    def validate_source_matches_asset_type(self) -> "IndexedItem":
        if self.asset_type.value != self.source.source_type.value:
            raise ValueError("asset_type must match source.source_type")
        return self


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: IndexedItem
    score: float = Field(ge=0)
    score_parts: dict[str, float] | None = None
    match_reason: str = Field(min_length=1)
    source: SourceCitation

    @model_validator(mode="after")
    def validate_result_source_matches_item_source(self) -> "SearchResult":
        # SearchResult 顶层 source 是给调用方快速读取的冗余字段，必须与 item.source 一致。
        if self.source != self.item.source:
            raise ValueError("search result source must match item.source")
        return self


class TaskContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    related_code: list[SearchResult] = Field(default_factory=list)
    related_db_schema: list[SearchResult] = Field(default_factory=list)
    related_docs: list[SearchResult] = Field(default_factory=list)
    similar_implementations: list[SearchResult] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    missing_context: list[str] = Field(default_factory=list)
    citations: list[SourceCitation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_citations_cover_results(self) -> "TaskContext":
        # 上下文包不能只携带自然语言结论，汇总 citations 必须覆盖所有返回结果。
        result_sources = {
            result.source.model_dump_json()
            for result in (
                self.related_code
                + self.related_db_schema
                + self.related_docs
                + self.similar_implementations
            )
        }
        citation_sources = {citation.model_dump_json() for citation in self.citations}
        if not result_sources.issubset(citation_sources):
            raise ValueError("citations must include every returned result source")
        return self
