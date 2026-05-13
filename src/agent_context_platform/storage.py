from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import JSON, String, Text, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from agent_context_platform.models import AssetType, IndexedItem, SourceCitation, SourceType


JsonType = JSON().with_variant(JSONB, "postgresql")
EmbeddingType = VECTOR().with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    pass


class IndexedItemRecord(Base):
    __tablename__ = "indexed_items"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    asset_type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    item_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JsonType, default=dict
    )
    embedding: Mapped[list[float] | None] = mapped_column(EmbeddingType, nullable=True)

    source_type: Mapped[str] = mapped_column(String(32), index=True)
    repo: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
    def from_indexed_item(
        cls, item: IndexedItem, embedding: Sequence[float] | None = None
    ) -> "IndexedItemRecord":
        source = item.source
        metadata = dict(item.metadata)
        return cls(
            id=item.id,
            asset_type=item.asset_type.value,
            title=item.title,
            content=item.content,
            summary=item.summary,
            item_metadata=metadata,
            embedding=list(embedding) if embedding is not None else None,
            source_type=source.source_type.value,
            repo=source.repo,
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
        source = SourceCitation(
            source_type=SourceType(self.source_type),
            repo=self.repo,
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


class IndexedItemRepository:
    def __init__(self, session: Session):
        self.session = session

    def save(
        self, item: IndexedItem, embedding: Sequence[float] | None = None
    ) -> IndexedItem:
        record = IndexedItemRecord.from_indexed_item(item, embedding=embedding)
        self.session.merge(record)
        self.session.flush()
        return record.to_indexed_item()

    def get(self, item_id: str) -> IndexedItem | None:
        record = self.session.get(IndexedItemRecord, item_id)
        return record.to_indexed_item() if record else None

    def list(
        self,
        *,
        asset_type: AssetType | None = None,
        path: str | None = None,
        language: str | None = None,
        symbol_type: str | None = None,
        table: str | None = None,
    ) -> list[IndexedItem]:
        statement = select(IndexedItemRecord)
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


def make_engine(database_url: str, *, echo: bool = False) -> Engine:
    return create_engine(database_url, echo=echo, future=True)
