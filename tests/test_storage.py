from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from agent_context_platform.embeddings import EmbeddingIdentity
from agent_context_platform.models import (
    AssetType,
    IndexedItem,
    SourceCitation,
    SourceType,
    SymbolCatalogEntry,
)
from agent_context_platform.storage import (
    Base,
    IndexedItemRepository,
    ItemEmbeddingRecord,
    build_pgvector_search_statement,
)


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


def make_symbol(
    symbol_id: str,
    *,
    repo: str = "gitlab.example.com/payments/payment-service",
    kind: str = "method",
    name: str = "build",
    qualified_name: str = "example.PaymentService.build(PaymentRequest)",
    source_item_id: str = "code:src/main/java/example/PaymentService.java:PaymentService.build",
) -> SymbolCatalogEntry:
    return SymbolCatalogEntry(
        symbol_id=symbol_id,
        repo=repo,
        path="src/main/java/example/PaymentService.java",
        language="java",
        kind=kind,
        name=name,
        qualified_name=qualified_name,
        start_line=10,
        end_line=18,
        source_item_id=source_item_id,
        branch="main",
        commit_sha="abc123",
        file_hash="f" * 64,
        indexed_at=datetime(2026, 6, 10, 8, 30, tzinfo=UTC),
        index_batch_id="batch-001",
    )


