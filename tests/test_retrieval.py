from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent_context_platform.aliases import DomainVocabulary
from agent_context_platform.embeddings import EmbeddingIdentity
from agent_context_platform.models import (
    AssetType,
    IndexedItem,
    SourceCitation,
    SourceType,
    SymbolCatalogEntry,
)
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
                repo="gitlab.example.com/payments/payment-service",
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
                repo="gitlab.example.com/payments/payment-service",
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
            SourceCitation(
                source_type=SourceType.DB_SCHEMA,
                repo="gitlab.example.com/payments/payment-service",
                table="payment_order",
            ),
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
                repo="gitlab.example.com/payments/payment-service",
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


def test_hybrid_search_filters_candidates_by_repo() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    repository = IndexedItemRepository(session)

    for repo, path, line_start in [
        (
            "gitlab.example.com/payments/payment-service",
            "src/main/java/example/PaymentMessageBuilder.java",
            10,
        ),
        (
            "gitlab.example.com/orders/order-service",
            "src/main/java/example/PaymentMessageBuilder.java",
            50,
        ),
    ]:
        repository.save(
            make_item(
                "code:src/main/java/example/PaymentMessageBuilder.java:PaymentMessageBuilder.build",
                AssetType.CODE,
                "PaymentMessageBuilder.build",
                "build payment message from order data",
                SourceCitation(
                    source_type=SourceType.CODE,
                    repo=repo,
                    path=path,
                    start_line=line_start,
                    end_line=line_start + 10,
                    symbol="PaymentMessageBuilder.build",
                ),
                {"language": "java", "symbol_type": "method"},
            )
        )
    session.commit()

    service = HybridSearchService(repository)
    results = service.search(
        HybridSearchQuery(
            query="payment message",
            asset_type=AssetType.CODE,
            filters={"repo": "gitlab.example.com/orders/order-service"},
        )
    )

    assert [result.source.repo for result in results] == [
        "gitlab.example.com/orders/order-service"
    ]


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


def test_hybrid_search_merges_bounded_keyword_and_vector_candidates() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    repository = IndexedItemRepository(session)
    identity = EmbeddingIdentity(provider="fake", model="query-model", dimension=3)

    repository.save(
        make_item(
            "code:KeywordOnlyService.build",
            AssetType.CODE,
            "KeywordOnlyService.build",
            "rare payment keyword implementation",
            SourceCitation(
                source_type=SourceType.CODE,
                repo="gitlab.example.com/payments/payment-service",
                path="src/main/java/example/KeywordOnlyService.java",
                start_line=1,
                end_line=12,
                symbol="KeywordOnlyService.build",
            ),
            {"language": "java", "symbol_type": "method"},
        )
    )
    repository.save(
        make_item(
            "code:VectorOnlyService.print",
            AssetType.CODE,
            "VectorOnlyService.print",
            "invoice document",
            SourceCitation(
                source_type=SourceType.CODE,
                repo="gitlab.example.com/payments/payment-service",
                path="src/main/java/example/VectorOnlyService.java",
                start_line=1,
                end_line=12,
                symbol="VectorOnlyService.print",
            ),
            {"language": "java", "symbol_type": "method"},
        ),
        embedding=[0.0, 1.0, 0.0],
        embedding_identity=identity,
    )
    session.commit()

    service = HybridSearchService(repository, QueryEmbeddingProvider(identity))
    results = service.search(
        HybridSearchQuery(
            query="rare payment",
            asset_type=AssetType.CODE,
            query_embedding=[0.0, 1.0, 0.0],
            limit=10,
            filters={"language": "java"},
        )
    )

    result_ids = [result.item.id for result in results]
    assert result_ids == [
        "code:KeywordOnlyService.build",
        "code:VectorOnlyService.print",
    ]
    assert results[0].score_parts is not None
    assert results[0].score_parts["keyword"] == 1.0
    assert results[0].score_parts["vector"] == 0.0
    assert results[1].score_parts is not None
    assert results[1].score_parts["keyword"] == 0.0
    assert results[1].score_parts["vector"] == 1.0


