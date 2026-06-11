from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    JSON,
    String,
    Text,
    and_,
    create_engine,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from agent_context_platform.embeddings import EmbeddingIdentity
from agent_context_platform.models import AssetType, IndexedItem, SourceCitation, SourceType


JsonType = JSON().with_variant(JSONB, "postgresql")
EmbeddingType = VECTOR().with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    pass


class IndexedItemRecord(Base):
    """indexed_items 表的 ORM 映射。

    例子：Java 方法会保存为一行，title="PaymentService.build"，
    path/start_line/end_line/symbol 用来让 Agent 回到源码定位证据。
    """

    __tablename__ = "indexed_items"

    # indexed_items 保存“工程资产本体”和来源定位；embedding 作为可重建派生数据放到 item_embeddings。
    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    asset_type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    item_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JsonType, default=dict
    )

    source_type: Mapped[str] = mapped_column(String(32), index=True)
    repo: Mapped[str] = mapped_column(String(255), primary_key=True)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    index_batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    path: Mapped[str | None] = mapped_column(String(1000), index=True, nullable=True)
    start_line: Mapped[int | None] = mapped_column(nullable=True)
    end_line: Mapped[int | None] = mapped_column(nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(500), nullable=True)
    table_name: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    column_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    heading_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    language: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    symbol_type: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    @classmethod
    def from_indexed_item(cls, item: IndexedItem) -> "IndexedItemRecord":
        # 这是 domain model -> ORM row 的入口；调试字段丢失时优先看这里的映射。
        source = item.source
        metadata = dict(item.metadata)
        return cls(
            id=item.id,
            asset_type=item.asset_type.value,
            title=item.title,
            content=item.content,
            summary=item.summary,
            item_metadata=metadata,
            source_type=source.source_type.value,
            repo=source.repo,
            branch=source.branch,
            commit_sha=source.commit_sha,
            file_hash=source.file_hash,
            indexed_at=source.indexed_at,
            index_batch_id=source.index_batch_id,
            path=source.path,
            start_line=source.start_line,
            end_line=source.end_line,
            symbol=source.symbol,
            table_name=source.table,
            column_name=source.column,
            heading_path=source.heading_path,
            language=metadata.get("language"),
            symbol_type=metadata.get("symbol_type"),
        )

    def to_indexed_item(self) -> IndexedItem:
        # 数据库行重新组装成 Pydantic model，让 API/MCP 层不直接依赖 ORM 对象。
        source = SourceCitation(
            source_type=SourceType(self.source_type),
            repo=self.repo,
            branch=self.branch,
            commit_sha=self.commit_sha,
            file_hash=self.file_hash,
            indexed_at=_normalize_indexed_at(self.indexed_at),
            index_batch_id=self.index_batch_id,
            path=self.path,
            start_line=self.start_line,
            end_line=self.end_line,
            symbol=self.symbol,
            table=self.table_name,
            column=self.column_name,
            heading_path=self.heading_path,
        )
        return IndexedItem(
            id=self.id,
            asset_type=AssetType(self.asset_type),
            title=self.title,
            content=self.content,
            summary=self.summary,
            metadata=dict(self.item_metadata or {}),
            source=source,
        )


def _normalize_indexed_at(value: datetime | None) -> datetime | None:
    # SQLite 会把 timezone-aware datetime 读回 naive；统一补回 UTC，保持 API 输出稳定。
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class ItemEmbeddingRecord(Base):
    """item_embeddings 表的 ORM 映射。

    例子：同一个 item_id 可以同时保存 dashscope/1024 维和 fake/3 维两套向量。
    """

    __tablename__ = "item_embeddings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["repo", "item_id"],
            ["indexed_items.repo", "indexed_items.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("dimension > 0", name="ck_item_embeddings_dimension_positive"),
        CheckConstraint(
            "embedding IS NULL OR vector_dims(embedding) = dimension",
            name="ck_item_embeddings_vector_matches_dimension",
        ).ddl_if(dialect="postgresql"),
    )

    repo: Mapped[str] = mapped_column(String(255), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(255), primary_key=True)
    dimension: Mapped[int] = mapped_column(primary_key=True)
    # PostgreSQL 使用 pgvector，SQLite 使用 JSON；SQLite 路径只为测试和轻量验证保留。
    embedding: Mapped[list[float]] = mapped_column(EmbeddingType, nullable=False)


