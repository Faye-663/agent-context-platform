from __future__ import annotations

import os

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from agent_context_platform.api import create_app
from agent_context_platform.models import AssetType, IndexedItem, SourceCitation, SourceType
from agent_context_platform.retrieval import HybridSearchService
from agent_context_platform.storage import Base, IndexedItemRepository, make_engine


def main() -> None:
    database_url = os.environ.get("ACP_DATABASE_URL", "sqlite:///:memory:")
    engine = _make_verification_engine(database_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        _seed_phase3_samples(repository)
        session.commit()

        client = TestClient(create_app(HybridSearchService(repository)))
        code = _post(client, "/search-code", {"query": "phase3 payment message"})
        schema = _post(client, "/search-db-schema", {"query": "phase3 payment status"})
        doc = _post(client, "/search-doc", {"query": "phase3 payment integration"})
        context = _post(
            client,
            "/build-task-context",
            {
                "task": "phase3 payment integration message",
                "limits": {
                    "code": 5,
                    "db_schema": 5,
                    "docs": 5,
                    "similar_implementations": 5,
                },
                "constraints": {"language": "java"},
            },
        )

    assert code["results"][0]["source"]["symbol"] == "Phase3PaymentMessageBuilder.build"
    assert schema["results"][0]["source"]["table"] == "phase3_payment_order"
    assert doc["results"][0]["source"]["heading_path"] == "Phase3 Payment Integration"
    assert context["related_code"]
    assert context["related_db_schema"]
    assert context["related_docs"]
    assert context["similar_implementations"]
    assert context["missing_context"] == []

    print("phase3 runtime verification passed")
    print(f"database_url={database_url}")
    print(
        "result_counts="
        f"code:{len(code['results'])},"
        f"db_schema:{len(schema['results'])},"
        f"doc:{len(doc['results'])},"
        f"citations:{len(context['citations'])}"
    )


def _seed_phase3_samples(repository: IndexedItemRepository) -> None:
    repository.save(
        IndexedItem(
            id="code:phase3:Phase3PaymentMessageBuilder.build",
            asset_type=AssetType.CODE,
            title="Phase3PaymentMessageBuilder.build",
            content="phase3 payment message build implementation",
            summary="阶段三支付报文构造示例。",
            metadata={"language": "java", "symbol_type": "method"},
            source=SourceCitation(
                source_type=SourceType.CODE,
                path="src/main/java/example/Phase3PaymentMessageBuilder.java",
                start_line=10,
                end_line=30,
                symbol="Phase3PaymentMessageBuilder.build",
            ),
        ),
        embedding=[1.0, 0.0, 0.0],
    )
    repository.save(
        IndexedItem(
            id="db_schema:phase3:phase3_payment_order",
            asset_type=AssetType.DB_SCHEMA,
            title="phase3_payment_order",
            content="phase3 payment order status amount",
            summary="阶段三支付订单表。",
            metadata={"symbol_type": "table", "table": "phase3_payment_order"},
            source=SourceCitation(
                source_type=SourceType.DB_SCHEMA,
                table="phase3_payment_order",
            ),
        ),
        embedding=[1.0, 0.0, 0.0],
    )
    repository.save(
        IndexedItem(
            id="doc:phase3:payment-integration",
            asset_type=AssetType.DOC,
            title="Phase3 Payment Integration",
            content="phase3 payment integration message generation",
            summary="阶段三支付集成文档。",
            metadata={"heading_path": "Phase3 Payment Integration"},
            source=SourceCitation(
                source_type=SourceType.DOC,
                path="docs/phase3-payment.md",
                start_line=1,
                end_line=8,
                heading_path="Phase3 Payment Integration",
            ),
        ),
        embedding=[1.0, 0.0, 0.0],
    )


def _make_verification_engine(database_url: str):
    if database_url == "sqlite:///:memory:":
        return create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return make_engine(database_url)


def _post(client: TestClient, path: str, payload: dict[str, object]) -> dict[str, object]:
    response = client.post(path, json=payload)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    main()
