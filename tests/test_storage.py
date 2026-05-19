from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from agent_context_platform.embeddings import EmbeddingIdentity
from agent_context_platform.models import AssetType, IndexedItem, SourceCitation, SourceType
from agent_context_platform.storage import Base, IndexedItemRepository, ItemEmbeddingRecord


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
    embedding_type = ItemEmbeddingRecord.__table__.c.embedding.type.compile(
        dialect=postgresql.dialect()
    )

    assert embedding_type == "VECTOR"


def test_item_embedding_table_keeps_dynamic_dimension_check() -> None:
    constraint_sql = {
        str(constraint.sqltext)
        for constraint in ItemEmbeddingRecord.__table__.constraints
        if hasattr(constraint, "sqltext")
    }

    assert "embedding IS NULL OR vector_dims(embedding) = dimension" in constraint_sql


def test_repository_stores_embeddings_by_provider_model_and_dimension() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    identity_v1 = EmbeddingIdentity(provider="dashscope", model="model-a", dimension=3)
    identity_v2 = EmbeddingIdentity(provider="dashscope", model="model-b", dimension=2)
    item = make_item(
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

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        repository.save(item, embedding=[0.1, 0.2, 0.3], embedding_identity=identity_v1)
        repository.save(item, embedding=[0.4, 0.5], embedding_identity=identity_v2)
        session.commit()

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        v1_results = repository.list_with_embeddings(
            asset_type=AssetType.CODE,
            embedding_identity=identity_v1,
        )
        v2_results = repository.list_with_embeddings(
            asset_type=AssetType.CODE,
            embedding_identity=identity_v2,
        )
        missing_results = repository.list_with_embeddings(
            asset_type=AssetType.CODE,
            embedding_identity=EmbeddingIdentity(
                provider="dashscope", model="model-c", dimension=3
            ),
        )

    assert v1_results == [(item, [0.1, 0.2, 0.3])]
    assert v2_results == [(item, [0.4, 0.5])]
    assert missing_results == [(item, None)]


def test_repository_rejects_embedding_identity_dimension_mismatch() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    item = make_item(
        "db_schema:payment_order",
        SourceCitation(source_type=SourceType.DB_SCHEMA, table="payment_order"),
        {},
    )

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        try:
            repository.save(
                item,
                embedding=[0.1, 0.2],
                embedding_identity=EmbeddingIdentity(
                    provider="dashscope", model="model-a", dimension=3
                ),
            )
        except ValueError as exc:
            assert "embedding dimension" in str(exc)
        else:
            raise AssertionError("expected embedding dimension mismatch")
