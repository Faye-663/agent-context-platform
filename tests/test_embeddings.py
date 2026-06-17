from __future__ import annotations

import json
from collections.abc import Sequence

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent_context_platform.embeddings import (
    EmbeddingDimensionError,
    EmbeddingIdentity,
    EmbeddingProviderError,
    InferEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    embed_and_save_items,
)
from agent_context_platform.indexers import (
    index_java_source,
    index_markdown_document,
    index_sql_ddl,
)
from agent_context_platform.models import AssetType
from agent_context_platform.storage import Base, IndexedItemRepository


def test_openai_compatible_provider_posts_embeddings_request_and_parses_vectors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.openai.example/v1/embeddings"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload == {
            "model": "embedding-model",
            "input": ["alpha", "beta"],
            "encoding_format": "float",
            "dimensions": 3,
        }
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"object": "embedding", "index": 0, "embedding": [1.0, 0.0, 0.0]},
                    {"object": "embedding", "index": 1, "embedding": [0.0, 1.0, 0.0]},
                ],
                "model": "embedding-model",
            },
        )

    provider = OpenAICompatibleEmbeddingProvider(
        provider="openai",
        base_url="https://api.openai.example/v1",
        api_key="test-key",
        model="embedding-model",
        dimension=3,
        batch_size=10,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert provider.identity == EmbeddingIdentity(
        provider="openai", model="embedding-model", dimension=3
    )
    assert provider.embed_texts(["alpha", "beta"]) == [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ]


def test_openai_compatible_provider_reports_provider_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"code": "invalid_request", "message": "bad input"}},
        )

    provider = OpenAICompatibleEmbeddingProvider(
        provider="openai",
        base_url="https://api.openai.example/v1",
        api_key="test-key",
        model="embedding-model",
        dimension=3,
        batch_size=10,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(EmbeddingProviderError, match="400.*invalid_request"):
        provider.embed_texts(["alpha"])


def test_openai_compatible_provider_reports_detail_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "detail": {
                    "code": "INPUT_TOKEN_LIMIT_EXCEEDED",
                    "message": "Input text exceeds the model limit.",
                }
            },
        )

    provider = OpenAICompatibleEmbeddingProvider(
        provider="openai",
        base_url="https://api.openai.example/v1",
        api_key="test-key",
        model="embedding-model",
        dimension=3,
        batch_size=10,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(
        EmbeddingProviderError,
        match="INPUT_TOKEN_LIMIT_EXCEEDED.*Input text exceeds",
    ):
        provider.embed_texts(["alpha"])


def test_infer_provider_posts_messages_to_exact_endpoint_and_parses_vectors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://gateway.example.test/infer"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload == {
            "model": "bge-m3",
            "messages": [{"role": "user", "content": "Hello!"}],
        }
        return httpx.Response(
            200,
            json={"data": {"embedding": [1.0, 0.0, 0.0]}},
        )

    provider = InferEmbeddingProvider(
        base_url="http://gateway.example.test/infer",
        api_key="test-key",
        model="bge-m3",
        dimension=3,
        batch_size=10,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert provider.identity == EmbeddingIdentity(
        provider="infer", model="bge-m3", dimension=3
    )
    assert provider.embed_texts(["Hello!"]) == [[1.0, 0.0, 0.0]]


def test_infer_provider_parses_embedding_from_message_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer explicit-key"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "{\"embedding\": [0.0, 1.0, 0.0]}"
                        }
                    }
                ]
            },
        )

    provider = InferEmbeddingProvider(
        base_url="http://gateway.example.test/infer",
        api_key="Bearer explicit-key",
        model="bge-m3",
        dimension=3,
        batch_size=10,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert provider.embed_query("Hello!") == [0.0, 1.0, 0.0]


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
        repo="gitlab.example.com/payments/payment-service",
    )
    sql_items = index_sql_ddl(
        "db/payment.sql",
        "CREATE TABLE payment_order (id bigint, status varchar(20));",
        repo="gitlab.example.com/payments/payment-service",
    )
    doc_items = index_markdown_document(
        "docs/payment.md",
        "# Payment Integration\n\nBuild payment messages.",
        repo="gitlab.example.com/payments/payment-service",
    )
    items = [java_items[0], sql_items[0], doc_items[0]]

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        saved_count = embed_and_save_items(repository, provider, items)
        session.commit()

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        code_embeddings = repository.list_with_embeddings(
            repo="gitlab.example.com/payments/payment-service",
            asset_type=AssetType.CODE,
            embedding_identity=provider.identity,
        )
        schema_embeddings = repository.list_with_embeddings(
            repo="gitlab.example.com/payments/payment-service",
            asset_type=AssetType.DB_SCHEMA,
            embedding_identity=provider.identity,
        )
        doc_embeddings = repository.list_with_embeddings(
            repo="gitlab.example.com/payments/payment-service",
            asset_type=AssetType.DOC,
            embedding_identity=provider.identity,
        )

    assert saved_count == 3
    assert len(provider.requests) == 2
    assert code_embeddings[0][1] == [1.0, 0.0, 0.0]
    assert schema_embeddings[0][1] == [2.0, 0.0, 0.0]
    assert doc_embeddings[0][1] == [1.0, 0.0, 0.0]
