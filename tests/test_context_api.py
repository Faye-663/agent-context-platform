from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agent_context_platform.api import create_app
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
            source=SourceCitation(source_type=SourceType.DB_SCHEMA, table="payment_order"),
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


def test_search_interfaces_return_empty_results_and_invalid_request_error() -> None:
    client = make_client()

    empty_response = client.post("/search-code", json={"query": "not-found"})
    invalid_response = client.post("/search-code", json={"query": ""})

    assert empty_response.status_code == 200
    assert empty_response.json() == {"results": []}
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
    assert payload["similar_implementations"][0]["source"]["symbol"] == (
        "PaymentMessageBuilder.build"
    )
    assert payload["missing_context"] == []
    assert len(payload["citations"]) >= 3


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
