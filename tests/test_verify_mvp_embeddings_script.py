from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from agent_context_platform.embeddings import EmbeddingIdentity
from agent_context_platform.runtime import EmbeddingProviderSettings, RuntimeSettings


def _load_script_module():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "verify_mvp_embeddings.py"
    )
    spec = importlib.util.spec_from_file_location("verify_mvp_embeddings", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mvp_embedding_script_uses_runtime_provider_factory(
    monkeypatch,
    capsys,
) -> None:
    module = _load_script_module()
    embedding_settings = EmbeddingProviderSettings(
        provider="jina",
        base_url="https://api.jina.ai/v1",
        api_key="test-key",
        model="jina-embeddings-v4",
        dimension=3,
        batch_size=10,
        document_task="retrieval.passage",
        query_task="retrieval.query",
    )
    settings = RuntimeSettings(
        database_url="sqlite:///:memory:",
        embedding=embedding_settings,
    )
    provider = SimpleNamespace(
        identity=EmbeddingIdentity(
            provider="jina:retrieval.passage>retrieval.query",
            model="jina-embeddings-v4",
            dimension=3,
        ),
        batch_size=10,
    )
    seen_settings = []

    class FakeSession:
        def __init__(self, _engine):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc_info):
            return False

        def commit(self) -> None:
            pass

    class FakeRepository:
        def __init__(self, _session):
            pass

        def list_with_embeddings(self, **_kwargs):
            return [
                (SimpleNamespace(id="code:mvp-embedding"), [1.0, 0.0, 0.0]),
                (SimpleNamespace(id="code:existing-without-jina"), None),
            ]

    class FakeSearchService:
        def __init__(self, _repository, _provider):
            pass

        def search(self, _query):
            return [
                SimpleNamespace(
                    item=SimpleNamespace(id="code:mvp-embedding"),
                    score_parts={"vector": 0.75},
                )
            ]

    def fake_build_embedding_provider(provider_settings):
        seen_settings.append(provider_settings)
        return provider

    monkeypatch.setattr(module, "load_runtime_settings", lambda: settings)
    monkeypatch.setattr(module, "build_embedding_provider", fake_build_embedding_provider)
    monkeypatch.setattr(module, "make_engine", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(module, "Session", FakeSession)
    monkeypatch.setattr(module, "IndexedItemRepository", FakeRepository)
    monkeypatch.setattr(module, "HybridSearchService", FakeSearchService)
    monkeypatch.setattr(module, "embed_and_save_items", lambda *_args: 3)
    monkeypatch.setattr(module, "_sample_items", lambda: [SimpleNamespace(id="code:mvp-embedding")])
    monkeypatch.setattr(module, "_assert_embeddings", lambda *_args: None)
    monkeypatch.setattr(sys, "argv", ["verify_mvp_embeddings.py"])

    module.main()

    assert seen_settings == [embedding_settings]
    output = capsys.readouterr().out
    assert "provider=jina:retrieval.passage>retrieval.query" in output


def test_filter_rows_by_ids_ignores_existing_items_without_current_embedding() -> None:
    module = _load_script_module()

    rows = [
        (SimpleNamespace(id="code:mvp-embedding"), [1.0, 0.0, 0.0]),
        (SimpleNamespace(id="code:existing-without-jina"), None),
    ]

    assert module._filter_rows_by_ids(rows, {"code:mvp-embedding"}) == [rows[0]]
