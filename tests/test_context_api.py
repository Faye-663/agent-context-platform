from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agent_context_platform.api import create_app
from agent_context_platform.embeddings import (
    EmbeddingIdentity,
    EmbeddingProviderError,
)
from agent_context_platform.models import AssetType, IndexedItem, SourceCitation, SourceType
from agent_context_platform.retrieval import HybridSearchService
from agent_context_platform.storage import Base, IndexedItemRepository


def make_client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    repository = IndexedItemRepository(session)
    repository.save(
        IndexedItem(
            id="code:PaymentMessageBuilder.build",
            asset_type=AssetType.CODE,
            title="PaymentMessageBuilder.build",
            content="build payment message from order data",
            summary="构造支付报文。",
            metadata={"language": "java", "symbol_type": "method"},
            source=SourceCitation(
                source_type=SourceType.CODE,
                repo="gitlab.example.com/payments/payment-service",
                path="src/main/java/example/PaymentMessageBuilder.java",
                start_line=10,
                end_line=30,
                symbol="PaymentMessageBuilder.build",
            ),
        ),
        embedding=[1.0, 0.0, 0.0],
    )
    repository.save(
        IndexedItem(
            id="db_schema:payment_order",
            asset_type=AssetType.DB_SCHEMA,
            title="payment_order",
            content="payment order status amount",
            summary="支付订单表。",
            metadata={"symbol_type": "table", "table": "payment_order"},
            source=SourceCitation(
                source_type=SourceType.DB_SCHEMA,
                repo="gitlab.example.com/payments/payment-service",
                table="payment_order",
            ),
        ),
        embedding=[1.0, 0.0, 0.0],
    )
    repository.save(
        IndexedItem(
            id="doc:payment-integration",
            asset_type=AssetType.DOC,
            title="Payment Integration",
            content="payment integration message generation",
            summary="支付集成文档。",
            metadata={"heading_path": "Payment Integration"},
            source=SourceCitation(
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

    app = create_app(HybridSearchService(repository))
    return TestClient(app)


def test_search_interfaces_return_contract_results_with_source_citations() -> None:
    client = make_client()

    code_response = client.post(
        "/search-code",
        json={"query": "payment message", "filters": {"language": "java"}},
    )
    schema_response = client.post(
        "/search-db-schema",
        json={"query": "payment status", "filters": {"table": "payment_order"}},
    )
    doc_response = client.post(
        "/search-doc",
        json={"query": "payment integration", "filters": {"path_prefix": "docs"}},
    )

    assert code_response.status_code == 200
    assert code_response.json()["results"][0]["source"]["symbol"] == (
        "PaymentMessageBuilder.build"
    )
    assert schema_response.status_code == 200
    assert schema_response.json()["results"][0]["source"]["table"] == "payment_order"
    assert doc_response.status_code == 200
    assert doc_response.json()["results"][0]["source"]["heading_path"] == (
        "Payment Integration"
    )


def test_search_debug_trace_serializes_internal_retrieval_details() -> None:
    client = make_client()

    response = client.post(
        "/search-code",
        json={
            "query": "payment message",
            "debug_options": {"include_trace": True},
        },
    )

    assert response.status_code == 200
    trace = response.json()["_trace"]
    assert trace["query"] == "payment message"
    assert trace["query_tokens"] == ["message", "payment"]
    assert trace["alias_expansions"] == []
    assert trace["channels"]["lexical"]["hits"][0]["rank"] == 1
    assert "keyword/lexical hit" in trace["channels"]["lexical"]["hits"][0]["reason"]
    assert trace["fused"][0]["channel_ranks"] == {"lexical": 1}
    assert trace["fused"][0]["rrf_score"] > 0


def test_build_task_context_debug_trace_keeps_each_retrieval_group() -> None:
    client = make_client()

    response = client.post(
        "/build-task-context",
        json={
            "task": "payment message",
            "debug_options": {"include_trace": True},
        },
    )

    assert response.status_code == 200
    traces = response.json()["_trace"]["queries"]
    assert set(traces) == {
        "related_code",
        "related_db_schema",
        "related_docs",
        "similar_implementations",
    }
    assert traces["related_code"]["query_tokens"] == ["message", "payment"]
    assert traces["related_code"]["fused"][0]["channel_ranks"] == {"lexical": 1}


def test_search_interface_filters_results_by_repo() -> None:
    client = make_client()

    matching_response = client.post(
        "/search-code",
        json={
            "query": "payment message",
            "filters": {"repo": "gitlab.example.com/payments/payment-service"},
        },
    )
    missing_response = client.post(
        "/search-code",
        json={
            "query": "payment message",
            "filters": {"repo": "gitlab.example.com/orders/order-service"},
        },
    )

    assert matching_response.status_code == 200
    assert matching_response.json()["results"][0]["source"]["repo"] == (
        "gitlab.example.com/payments/payment-service"
    )
    assert missing_response.status_code == 200
    assert missing_response.json() == {
        "result_status": "empty",
        "results": [],
        "risks": [],
    }


def test_search_strictly_filters_results_by_expected_commit() -> None:
    client = make_client()

    response = client.post(
        "/search-code",
        json={
            "query": "payment message",
            "filters": {"expected_commit_sha": "missing-commit"},
        },
    )

    assert response.status_code == 200
    assert response.json()["result_status"] == "empty"
    assert response.json()["results"] == []
    assert response.json()["risks"][0]["code"] == "STALE_INDEX"


def test_search_interfaces_return_empty_results_and_invalid_request_error() -> None:
    client = make_client()

    empty_response = client.post("/search-code", json={"query": "not-found"})
    invalid_response = client.post("/search-code", json={"query": ""})

    assert empty_response.status_code == 200
    assert empty_response.json() == {
        "result_status": "empty",
        "results": [],
        "risks": [],
    }
    assert invalid_response.status_code == 400
    assert invalid_response.json()["error"]["code"] == "invalid_request"


def test_search_logging_includes_request_id_api_name_count_and_elapsed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = make_client()

    with caplog.at_level(logging.INFO, logger="agent_context_platform.api"):
        response = client.post(
            "/search-code",
            json={"query": "payment", "request_id": "req-123"},
        )

    assert response.status_code == 200
    assert "request_id=req-123" in caplog.text
    assert "api=search-code" in caplog.text
    assert "result_count=1" in caplog.text
    assert "elapsed_ms=" in caplog.text


def test_build_task_context_groups_results_and_reports_missing_context() -> None:
    client = make_client()

    response = client.post(
        "/build-task-context",
        json={
            "task": "新增支付接口，复用支付报文生成能力",
            "limits": {
                "code": 5,
                "db_schema": 5,
                "docs": 5,
                "similar_implementations": 5,
            },
            "constraints": {"language": "java"},
        },
    )

    payload = response.json()

    assert response.status_code == 200
    assert payload["related_code"][0]["source"]["symbol"] == (
        "PaymentMessageBuilder.build"
    )
    assert payload["related_db_schema"][0]["source"]["table"] == "payment_order"
    assert payload["related_docs"][0]["source"]["heading_path"] == "Payment Integration"
    assert payload["related_code"][0]["evidence_role"] == "primary"
    assert payload["related_docs"][0]["evidence_role"] == "background"
    assert payload["similar_implementations"] == []
    assert payload["missing_context"] == []
    assert len(payload["citations"]) >= 3


def test_build_task_context_applies_repo_constraint_to_all_searches() -> None:
    client = make_client()

    response = client.post(
        "/build-task-context",
        json={
            "task": "新增支付接口，复用支付报文生成能力",
            "constraints": {
                "repo": "gitlab.example.com/orders/order-service",
                "language": "java",
            },
        },
    )

    payload = response.json()

    assert response.status_code == 200
    assert payload["related_code"] == []
    assert payload["related_db_schema"] == []
    assert payload["related_docs"] == []
    assert payload["missing_context"] == ["code", "db_schema", "doc"]


def test_build_task_context_reports_empty_assets_as_missing_context() -> None:
    client = make_client()

    response = client.post(
        "/build-task-context",
        json={"task": "完全无关任务", "limits": {"code": 3, "db_schema": 3, "docs": 3}},
    )

    payload = response.json()

    assert response.status_code == 200
    assert payload["related_code"] == []
    assert "code" in payload["missing_context"]
    assert "db_schema" in payload["missing_context"]
    assert "doc" in payload["missing_context"]
    assert payload["risks"]


def test_build_task_context_reports_partially_missing_context() -> None:
    client = make_client()

    response = client.post(
        "/build-task-context",
        json={
            "task": "payment integration",
            "limits": {"code": 3, "db_schema": 3, "docs": 3},
            "constraints": {"language": "kotlin"},
        },
    )

    payload = response.json()

    assert response.status_code == 200
    assert payload["related_code"] == []
    assert payload["related_db_schema"]
    assert payload["related_docs"]
    assert payload["missing_context"] == ["code"]


def test_build_task_context_applies_token_budget_constraint() -> None:
    client = make_client()

    response = client.post(
        "/build-task-context",
        json={
            "task": "新增支付接口，复用支付报文生成能力",
            "constraints": {"language": "java", "token_budget": 1},
        },
    )

    payload = response.json()

    assert response.status_code == 200
    assert [result["source"]["symbol"] for result in payload["related_code"]] == [
        "PaymentMessageBuilder.build"
    ]
    assert payload["related_db_schema"] == []
    assert payload["related_docs"] == []
    assert payload["missing_context"] == ["db_schema", "doc"]
    assert len(payload["citations"]) == 1


def test_build_task_context_rejects_invalid_token_budget_constraint() -> None:
    client = make_client()

    response = client.post(
        "/build-task-context",
        json={
            "task": "新增支付接口，复用支付报文生成能力",
            "constraints": {"token_budget": "small"},
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert "token_budget" in response.json()["error"]["message"]


class QueryEmbeddingProvider:
    identity = EmbeddingIdentity(provider="fake", model="query-model", dimension=3)
    batch_size = 10

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise EmbeddingProviderError("provider unavailable")
        self.calls.append(list(texts))
        return [[0.0, 1.0, 0.0] for _text in texts]


def test_search_generates_query_embedding_when_provider_is_configured() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    repository = IndexedItemRepository(session)
    provider = QueryEmbeddingProvider()
    repository.save(
        IndexedItem(
            id="code:InvoicePrinter.print",
            asset_type=AssetType.CODE,
            title="InvoicePrinter.print",
            content="print invoice document",
            summary="打印发票。",
            metadata={"language": "java", "symbol_type": "method"},
            source=SourceCitation(
                source_type=SourceType.CODE,
                repo="gitlab.example.com/payments/payment-service",
                path="src/main/java/example/InvoicePrinter.java",
                start_line=5,
                end_line=18,
                symbol="InvoicePrinter.print",
            ),
        ),
        embedding=[0.0, 1.0, 0.0],
        embedding_identity=provider.identity,
    )
    session.commit()

    client = TestClient(create_app(HybridSearchService(repository, provider)))
    response = client.post("/search-code", json={"query": "unmatched text"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"][0]["source"]["symbol"] == "InvoicePrinter.print"
    assert payload["results"][0]["score_parts"]["vector"] == 1.0
    assert provider.calls == [["unmatched text"]]


def test_explicit_query_embedding_skips_provider_call() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    repository = IndexedItemRepository(session)
    provider = QueryEmbeddingProvider()
    repository.save(
        IndexedItem(
            id="code:InvoicePrinter.print",
            asset_type=AssetType.CODE,
            title="InvoicePrinter.print",
            content="print invoice document",
            summary="打印发票。",
            metadata={"language": "java", "symbol_type": "method"},
            source=SourceCitation(
                source_type=SourceType.CODE,
                repo="gitlab.example.com/payments/payment-service",
                path="src/main/java/example/InvoicePrinter.java",
                start_line=5,
                end_line=18,
                symbol="InvoicePrinter.print",
            ),
        ),
        embedding=[0.0, 1.0, 0.0],
        embedding_identity=provider.identity,
    )
    session.commit()

    client = TestClient(create_app(HybridSearchService(repository, provider)))

    response = client.post(
        "/search-code",
        json={
            "query": "unmatched text",
            "debug_options": {"query_embedding": [0.0, 1.0, 0.0]},
        },
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["score_parts"]["vector"] == 1.0
    assert provider.calls == []


def test_search_returns_embedding_unavailable_when_provider_fails() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    repository = IndexedItemRepository(session)
    provider = QueryEmbeddingProvider(fail=True)

    client = TestClient(create_app(HybridSearchService(repository, provider)))
    response = client.post("/search-code", json={"query": "payment"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "embedding_unavailable"
