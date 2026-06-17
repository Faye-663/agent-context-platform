from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from agent_context_platform.models import AssetType, IndexedItem, SourceCitation, SourceType
from agent_context_platform.runtime import (
    EmbeddingProviderSettings,
    RuntimeConfigError,
    RuntimeSettings,
    build_embedding_provider,
    create_runtime_app,
    load_runtime_settings,
)
from agent_context_platform.storage import Base, IndexedItemRepository


def test_load_runtime_settings_requires_database_url() -> None:
    with pytest.raises(RuntimeConfigError, match="ACP_DATABASE_URL"):
        load_runtime_settings({})


def test_load_runtime_settings_reads_runtime_and_embedding_values() -> None:
    settings = load_runtime_settings(
        {
            "ACP_DATABASE_URL": "sqlite:///runtime.db",
            "ACP_ENV": "test",
            "ACP_LOG_LEVEL": "DEBUG",
            "ACP_SQL_ECHO": "true",
            "ACP_DEFAULT_REPO": "gitlab.example.com/payments/payment-service",
            "ACP_REQUIRE_REPO_FILTER": "true",
            "ACP_ALIAS_FILE": "config/domain-aliases.json",
            "ACP_EMBEDDING_BASE_URL": "https://embedding.example.com/v1",
            "ACP_EMBEDDING_API_KEY": "test-key",
            "ACP_EMBEDDING_MODEL": "embedding-model",
            "ACP_EMBEDDING_DIMENSION": "1024",
            "ACP_EMBEDDING_BATCH_SIZE": "32",
        }
    )

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
    assert settings.sql_echo is True
    assert settings.default_repo == "gitlab.example.com/payments/payment-service"
    assert settings.require_repo_filter is True
    assert settings.alias_file == "config/domain-aliases.json"
    assert settings.embedding is not None
    assert settings.embedding.dimension == 1024
    assert settings.embedding.batch_size == 32


def test_load_runtime_settings_reads_openai_provider_values() -> None:
    settings = load_runtime_settings(
        {
            "ACP_DATABASE_URL": "sqlite:///runtime.db",
            "ACP_EMBEDDING_PROVIDER": "openai",
            "ACP_EMBEDDING_BASE_URL": "https://api.openai.example/v1",
            "ACP_EMBEDDING_API_KEY": "test-key",
            "ACP_EMBEDDING_MODEL": "embedding-model",
            "ACP_EMBEDDING_DIMENSION": "2048",
            "ACP_EMBEDDING_BATCH_SIZE": "16",
        }
    )

    assert settings.embedding is not None
    assert settings.embedding.provider == "openai"
    assert settings.embedding.model == "embedding-model"


def test_load_runtime_settings_defaults_embedding_provider_to_openai() -> None:
    settings = load_runtime_settings(
        {
            "ACP_DATABASE_URL": "sqlite:///runtime.db",
            "ACP_EMBEDDING_BASE_URL": "https://api.openai.example/v1",
            "ACP_EMBEDDING_API_KEY": "test-key",
            "ACP_EMBEDDING_MODEL": "embedding-model",
            "ACP_EMBEDDING_DIMENSION": "2048",
            "ACP_EMBEDDING_BATCH_SIZE": "16",
        }
    )

    assert settings.embedding is not None
    assert settings.embedding.provider == "openai"


def test_build_embedding_provider_creates_openai_compatible_provider() -> None:
    provider = build_embedding_provider(
        EmbeddingProviderSettings(
            provider="openai",
            base_url="https://api.openai.example/v1",
            api_key="test-key",
            model="embedding-model",
            dimension=2048,
            batch_size=16,
        )
    )

    assert provider.identity.provider == "openai"
    assert provider.identity.model == "embedding-model"