class IndexedItemRepository:
    def __init__(self, session: Session):
        self.session = session

    def save(
        self,
        item: IndexedItem,
        embedding: Sequence[float] | None = None,
        embedding_identity: EmbeddingIdentity | None = None,
    ) -> IndexedItem:
        if not item.source.repo:
            raise ValueError("indexed item source.repo is required for persistence")
        # 先写基础资产，再写 embedding；这样没有向量时也能完成 keyword/RAG 基础检索。
        record = IndexedItemRecord.from_indexed_item(item)
        self.session.merge(record)
        self.session.flush()
        if embedding is not None:
            identity = embedding_identity or _manual_embedding_identity(embedding)
            _validate_embedding_dimension(embedding, identity)
            self.session.merge(
                ItemEmbeddingRecord(
                    repo=record.repo,
                    item_id=item.id,
                    provider=identity.provider,
                    model=identity.model,
                    dimension=identity.dimension,
                    embedding=list(embedding),
                )
            )
            self.session.flush()
        return record.to_indexed_item()

    def get(self, item_id: str, *, repo: str | None = None) -> IndexedItem | None:
        if repo is not None:
            record = self.session.get(IndexedItemRecord, {"repo": repo, "id": item_id})
            return record.to_indexed_item() if record else None
        statement = (
            select(IndexedItemRecord)
            .where(IndexedItemRecord.id == item_id)
            .order_by(IndexedItemRecord.repo)
        )
        record = self.session.scalars(statement).first()
        return record.to_indexed_item() if record else None

    def list(
        self,
        *,
        repo: str | None = None,
        asset_type: AssetType | None = None,
        path: str | None = None,
        language: str | None = None,
        symbol_type: str | None = None,
        table: str | None = None,
    ) -> list[IndexedItem]:
        statement = select(IndexedItemRecord)
        if repo is not None:
            statement = statement.where(IndexedItemRecord.repo == repo)
        if asset_type is not None:
            statement = statement.where(IndexedItemRecord.asset_type == asset_type.value)
        if path is not None:
            statement = statement.where(IndexedItemRecord.path == path)
        if language is not None:
            statement = statement.where(IndexedItemRecord.language == language)
        if symbol_type is not None:
            statement = statement.where(IndexedItemRecord.symbol_type == symbol_type)
        if table is not None:
            statement = statement.where(IndexedItemRecord.table_name == table)

        records = self.session.scalars(statement.order_by(IndexedItemRecord.id)).all()
        return [record.to_indexed_item() for record in records]

    def list_paths(self, *, repo: str, path_prefix: str | None = None) -> list[str]:
        statement = (
            select(IndexedItemRecord.path)
            .where(IndexedItemRecord.repo == repo)
            .where(IndexedItemRecord.path.is_not(None))
            .distinct()
        )
        if path_prefix is not None:
            statement = statement.where(IndexedItemRecord.path.startswith(path_prefix))
        paths = self.session.scalars(statement.order_by(IndexedItemRecord.path)).all()
        return [path for path in paths if path is not None]

    def delete_by_path(self, *, repo: str, path: str) -> int:
        records = self.session.scalars(
            select(IndexedItemRecord)
            .where(IndexedItemRecord.repo == repo)
            .where(IndexedItemRecord.path == path)
            .order_by(IndexedItemRecord.id)
        ).all()
        return self._delete_records(records)

    def delete_by_path_prefix(self, *, repo: str, path_prefix: str) -> int:
        records = self.session.scalars(
            select(IndexedItemRecord)
            .where(IndexedItemRecord.repo == repo)
            .where(IndexedItemRecord.path.startswith(path_prefix))
            .order_by(IndexedItemRecord.id)
        ).all()
        return self._delete_records(records)

    def _delete_records(self, records: Sequence[IndexedItemRecord]) -> int:
        if not records:
            return 0
        # 测试和轻量 SQLite 路径不保证开启外键级联；先删 embedding，避免留下孤儿向量。
        for record in records:
            embedding_records = self.session.scalars(
                select(ItemEmbeddingRecord)
                .where(ItemEmbeddingRecord.repo == record.repo)
                .where(ItemEmbeddingRecord.item_id == record.id)
            ).all()
            for embedding_record in embedding_records:
                self.session.delete(embedding_record)
            self.session.delete(record)
        self.session.flush()
        return len(records)

    def list_with_embeddings(
        self,
        *,
        repo: str | None = None,
        asset_type: AssetType | None = None,
        path_prefix: str | None = None,
        language: str | None = None,
        symbol_types: Sequence[str] | None = None,
        table: str | None = None,
        embedding_identity: EmbeddingIdentity | None = None,
    ) -> list[tuple[IndexedItem, list[float] | None]]:
        # 检索层需要同时拿到模型对象和对应模型的 embedding，避免跨模型维度误比较。
        statement = select(IndexedItemRecord)
        if repo is not None:
            statement = statement.where(IndexedItemRecord.repo == repo)
        if asset_type is not None:
            statement = statement.where(IndexedItemRecord.asset_type == asset_type.value)
        if path_prefix is not None:
            statement = statement.where(IndexedItemRecord.path.startswith(path_prefix))
        if language is not None:
            statement = statement.where(IndexedItemRecord.language == language)
        if symbol_types:
            statement = statement.where(IndexedItemRecord.symbol_type.in_(symbol_types))
        if table is not None:
            statement = statement.where(IndexedItemRecord.table_name == table)

        records = self.session.scalars(statement.order_by(IndexedItemRecord.id)).all()
        return [
            (
                record.to_indexed_item(),
                self._find_embedding(record.repo, record.id, embedding_identity),
            )
            for record in records
        ]

    def _find_embedding(
        self,
        repo: str,
        item_id: str,
        embedding_identity: EmbeddingIdentity | None,
    ) -> list[float] | None:
        statement = select(ItemEmbeddingRecord).where(
            ItemEmbeddingRecord.repo == repo,
            ItemEmbeddingRecord.item_id == item_id,
        )
        if embedding_identity is not None:
            statement = statement.where(
                ItemEmbeddingRecord.provider == embedding_identity.provider,
                ItemEmbeddingRecord.model == embedding_identity.model,
                ItemEmbeddingRecord.dimension == embedding_identity.dimension,
            )
        statement = statement.order_by(
            ItemEmbeddingRecord.provider,
            ItemEmbeddingRecord.model,
            ItemEmbeddingRecord.dimension,
        )
        record = self.session.scalars(statement).first()
        return list(record.embedding) if record is not None else None

    def list_keyword_candidates(
        self,
        *,
        repo: str | None = None,
        asset_type: AssetType | None = None,
        path_prefix: str | None = None,
        language: str | None = None,
        symbol_types: Sequence[str] | None = None,
        table: str | None = None,
        keywords: Sequence[str] = (),
        limit: int = 10,
    ) -> list[IndexedItem]:
        if limit <= 0 or not keywords:
            return []

        # keyword 召回先用结构化过滤缩小范围，再做 LIKE；这是 grep-like 检索进入 RAG 的位置。
        statement = _apply_item_filters(
            select(IndexedItemRecord),
            repo=repo,
            asset_type=asset_type,
            path_prefix=path_prefix,
            language=language,
            symbol_types=symbol_types,
            table=table,
        )
        keyword_conditions = []
        for keyword in keywords:
            pattern = f"%{keyword.lower()}%"
            keyword_conditions.extend(
                [
                    func.lower(IndexedItemRecord.title).like(pattern),
                    func.lower(IndexedItemRecord.content).like(pattern),
                    func.lower(IndexedItemRecord.summary).like(pattern),
                    func.lower(IndexedItemRecord.symbol).like(pattern),
                    func.lower(IndexedItemRecord.table_name).like(pattern),
                    func.lower(IndexedItemRecord.heading_path).like(pattern),
                    func.lower(IndexedItemRecord.path).like(pattern),
                ]
            )
        statement = statement.where(or_(*keyword_conditions))
        records = self.session.scalars(
            statement.order_by(IndexedItemRecord.id).limit(limit)
        ).all()
        return [record.to_indexed_item() for record in records]

    def search_by_vector(
        self,
        *,
        repo: str | None = None,
        asset_type: AssetType | None = None,
        path_prefix: str | None = None,
        language: str | None = None,
        symbol_types: Sequence[str] | None = None,
        table: str | None = None,
        query_embedding: Sequence[float],
        embedding_identity: EmbeddingIdentity | None = None,
        limit: int = 10,
    ) -> list[tuple[IndexedItem, float]]:
        if limit <= 0:
            return []
        if embedding_identity is not None:
            _validate_embedding_dimension(query_embedding, embedding_identity)

        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            # 真实检索路径使用数据库侧 pgvector 排序，避免把全量向量拉回 Python。
            statement = build_pgvector_search_statement(
                asset_type=asset_type,
                repo=repo,
                path_prefix=path_prefix,
                language=language,
                symbol_types=symbol_types,
                table=table,
                query_embedding=query_embedding,
                embedding_identity=embedding_identity,
                limit=limit,
            )
            rows = self.session.execute(statement).all()
            return [
                (record.to_indexed_item(), _cosine_distance_to_score(distance))
                for record, distance in rows
            ]

        # SQLite 没有 pgvector 算子，测试路径退回 Python cosine，便于单元测试不依赖 PostgreSQL。
        candidates = self.list_with_embeddings(
            asset_type=asset_type,
            repo=repo,
            path_prefix=path_prefix,
            language=language,
            symbol_types=symbol_types,
            table=table,
            embedding_identity=embedding_identity,
        )
        scored = [
            (item, _cosine_similarity(query_embedding, embedding))
            for item, embedding in candidates
        ]
        return [
            (item, score)
            for item, score in sorted(scored, key=lambda row: (-row[1], row[0].id))
            if score > 0
        ][:limit]


