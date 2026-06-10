from __future__ import annotations

from datetime import datetime
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
    """检索结果的来源坐标。

    例子：
    - 代码：path + start_line/end_line + symbol 定位到一个 Java 方法。
    - 表结构：table/column 定位到数据库表或字段。
    - 文档：path + heading_path + 行号定位到 Markdown 小节。
    """

    model_config = ConfigDict(extra="forbid")

    # source_type 决定下面哪些定位字段是必填的。
    source_type: SourceType
    # repo 用于区分不同代码库或样本集，例如 "mvp-indexing"。
    repo: str | None = None
    # branch/commit_sha 是索引运行时 best-effort 采集的 Git 坐标；非 Git 目录允许为空。
    branch: str | None = None
    commit_sha: str | None = None
    # file_hash 记录索引时的文件内容指纹，后续用于判断证据是否可能过期。
    file_hash: str | None = None
    # indexed_at/index_batch_id 记录索引批次，便于调试 freshness 和批处理边界。
    indexed_at: datetime | None = None
    index_batch_id: str | None = None
    # path 是仓库内相对路径，例如 "src/main/java/example/PaymentService.java"。
    path: str | None = None
    # start_line/end_line 让 Agent 能回到原始文件核对证据。
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    # symbol 通常是类名或方法名，例如 "PaymentService.build"。
    symbol: str | None = None
    # table/column 用于 DB schema 资产，例如 table="payment_order"。
    table: str | None = None
    column: str | None = None
    # heading_path 用于文档资产，例如 "Payment Integration > Error Handling"。
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
    """索引后的最小工程资产。

    一个 Java method、一个 DB column、一个 Markdown section 都会变成 IndexedItem。
    后续 keyword search、embedding 和 TaskContext 都围绕这个结构工作。
    """

    model_config = ConfigDict(extra="forbid")

    # id 需要稳定可重建，例如 "code:<path>:PaymentService.build"。
    id: str = Field(min_length=1)
    # asset_type 决定它属于代码、表结构还是文档。
    asset_type: AssetType
    # title 是给检索和展示用的短名称，例如方法名、表名、章节名。
    title: str = Field(min_length=1)
    # content 是参与检索和 embedding 的主体文本。
    content: str = Field(min_length=1)
    # summary 提供短描述，让 embedding 不只依赖原文片段。
    summary: str = Field(min_length=1)
    # metadata 存放结构化补充字段，例如 language、symbol_type、columns。
    metadata: dict[str, Any] = Field(default_factory=dict)
    # source 是可追溯引用，必须和 asset_type 对应。
    source: SourceCitation

    @model_validator(mode="after")
    def validate_source_matches_asset_type(self) -> "IndexedItem":
        # 防止把 DB 来源包进 CODE item，这类错配会让 API filter 和 citation 都失真。
        if self.asset_type.value != self.source.source_type.value:
            raise ValueError("asset_type must match source.source_type")
        return self


class SearchResult(BaseModel):
    """一次检索命中的返回项。

    例子：item 是 PaymentService.build，score 是综合分，
    score_parts 可以解释 keyword/vector 各贡献多少。
    """

    model_config = ConfigDict(extra="forbid")

    item: IndexedItem
    # score 是最终排序分，当前由 retrieval.py 组合 keyword 与 vector 得出。
    score: float = Field(ge=0)
    # score_parts 用于调试召回质量，例如 {"keyword": 0.7, "vector": 0.3}。
    score_parts: dict[str, float] | None = None
    # match_reason 是给人看的命中解释，不作为排序依据。
    match_reason: str = Field(min_length=1)
    # source 冗余自 item.source，方便 API 调用方不用展开 item 也能拿来源。
    source: SourceCitation

    @model_validator(mode="after")
    def validate_result_source_matches_item_source(self) -> "SearchResult":
        # SearchResult 顶层 source 是给调用方快速读取的冗余字段，必须与 item.source 一致。
        if self.source != self.item.source:
            raise ValueError("search result source must match item.source")
        return self


class TaskContext(BaseModel):
    """给 Agent 的任务上下文包。

    build-task-context 会把同一个自然语言任务拆到代码、DB、文档和相似实现四类结果，
    再附上 risks/missing_context/citations，方便 Agent 判断上下文是否足够。
    """

    model_config = ConfigDict(extra="forbid")

    # query 保留原始任务描述，例如 "修改支付报文生成逻辑"。
    query: str = Field(min_length=1)
    # related_code 是直接相关的代码类/方法。
    related_code: list[SearchResult] = Field(default_factory=list)
    # related_db_schema 是相关表、字段和索引。
    related_db_schema: list[SearchResult] = Field(default_factory=list)
    # related_docs 是相关设计文档或说明章节。
    related_docs: list[SearchResult] = Field(default_factory=list)
    # similar_implementations 用于给 Agent 提供可参考的已有实现。
    similar_implementations: list[SearchResult] = Field(default_factory=list)
    # risks 记录上下文不足或召回缺口，调用方不应忽略。
    risks: list[str] = Field(default_factory=list)
    # missing_context 标记缺失的资产类型，例如 ["db_schema"]。
    missing_context: list[str] = Field(default_factory=list)
    # citations 汇总所有返回结果的来源，便于统一展示和审计。
    citations: list[SourceCitation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_citations_cover_results(self) -> "TaskContext":
        # 上下文包不能只携带自然语言结论，汇总 citations 必须覆盖所有返回结果。
        # 这个校验保证 Agent 展示的每个结果都有可审计来源。
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