def test_repository_inserts_and_reads_three_asset_types() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    code = make_item(
        "code:PaymentMessageBuilder.build",
        SourceCitation(
            source_type=SourceType.CODE,
            repo="payment-service",
            branch="main",
            commit_sha="abc123",
            file_hash="f" * 64,
            indexed_at=datetime(2026, 6, 10, 8, 30, tzinfo=UTC),
            index_batch_id="batch-001",
            path="src/main/java/example/PaymentMessageBuilder.java",
            start_line=10,
            end_line=30,
            symbol="PaymentMessageBuilder.build",
        ),
        {"language": "java", "symbol_type": "method"},
    )
    schema = make_item(
        "db_schema:payment_order",
        SourceCitation(
            source_type=SourceType.DB_SCHEMA,
            repo="payment-service",
            table="payment_order",
        ),
        {},
    )
    doc = make_item(
        "doc:payment-integration",
        SourceCitation(
            source_type=SourceType.DOC,
            repo="payment-service",
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
        stored_code = repository.get("code:PaymentMessageBuilder.build")
        assert stored_code is not None
        assert stored_code.source.branch == "main"
        assert stored_code.source.commit_sha == "abc123"
        assert stored_code.source.file_hash == "f" * 64
        assert stored_code.source.indexed_at == datetime(2026, 6, 10, 8, 30, tzinfo=UTC)
        assert stored_code.source.index_batch_id == "batch-001"
        assert repository.list(language="java") == [code]
        assert repository.list(symbol_type="method") == [code]
        assert repository.list(table="payment_order") == [schema]


def test_repository_saves_and_looks_up_symbol_catalog_entries() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    item = make_item(
        "code:src/main/java/example/PaymentService.java:PaymentService.build",
        SourceCitation(
            source_type=SourceType.CODE,
            repo="gitlab.example.com/payments/payment-service",
            path="src/main/java/example/PaymentService.java",
            start_line=10,
            end_line=18,
            symbol="PaymentService.build",
        ),
        {"language": "java", "symbol_type": "method"},
    )
    symbol = make_symbol("java:method:example.PaymentService.build(PaymentRequest)")

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        repository.save(item)
        assert repository.save_symbols([symbol]) == 1
        session.commit()

    with Session(engine) as session:
        repository = IndexedItemRepository(session)

        assert repository.find_symbols_exact(
            repo="gitlab.example.com/payments/payment-service",
            query="example.PaymentService.build(PaymentRequest)",
        ) == [symbol]
        assert repository.find_symbols_prefix(
            repo="gitlab.example.com/payments/payment-service",
            query="example.Payment",
            kinds=["method"],
            language="java",
        ) == [symbol]
        assert repository.find_symbols_prefix(
            repo="gitlab.example.com/orders/order-service",
            query="example.Payment",
        ) == []


def test_repository_deletes_symbols_by_repo_path_without_touching_other_repos() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    payment_symbol = make_symbol(
        "java:class:example.PaymentService",
        kind="class",
        source_item_id=None,
    )
    order_symbol = make_symbol(
        "java:class:example.PaymentService",
        repo="gitlab.example.com/orders/order-service",
        kind="class",
        source_item_id=None,
    )

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        repository.save_symbols([payment_symbol, order_symbol])
        session.commit()

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        assert repository.delete_symbols_by_path(
            repo="gitlab.example.com/payments/payment-service",
            path="src/main/java/example/PaymentService.java",
        ) == 1
        session.commit()

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        assert repository.find_symbols_prefix(
            repo="gitlab.example.com/payments/payment-service",
            query="example.Payment",
        ) == []
        assert repository.find_symbols_prefix(
            repo="gitlab.example.com/orders/order-service",
            query="example.Payment",
        ) == [order_symbol]


def test_repository_keeps_same_item_id_isolated_by_repo() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    payment_item = make_item(
        "code:src/main/java/example/PaymentService.java:PaymentService.build",
        SourceCitation(
            source_type=SourceType.CODE,
            repo="gitlab.example.com/payments/payment-service",
            path="src/main/java/example/PaymentService.java",
            start_line=10,
            end_line=30,
            symbol="PaymentService.build",
        ),
        {"language": "java", "symbol_type": "method"},
    )
    order_item = make_item(
        "code:src/main/java/example/PaymentService.java:PaymentService.build",
        SourceCitation(
            source_type=SourceType.CODE,
            repo="gitlab.example.com/orders/order-service",
            path="src/main/java/example/PaymentService.java",
            start_line=40,
            end_line=60,
            symbol="PaymentService.build",
        ),
        {"language": "java", "symbol_type": "method"},
    )

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        repository.save(payment_item)
        repository.save(order_item)
        session.commit()

    with Session(engine) as session:
        repository = IndexedItemRepository(session)

        assert repository.get(payment_item.id, repo=payment_item.source.repo) == payment_item
        assert repository.get(order_item.id, repo=order_item.source.repo) == order_item
        assert repository.list(asset_type=AssetType.CODE, repo=payment_item.source.repo) == [
            payment_item
        ]
        assert repository.list(asset_type=AssetType.CODE, repo=order_item.source.repo) == [
            order_item
        ]


def test_repository_rejects_persisted_items_without_repo() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
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
        try:
            repository.save(item)
        except ValueError as exc:
            assert "repo" in str(exc)
        else:
            raise AssertionError("expected missing repo to be rejected")


def test_repository_lists_and_deletes_items_by_repo_path() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    identity = EmbeddingIdentity(provider="openai", model="model-a", dimension=3)
    payment_item = make_item(
        "code:PaymentService.build",
        SourceCitation(
            source_type=SourceType.CODE,
            repo="gitlab.example.com/payments/payment-service",
            path="src/main/java/example/PaymentService.java",
            start_line=10,
            end_line=30,
            symbol="PaymentService.build",
        ),
        {"language": "java", "symbol_type": "method"},
    )
    order_item = make_item(
        "code:PaymentService.build",
        SourceCitation(
            source_type=SourceType.CODE,
            repo="gitlab.example.com/orders/order-service",
            path="src/main/java/example/PaymentService.java",
            start_line=10,
            end_line=30,
            symbol="PaymentService.build",
        ),
        {"language": "java", "symbol_type": "method"},
    )
    other_path_item = make_item(
        "doc:Payment Guide",
        SourceCitation(
            source_type=SourceType.DOC,
            repo="gitlab.example.com/payments/payment-service",
            path="docs/payment.md",
            start_line=1,
            end_line=8,
            heading_path="Payment Guide",
        ),
        {},
    )

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        repository.save(payment_item, embedding=[1.0, 0.0, 0.0], embedding_identity=identity)
        repository.save(order_item, embedding=[0.0, 1.0, 0.0], embedding_identity=identity)
        repository.save(other_path_item)
        session.commit()

    with Session(engine) as session:
        repository = IndexedItemRepository(session)

        assert repository.list_paths(
            repo="gitlab.example.com/payments/payment-service",
            path_prefix="src/main/java/example/",
        ) == ["src/main/java/example/PaymentService.java"]
        assert repository.delete_by_path(
            repo="gitlab.example.com/payments/payment-service",
            path="src/main/java/example/PaymentService.java",
        ) == 1
        session.commit()

    with Session(engine) as session:
        repository = IndexedItemRepository(session)

        assert repository.list(repo="gitlab.example.com/payments/payment-service") == [
            other_path_item
        ]
        assert repository.list(repo="gitlab.example.com/orders/order-service") == [
            order_item
        ]
        assert repository.list_with_embeddings(
            repo="gitlab.example.com/payments/payment-service",
            embedding_identity=identity,
        ) == [(other_path_item, None)]
        assert repository.list_with_embeddings(
            repo="gitlab.example.com/orders/order-service",
            embedding_identity=identity,
        ) == [(order_item, [0.0, 1.0, 0.0])]


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
    identity_v1 = EmbeddingIdentity(provider="openai", model="model-a", dimension=3)
    identity_v2 = EmbeddingIdentity(provider="openai", model="model-b", dimension=2)
    item = make_item(
        "code:PaymentMessageBuilder.build",
        SourceCitation(
            source_type=SourceType.CODE,
            repo="payment-service",
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
                provider="openai", model="model-c", dimension=3
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
        SourceCitation(
            source_type=SourceType.DB_SCHEMA,
            repo="payment-service",
            table="payment_order",
        ),
        {},
    )

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        try:
            repository.save(
                item,
                embedding=[0.1, 0.2],
                embedding_identity=EmbeddingIdentity(
                    provider="openai", model="model-a", dimension=3
                ),
            )
        except ValueError as exc:
            assert "embedding dimension" in str(exc)
        else:
            raise AssertionError("expected embedding dimension mismatch")


def test_repository_vector_search_orders_filters_and_limits_candidates() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    identity = EmbeddingIdentity(provider="openai", model="model-a", dimension=3)
    other_identity = EmbeddingIdentity(provider="openai", model="model-b", dimension=3)
    matching = make_item(
        "code:InvoicePrinter.print",
        SourceCitation(
            source_type=SourceType.CODE,
            repo="gitlab.example.com/payments/payment-service",
            path="src/main/java/example/InvoicePrinter.java",
            start_line=5,
            end_line=18,
            symbol="InvoicePrinter.print",
        ),
        {"language": "java", "symbol_type": "method"},
    )
    second = make_item(
        "code:PaymentMessageBuilder.build",
        SourceCitation(
            source_type=SourceType.CODE,
            repo="gitlab.example.com/payments/payment-service",
            path="src/main/java/example/PaymentMessageBuilder.java",
            start_line=10,
            end_line=30,
            symbol="PaymentMessageBuilder.build",
        ),
        {"language": "java", "symbol_type": "method"},
    )
    filtered_out = make_item(
        "code:PythonHelper.build",
        SourceCitation(
            source_type=SourceType.CODE,
            repo="gitlab.example.com/tools/python-helper",
            path="src/PythonHelper.py",
            start_line=1,
            end_line=5,
            symbol="PythonHelper.build",
        ),
        {"language": "python", "symbol_type": "function"},
    )

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        repository.save(matching, embedding=[0.0, 1.0, 0.0], embedding_identity=identity)
        repository.save(second, embedding=[1.0, 0.0, 0.0], embedding_identity=identity)
        repository.save(
            filtered_out,
            embedding=[0.0, 1.0, 0.0],
            embedding_identity=identity,
        )
        repository.save(matching, embedding=[1.0, 0.0, 0.0], embedding_identity=other_identity)
        session.commit()

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        results = repository.search_by_vector(
            asset_type=AssetType.CODE,
            repo="gitlab.example.com/payments/payment-service",
            query_embedding=[0.0, 1.0, 0.0],
            embedding_identity=identity,
            language="java",
            symbol_types=["method"],
            limit=1,
        )

    assert [(item.id, score) for item, score in results] == [
        ("code:InvoicePrinter.print", 1.0)
    ]


def test_pgvector_search_statement_uses_cosine_distance_and_limit() -> None:
    identity = EmbeddingIdentity(provider="openai", model="model-a", dimension=3)

    statement = build_pgvector_search_statement(
        asset_type=AssetType.CODE,
        repo="gitlab.example.com/payments/payment-service",
        query_embedding=[0.0, 1.0, 0.0],
        embedding_identity=identity,
        language="java",
        symbol_types=["method"],
        limit=5,
    )

    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "item_embeddings.embedding <=>" in compiled
    assert "indexed_items.repo" in compiled
    assert "item_embeddings.provider" in compiled
    assert "item_embeddings.model" in compiled
    assert "item_embeddings.dimension" in compiled
    assert "LIMIT" in compiled


def test_repository_vector_search_rejects_query_dimension_mismatch() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    identity = EmbeddingIdentity(provider="openai", model="model-a", dimension=3)

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        try:
            repository.search_by_vector(
                asset_type=AssetType.CODE,
                query_embedding=[1.0, 0.0],
                embedding_identity=identity,
                limit=1,
            )
        except ValueError as exc:
            assert "embedding dimension" in str(exc)
        else:
            raise AssertionError("expected query embedding dimension mismatch")