def _manual_embedding_identity(embedding: Sequence[float]) -> EmbeddingIdentity:
    return EmbeddingIdentity(
        provider="manual",
        model=f"dimension-{len(embedding)}",
        dimension=len(embedding),
    )


def _validate_embedding_dimension(
    embedding: Sequence[float], identity: EmbeddingIdentity
) -> None:
    if len(embedding) != identity.dimension:
        raise ValueError(
            "embedding dimension mismatch: "
            f"expected {identity.dimension}, got {len(embedding)}"
        )


def build_pgvector_search_statement(
    *,
    repo: str | None = None,
    asset_type: AssetType | None = None,
    path_prefix: str | None = None,
    language: str | None = None,
    symbol_types: Sequence[str] | None = None,
    table: str | None = None,
    query_embedding: Sequence[float],
    embedding_identity: EmbeddingIdentity | None = None,
    limit: int = 10,
):
    # 单独构造 SQL 方便测试断言是否真的使用 pgvector cosine_distance，而不是误走 Python fallback。
    distance = ItemEmbeddingRecord.embedding.cosine_distance(list(query_embedding)).label(
        "distance"
    )
    statement = select(IndexedItemRecord, distance).join(
        ItemEmbeddingRecord,
        and_(
            ItemEmbeddingRecord.repo == IndexedItemRecord.repo,
            ItemEmbeddingRecord.item_id == IndexedItemRecord.id,
        ),
    )
    statement = _apply_item_filters(
        statement,
        repo=repo,
        asset_type=asset_type,
        path_prefix=path_prefix,
        language=language,
        symbol_types=symbol_types,
        table=table,
    )
    if embedding_identity is not None:
        statement = statement.where(
            ItemEmbeddingRecord.provider == embedding_identity.provider,
            ItemEmbeddingRecord.model == embedding_identity.model,
            ItemEmbeddingRecord.dimension == embedding_identity.dimension,
        )
    return statement.order_by(distance, IndexedItemRecord.id).limit(limit)