def test_build_embedding_provider_creates_infer_provider() -> None:
    provider = build_embedding_provider(
        EmbeddingProviderSettings(
            provider="infer",
            base_url="http://gateway.example.test/infer",
            api_key="test-key",
            model="bge-m3",
            dimension=1024,
            batch_size=1,
        )
    )

    assert provider.identity.provider == "infer"
    assert provider.identity.model == "bge-m3"


def test_build_embedding_provider_rejects_unsupported_provider() -> None:
    with pytest.raises(RuntimeConfigError, match="openai.*infer"):
        build_embedding_provider(
            EmbeddingProviderSettings(
                provider="legacy",
                base_url="https://embedding.example.com/v1",
                api_key="test-key",
                model="embedding-model",
                dimension=1024,
                batch_size=16,
            )
        )


def test_load_runtime_settings_rejects_partial_embedding_configuration() -> None:
    with pytest.raises(RuntimeConfigError, match="ACP_EMBEDDING_API_KEY"):
        load_runtime_settings(
            {
                "ACP_DATABASE_URL": "sqlite:///runtime.db",
                "ACP_EMBEDDING_BASE_URL": "https://embedding.example.com/v1",
            }
        )


def test_load_runtime_settings_rejects_empty_embedding_batch_size() -> None:
    with pytest.raises(RuntimeConfigError, match="ACP_EMBEDDING_BATCH_SIZE"):
        load_runtime_settings(
            {
                "ACP_DATABASE_URL": "sqlite:///runtime.db",
                "ACP_EMBEDDING_BASE_URL": "https://api.openai.example/v1",
                "ACP_EMBEDDING_API_KEY": "test-key",
                "ACP_EMBEDDING_MODEL": "embedding-model",
                "ACP_EMBEDDING_DIMENSION": "1024",
                "ACP_EMBEDDING_BATCH_SIZE": "",
            }
        )


def test_load_runtime_settings_rejects_zero_embedding_batch_size() -> None:
    with pytest.raises(RuntimeConfigError, match="ACP_EMBEDDING_BATCH_SIZE"):
        load_runtime_settings(
            {
                "ACP_DATABASE_URL": "sqlite:///runtime.db",
                "ACP_EMBEDDING_BASE_URL": "https://api.openai.example/v1",
                "ACP_EMBEDDING_API_KEY": "test-key",
                "ACP_EMBEDDING_MODEL": "embedding-model",
                "ACP_EMBEDDING_DIMENSION": "1024",
                "ACP_EMBEDDING_BATCH_SIZE": "0",
            }
        )


def test_load_runtime_settings_rejects_invalid_log_level() -> None:
    with pytest.raises(RuntimeConfigError, match="ACP_LOG_LEVEL"):
        load_runtime_settings(
            {
                "ACP_DATABASE_URL": "sqlite:///runtime.db",
                "ACP_LOG_LEVEL": "verbose",
            }
        )


def test_create_runtime_app_serves_context_api(tmp_path) -> None:
    settings = RuntimeSettings(
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        environment="test",
    )
    app = create_runtime_app(settings)
    Base.metadata.create_all(app.state.engine)

    with Session(app.state.engine) as session:
        repository = IndexedItemRepository(session)
        repository.save(
            IndexedItem(
                id="code:PaymentMessageBuilder.build",
                asset_type=AssetType.CODE,
                title="PaymentMessageBuilder.build",
                content="build payment message",
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
            )
        )
        session.commit()

    client = TestClient(app)
    response = client.post("/search-code", json={"query": "payment"})

    assert response.status_code == 200
    assert response.json()["results"][0]["source"]["symbol"] == (
        "PaymentMessageBuilder.build"
    )


