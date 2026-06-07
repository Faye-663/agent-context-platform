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
    # MVP Context API 验证覆盖 FastAPI 运行路径；默认 SQLite，设置 ACP_DATABASE_URL 后可连真实数据库。
    database_url = os.environ.get("ACP_DATABASE_URL", "sqlite:///:memory:")
    engine = _make_verification_engine(database_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        _seed_mvp_runtime_samples(repository)
        session.commit()

        client = TestClient(create_app(HybridSearchService(repository)))
        code = _post(client, "/search-code", {"query": "mvp payment message"})
        schema = _post(client, "/search-db-schema", {"query": "mvp payment status"})
        doc = _post(client, "/search-doc", {"query": "mvp payment integration"})
        context = _post(
            client,
            "/build-task-context",
            {
                "task": "mvp payment integration message",
                "limits": {
                    "code": 5,
                    "db_schema": 5,
                    "docs": 5,
                    "similar_implementations": 5,
                },
                "constraints": {"language": "java"},
            },
        )

    assert code["results"][0]["source"]["symbol"] == "MvpPaymentMessageBuilder.build"
    assert schema["results"][0]["source"]["table"] == "mvp_payment_order"
    assert doc["results"][0]["source"]["heading_path"] == "MVP Payment Integration"
    assert context["related_code"]
    assert context["related_db_schema"]
    assert context["related_docs"]
    assert context["similar_implementations"]
    assert context["missing_context"] == []

    print("MVP Context API runtime verification passed")
    print(f"database_url={database_url}")
    print(
        "result_counts="
        f"code:{len(code['results'])},"
        f"db_schema:{len(schema['results'])},"
        f"doc:{len(doc['results'])},"
        f"citations:{len(context['citations'])}"
    )


def _seed_mvp_runtime_samples(repository: IndexedItemRepository) -> None:
    repository.save(
        IndexedItem(
            id="code:mvp:MvpPaymentMessageBuilder.build",
            asset_type=AssetType.CODE,
            title="MvpPaymentMessageBuilder.build",
            content="mvp payment message build implementation",
            summary="MVP 支付报文构造示例。",
            metadata={"language": "java", "symbol_type": "method"},
            source=SourceCitation(
                source_type=SourceType.CODE,
                path="src/main/java/example/MvpPaymentMessageBuilder.java",
                start_line=10,
                end_line=30,
                symbol="MvpPaymentMessageBuilder.build",
            ),
        ),
        embedding=[1.0, 0.0, 0.0],
    )
    repository.save(
        IndexedItem(
            id="db_schema:mvp:mvp_payment_order",
            asset_type=AssetType.DB_SCHEMA,
            title="mvp_payment_order",
            content="mvp payment order status amount",
            summary="MVP 支付订单表。",
            metadata={"symbol_type": "table", "table": "mvp_payment_order"},
            source=SourceCitation(
                source_type=SourceType.DB_SCHEMA,
                table="mvp_payment_order",
            ),
        ),
        embedding=[1.0, 0.0, 0.0],
    )
    repository.save(
        IndexedItem(
            id="doc:mvp:payment-integration",
            asset_type=AssetType.DOC,
            title="MVP Payment Integration",
            content="mvp payment integration message generation",
            summary="MVP 支付集成文档。",
            metadata={"heading_path": "MVP Payment Integration"},
            source=SourceCitation(
                source_type=SourceType.DOC,
                path="docs/mvp-payment.md",
                start_line=1,
                end_line=8,
                heading_path="MVP Payment Integration",
            ),
        ),
        embedding=[1.0, 0.0, 0.0],
    )


def _make_verification_engine(database_url: str):
    # TestClient 需要跨线程访问同一个 SQLite 内存库，因此这里使用 StaticPool。
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
