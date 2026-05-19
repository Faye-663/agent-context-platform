from __future__ import annotations

import json
from collections.abc import Sequence

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent_context_platform.embeddings import (
    DashScopeEmbeddingProvider,
    EmbeddingDimensionError,
    EmbeddingIdentity,
    EmbeddingProviderError,
    embed_and_save_items,
)
from agent_context_platform.indexers import (
    index_java_source,
    index_markdown_document,
    index_sql_ddl,
)
from agent_context_platform.models import AssetType
from agent_context_platform.storage import Base, IndexedItemRepository


def test_dashscope_provider_posts_native_multimodal_request_and_parses_vectors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == (
            "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
            "multimodal-embedding/multimodal-embedding"
        )
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload == {
            "model": "test-embedding-model",
            "input": {"contents": [{"text": "alpha"}, {"text": "beta"}]},
            "parameters": {"dimension": 3},
        }
        return httpx.Response(
            200,
            json={
                "output": {
                    "embeddings": [
                        {"type": "text", "embedding": [1.0, 0.0, 0.0]},
                        {"type": "text", "embedding": [0.0, 1.0, 0.0]},
                    ]
                },
                "usage": {"input_tokens": 2},
            },
        )

    provider = DashScopeEmbeddingProvider(
        base_url="https://dashscope.aliyuncs.com/api/v1",
        api_key="test-key",
        model="test-embedding-model",
        dimension=3,
        batch_size=10,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert provider.identity == EmbeddingIdentity(
        provider="dashscope", model="test-embedding-model", dimension=3
    )
    assert provider.embed_texts(["alpha", "beta"]) == [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ]


def test_dashscope_provider_reports_provider_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"code": "Throttled", "message": "rate limit exceeded"},
        )

    provider = DashScopeEmbeddingProvider(
        base_url="https://dashscope.aliyuncs.com/api/v1",
        api_key="test-key",
        model="test-embedding-model",
        dimension=3,
        batch_size=10,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(EmbeddingProviderError, match="429.*Throttled"):
        provider.embed_texts(["alpha"])


def test_dashscope_provider_rejects_wrong_dimension() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"output": {"embeddings": [{"type": "text", "embedding": [1.0, 0.0]}]}},
        )

    provider = DashScopeEmbeddingProvider(
        base_url="https://dashscope.aliyuncs.com/api/v1",
        api_key="test-key",
        model="test-embedding-model",
        dimension=3,
        batch_size=10,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(EmbeddingDimensionError, match="test-embedding-model"):
        provider.embed_texts(["alpha"])


class FakeEmbeddingProvider:
    identity = EmbeddingIdentity(provider="fake", model="fake-model", dimension=3)
    batch_size = 2

    def __init__(self) -> None:
        self.requests: list[list[str]] = []

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        self.requests.append(list(texts))
        return [[float(index + 1), 0.0, 0.0] for index, _text in enumerate(texts)]


def test_embed_and_save_items_writes_all_asset_embeddings_with_identity() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    provider = FakeEmbeddingProvider()

    java_items = index_java_source(
        "src/main/java/example/PaymentService.java",
        """
        class PaymentService {
            void buildMessage() {
            }
        }
        """,
    )
    sql_items = index_sql_ddl(
        "db/payment.sql",
        "CREATE TABLE payment_order (id bigint, status varchar(20));",
    )
    doc_items = index_markdown_document(
        "docs/payment.md",
        "# Payment Integration\n\nBuild payment messages.",
    )
    items = [java_items[0], sql_items[0], doc_items[0]]

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        saved_count = embed_and_save_items(repository, provider, items)
        session.commit()

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        code_embeddings = repository.list_with_embeddings(
            asset_type=AssetType.CODE,
            embedding_identity=provider.identity,
        )
        schema_embeddings = repository.list_with_embeddings(
            asset_type=AssetType.DB_SCHEMA,
            embedding_identity=provider.identity,
        )
        doc_embeddings = repository.list_with_embeddings(
            asset_type=AssetType.DOC,
            embedding_identity=provider.identity,
        )

    assert saved_count == 3
    assert len(provider.requests) == 2
    assert code_embeddings[0][1] == [1.0, 0.0, 0.0]
    assert schema_embeddings[0][1] == [2.0, 0.0, 0.0]
    assert doc_embeddings[0][1] == [1.0, 0.0, 0.0]
