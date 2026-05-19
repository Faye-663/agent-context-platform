from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from agent_context_platform.models import AssetType, IndexedItem, SourceCitation, SourceType
from agent_context_platform.runtime import (
    RuntimeConfigError,
    RuntimeSettings,
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
    assert settings.embedding is not None
    assert settings.embedding.dimension == 1024
    assert settings.embedding.batch_size == 32


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
                "ACP_EMBEDDING_BASE_URL": "https://dashscope.aliyuncs.com/api/v1",
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
                "ACP_EMBEDDING_BASE_URL": "https://dashscope.aliyuncs.com/api/v1",
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


def test_asgi_module_exposes_importable_app(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ACP_DATABASE_URL", f"sqlite:///{tmp_path / 'asgi.db'}")

    module = importlib.import_module("agent_context_platform.asgi")
    module = importlib.reload(module)

    assert module.app.title == "agent-context-platform"

