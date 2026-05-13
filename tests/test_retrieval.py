from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent_context_platform.models import AssetType, IndexedItem, SourceCitation, SourceType
from agent_context_platform.retrieval import HybridSearchQuery, HybridSearchService
from agent_context_platform.storage import Base, IndexedItemRepository


def make_item(
    item_id: str,
    asset_type: AssetType,
    title: str,
    content: str,
    source: SourceCitation,
    metadata: dict[str, object] | None = None,
) -> IndexedItem:
    return IndexedItem(
        id=item_id,
        asset_type=asset_type,
        title=title,
        content=content,
        summary=f"{title} summary",
        metadata=metadata or {},
        source=source,
    )


def make_service() -> HybridSearchService:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    repository = IndexedItemRepository(session)

    repository.save(
        make_item(
            "code:PaymentMessageBuilder.build",
            AssetType.CODE,
            "PaymentMessageBuilder.build",
            "build payment message from order data",
            SourceCitation(
                source_type=SourceType.CODE,
                path="src/main/java/example/PaymentMessageBuilder.java",
                start_line=10,
                end_line=30,
                symbol="PaymentMessageBuilder.build",
            ),
            {"language": "java", "symbol_type": "method"},
        ),
        embedding=[1.0, 0.0, 0.0],
    )
    repository.save(
        make_item(
            "code:InvoicePrinter.print",
            AssetType.CODE,
            "InvoicePrinter.print",
            "print invoice document",
            SourceCitation(
                source_type=SourceType.CODE,
                path="src/main/java/example/InvoicePrinter.java",
                start_line=5,
                end_line=18,
                symbol="InvoicePrinter.print",
            ),
            {"language": "java", "symbol_type": "method"},
        ),
        embedding=[0.0, 1.0, 0.0],
    )
    repository.save(
        make_item(
            "db_schema:payment_order",
            AssetType.DB_SCHEMA,
            "payment_order",
            "payment order status amount",
            SourceCitation(source_type=SourceType.DB_SCHEMA, table="payment_order"),
            {"symbol_type": "table", "table": "payment_order"},
        ),
        embedding=[1.0, 0.0, 0.0],
    )
    repository.save(
        make_item(
            "doc:payment-integration",
            AssetType.DOC,
            "Payment Integration",
            "payment integration message generation",
            SourceCitation(
                source_type=SourceType.DOC,
                path="docs/payment.md",
                start_line=1,
                end_line=8,
                heading_path="Payment Integration",
            ),
        ),
        embedding=[1.0, 0.0, 0.0],
    )
    session.commit()

    return HybridSearchService(repository)


def test_hybrid_search_prioritizes_keyword_hits_and_explains_score() -> None:
    service = make_service()

    results = service.search(
        HybridSearchQuery(
            query="payment message build",
            asset_type=AssetType.CODE,
            limit=2,
        )
    )

    assert results[0].item.id == "code:PaymentMessageBuilder.build"
    assert len(results) == 1
    assert results[0].score_parts is not None
    assert results[0].score_parts["keyword"] > 0
    assert "keyword" in results[0].match_reason


def test_hybrid_search_keeps_structured_filters_inside_requested_asset_type() -> None:
    service = make_service()

    code_results = service.search(
        HybridSearchQuery(
            query="payment",
            asset_type=AssetType.CODE,
            filters={"language": "java", "symbol_type": ["method"]},
        )
    )
    schema_results = service.search(
        HybridSearchQuery(
            query="payment",
            asset_type=AssetType.DB_SCHEMA,
            filters={"table": "payment_order"},
        )
    )

    assert {result.item.asset_type for result in code_results} == {AssetType.CODE}
    assert {result.item.source.symbol for result in code_results} == {
        "PaymentMessageBuilder.build"
    }
    assert {result.item.asset_type for result in schema_results} == {
        AssetType.DB_SCHEMA
    }
    assert schema_results[0].item.source.table == "payment_order"


def test_hybrid_search_combines_vector_similarity_with_keyword_score() -> None:
    service = make_service()

    results = service.search(
        HybridSearchQuery(
            query="unmatched text",
            asset_type=AssetType.CODE,
            query_embedding=[0.0, 1.0, 0.0],
            limit=2,
        )
    )

    assert results[0].item.id == "code:InvoicePrinter.print"
    assert results[0].score_parts is not None
    assert results[0].score_parts["vector"] == 1.0
