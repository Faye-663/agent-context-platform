from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from agent_context_platform.models import AssetType, IndexedItem, SourceCitation, SourceType
from agent_context_platform.storage import Base, IndexedItemRecord, IndexedItemRepository


def make_item(item_id: str, source: SourceCitation, metadata: dict[str, str]) -> IndexedItem:
    return IndexedItem(
        id=item_id,
        asset_type=AssetType(source.source_type.value),
        title=item_id,
        content=f"{item_id} searchable content",
        summary=f"{item_id} summary",
        metadata=metadata,
        source=source,
    )


def test_repository_inserts_and_reads_three_asset_types() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    code = make_item(
        "code:PaymentMessageBuilder.build",
        SourceCitation(
            source_type=SourceType.CODE,
            path="src/main/java/example/PaymentMessageBuilder.java",
            start_line=10,
            end_line=30,
            symbol="PaymentMessageBuilder.build",
        ),
        {"language": "java", "symbol_type": "method"},
    )
    schema = make_item(
        "db_schema:payment_order",
        SourceCitation(source_type=SourceType.DB_SCHEMA, table="payment_order"),
        {},
    )
    doc = make_item(
        "doc:payment-integration",
        SourceCitation(
            source_type=SourceType.DOC,
            path="docs/design/payment-integration.md",
            start_line=1,
            end_line=8,
            heading_path="Payment Integration",
        ),
        {},
    )

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        repository.save(code, embedding=[0.1, 0.2, 0.3])
        repository.save(schema)
        repository.save(doc)
        session.commit()

    with Session(engine) as session:
        repository = IndexedItemRepository(session)

        assert repository.get("code:PaymentMessageBuilder.build") == code
        assert repository.list(asset_type=AssetType.CODE) == [code]
        assert repository.list(
            path="src/main/java/example/PaymentMessageBuilder.java"
        ) == [code]
        assert repository.list(language="java") == [code]
        assert repository.list(symbol_type="method") == [code]
        assert repository.list(table="payment_order") == [schema]


def test_postgresql_table_contains_pgvector_embedding_column() -> None:
    embedding_type = IndexedItemRecord.__table__.c.embedding.type.compile(
        dialect=postgresql.dialect()
    )

    assert embedding_type == "VECTOR"