def test_hybrid_search_generates_query_embedding_with_query_mode() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    repository = IndexedItemRepository(session)
    identity = EmbeddingIdentity(
        provider="jina:retrieval.passage>retrieval.query",
        model="jina-embeddings-v4",
        dimension=3,
    )
    provider = QueryModeEmbeddingProvider(identity)

    repository.save(
        make_item(
            "code:VectorOnlyService.print",
            AssetType.CODE,
            "VectorOnlyService.print",
            "invoice document",
            SourceCitation(
                source_type=SourceType.CODE,
                repo="gitlab.example.com/payments/payment-service",
                path="src/main/java/example/VectorOnlyService.java",
                start_line=1,
                end_line=12,
                symbol="VectorOnlyService.print",
            ),
            {"language": "java", "symbol_type": "method"},
        ),
        embedding=[0.0, 1.0, 0.0],
        embedding_identity=identity,
    )
    session.commit()

    service = HybridSearchService(repository, provider)
    results = service.search(
        HybridSearchQuery(
            query="semantic invoice",
            asset_type=AssetType.CODE,
            limit=10,
        )
    )

    assert [result.item.id for result in results] == ["code:VectorOnlyService.print"]
    assert provider.query_requests == ["semantic invoice"]
    assert provider.document_requests == []


def test_hybrid_search_expands_domain_aliases_for_lexical_recall() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    repository = IndexedItemRepository(session)

    repository.save(
        make_item(
            "code:PaymentApprovalService.approve",
            AssetType.CODE,
            "PaymentApprovalService.approve",
            "cashflow approval validation for pending payment requests",
            SourceCitation(
                source_type=SourceType.CODE,
                repo="gitlab.example.com/payments/payment-service",
                path="src/main/java/example/PaymentApprovalService.java",
                start_line=12,
                end_line=40,
                symbol="PaymentApprovalService.approve",
            ),
            {"language": "java", "symbol_type": "method"},
        )
    )
    session.commit()

    service = HybridSearchService(
        repository,
        domain_vocabulary=DomainVocabulary.from_mapping(
            {
                "aliases": [
                    {
                        "term": "现金流审批",
                        "expands_to": [
                            "cashflow approval",
                            "PaymentApprovalService",
                        ],
                    }
                ]
            }
        ),
    )
    results = service.search(
        HybridSearchQuery(
            query="现金流审批",
            asset_type=AssetType.CODE,
            filters={"repo": "gitlab.example.com/payments/payment-service"},
        )
    )

    assert [result.item.id for result in results] == [
        "code:PaymentApprovalService.approve"
    ]
    assert results[0].score_parts is not None
    assert results[0].score_parts["lexical"] > 0
    assert service.last_trace is not None
    assert service.last_trace.alias_expansions == (
        "现金流审批 -> cashflow approval, PaymentApprovalService",
    )


def test_hybrid_search_uses_symbol_catalog_when_text_does_not_match() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    repository = IndexedItemRepository(session)
    repo = "gitlab.example.com/payments/payment-service"
    item = repository.save(
        make_item(
            "code:DomainHandler.handle",
            AssetType.CODE,
            "DomainHandler.handle",
            "validate request state and record audit decision",
            SourceCitation(
                source_type=SourceType.CODE,
                repo=repo,
                path="src/main/java/example/DomainHandler.java",
                start_line=12,
                end_line=40,
                symbol="DomainHandler.handle",
            ),
            {"language": "java", "symbol_type": "method"},
        )
    )
    repository.save_symbols(
        [
            SymbolCatalogEntry(
                repo=repo,
                symbol_id="java:class:example.PaymentApprovalService",
                path="src/main/java/example/DomainHandler.java",
                language="java",
                kind="class",
                name="PaymentApprovalService",
                qualified_name="example.PaymentApprovalService",
                start_line=1,
                end_line=80,
                source_item_id=item.id,
            )
        ]
    )
    session.commit()

    service = HybridSearchService(repository)
    results = service.search(
        HybridSearchQuery(
            query="PaymentApprovalService",
            asset_type=AssetType.CODE,
            filters={"repo": repo, "language": "java"},
        )
    )

    assert [result.item.id for result in results] == ["code:DomainHandler.handle"]
    assert results[0].score_parts is not None
    assert results[0].score_parts["symbol"] == 1.0
    assert "symbol exact hit" in results[0].match_reason
    assert service.last_trace is not None
    assert [hit.channel for hit in service.last_trace.hits] == ["symbol"]
    assert service.last_trace.fused[0].channel_ranks == {"symbol": 1}


class QueryEmbeddingProvider:
    def __init__(self, identity: EmbeddingIdentity):
        self.identity = identity

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.0, 1.0, 0.0] for _text in texts]


class QueryModeEmbeddingProvider:
    batch_size = 2

    def __init__(self, identity: EmbeddingIdentity):
        self.identity = identity
        self.document_requests: list[list[str]] = []
        self.query_requests: list[str] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.document_requests.append(list(texts))
        return [[1.0, 0.0, 0.0] for _text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_requests.append(text)
        return [0.0, 1.0, 0.0]