def test_create_runtime_app_applies_default_repo_filter(tmp_path) -> None:
    settings = RuntimeSettings(
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        environment="test",
        default_repo="gitlab.example.com/payments/payment-service",
    )
    app = create_runtime_app(settings)
    Base.metadata.create_all(app.state.engine)

    with Session(app.state.engine) as session:
        repository = IndexedItemRepository(session)
        repository.save(
            IndexedItem(
                id="code:SharedService.build",
                asset_type=AssetType.CODE,
                title="SharedService.build",
                content="build shared payment",
                summary="支付服务实现。",
                metadata={"language": "java", "symbol_type": "method"},
                source=SourceCitation(
                    source_type=SourceType.CODE,
                    repo="gitlab.example.com/payments/payment-service",
                    path="src/main/java/example/SharedService.java",
                    start_line=10,
                    end_line=30,
                    symbol="SharedService.build",
                ),
            )
        )
        repository.save(
            IndexedItem(
                id="code:SharedService.build",
                asset_type=AssetType.CODE,
                title="SharedService.build",
                content="build shared payment",
                summary="订单服务实现。",
                metadata={"language": "java", "symbol_type": "method"},
                source=SourceCitation(
                    source_type=SourceType.CODE,
                    repo="gitlab.example.com/orders/order-service",
                    path="src/main/java/example/SharedService.java",
                    start_line=40,
                    end_line=60,
                    symbol="SharedService.build",
                ),
            )
        )
        session.commit()

    client = TestClient(app)
    response = client.post("/search-code", json={"query": "shared payment"})

    assert response.status_code == 200
    assert [result["source"]["repo"] for result in response.json()["results"]] == [
        "gitlab.example.com/payments/payment-service"
    ]


def test_create_runtime_app_loads_domain_alias_file(tmp_path) -> None:
    alias_file = tmp_path / "aliases.json"
    alias_file.write_text(
        """
        {
          "aliases": [
            {
              "term": "现金流审批",
              "expands_to": ["cashflow approval", "PaymentApprovalService"]
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    settings = RuntimeSettings(
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        environment="test",
        alias_file=str(alias_file),
    )
    app = create_runtime_app(settings)
    Base.metadata.create_all(app.state.engine)

    with Session(app.state.engine) as session:
        repository = IndexedItemRepository(session)
        repository.save(
            IndexedItem(
                id="code:PaymentApprovalService.approve",
                asset_type=AssetType.CODE,
                title="PaymentApprovalService.approve",
                content="cashflow approval validation",
                summary="支付审批实现。",
                metadata={"language": "java", "symbol_type": "method"},
                source=SourceCitation(
                    source_type=SourceType.CODE,
                    repo="gitlab.example.com/payments/payment-service",
                    path="src/main/java/example/PaymentApprovalService.java",
                    start_line=10,
                    end_line=30,
                    symbol="PaymentApprovalService.approve",
                ),
            )
        )
        session.commit()

    client = TestClient(app)
    response = client.post("/search-code", json={"query": "现金流审批"})

    assert response.status_code == 200
    assert response.json()["results"][0]["source"]["symbol"] == (
        "PaymentApprovalService.approve"
    )


def test_create_runtime_app_rejects_invalid_domain_alias_file(tmp_path) -> None:
    alias_file = tmp_path / "aliases.json"
    alias_file.write_text("[]", encoding="utf-8")
    settings = RuntimeSettings(
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        environment="test",
        alias_file=str(alias_file),
    )

    with pytest.raises(RuntimeConfigError, match="ACP_ALIAS_FILE"):
        create_runtime_app(settings)


def test_create_runtime_app_requires_repo_filter_when_configured(tmp_path) -> None:
    settings = RuntimeSettings(
        database_url=f"sqlite:///{tmp_path / 'runtime.db'}",
        environment="test",
        require_repo_filter=True,
    )
    app = create_runtime_app(settings)
    Base.metadata.create_all(app.state.engine)

    client = TestClient(app)
    response = client.post("/search-code", json={"query": "payment"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    assert "repo" in response.json()["error"]["message"]


def test_asgi_module_exposes_importable_app(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ACP_DATABASE_URL", f"sqlite:///{tmp_path / 'asgi.db'}")

    module = importlib.import_module("agent_context_platform.asgi")
    module = importlib.reload(module)

    assert module.app.title == "agent-context-platform"