def _apply_item_filters(
    statement,
    *,
    repo: str | None,
    asset_type: AssetType | None,
    path_prefix: str | None,
    language: str | None,
    symbol_types: Sequence[str] | None,
    table: str | None,
):
    if repo is not None:
        statement = statement.where(IndexedItemRecord.repo == repo)
    if asset_type is not None:
        statement = statement.where(IndexedItemRecord.asset_type == asset_type.value)
    if path_prefix is not None:
        statement = statement.where(IndexedItemRecord.path.startswith(path_prefix))
    if language is not None:
        statement = statement.where(IndexedItemRecord.language == language)
    if symbol_types:
        statement = statement.where(IndexedItemRecord.symbol_type.in_(symbol_types))
    if table is not None:
        statement = statement.where(IndexedItemRecord.table_name == table)
    return statement


def _cosine_distance_to_score(distance: float | None) -> float:
    if distance is None:
        return 0.0
    return round(max(0.0, 1.0 - float(distance)), 6)


def _cosine_similarity(
    query_embedding: Sequence[float], item_embedding: Sequence[float] | None
) -> float:
    if not query_embedding or not item_embedding:
        return 0.0
    if len(query_embedding) != len(item_embedding):
        return 0.0

    dot = sum(left * right for left, right in zip(query_embedding, item_embedding))
    query_norm = math.sqrt(sum(value * value for value in query_embedding))
    item_norm = math.sqrt(sum(value * value for value in item_embedding))
    if query_norm == 0 or item_norm == 0:
        return 0.0
    return round(max(0.0, dot / (query_norm * item_norm)), 6)


def make_engine(database_url: str, *, echo: bool = False) -> Engine:
    return create_engine(database_url, echo=echo, future=True)
