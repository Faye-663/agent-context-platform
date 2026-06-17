from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from io import StringIO
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from agent_context_platform.embeddings import EmbeddingIdentity, EmbeddingProviderError
from agent_context_platform.index_cli import run
from agent_context_platform.models import AssetType
from agent_context_platform.storage import Base, IndexedItemRepository


class FakeEmbeddingProvider:
    identity = EmbeddingIdentity(provider="fake", model="mvp-index-cli", dimension=3)
    batch_size = 2

    def __init__(self) -> None:
        self.requests: list[list[str]] = []

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        self.requests.append(list(texts))
        return [[1.0, 0.0, 0.0] for _text in texts]


class FailingEmbeddingProvider:
    identity = EmbeddingIdentity(provider="fake", model="mvp-index-cli", dimension=3)
    batch_size = 2

    def embed_texts(self, _texts: Sequence[str]) -> list[list[float]]:
        raise EmbeddingProviderError("simulated provider failure")


def test_dry_run_scans_indexable_files_without_database_write(tmp_path: Path) -> None:
    sample_root = _sample_project(tmp_path)
    sqlite_db = sample_root / "index.sqlite"
    output = StringIO()

    exit_code = run(
        ["--root", str(sample_root), "--dry-run"],
        environ={"ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}"},
        stdout=output,
    )

    summary = _summary(output)
    assert exit_code == 0
    assert summary["repo"] == sample_root.name
    assert summary["files_scanned"] == 3
    assert summary["files_indexed"] == 3
    assert summary["items_estimated"] == 7
    assert summary["symbols_estimated"] == 5
    assert summary["items_written"] == 0
    assert summary["symbols_written"] == 0
    assert summary["items_failed"] == 0
    assert summary["embedding_written"] == 0
    assert summary["index_batch_id"]
    assert summary["indexed_at"]
    assert summary["branch"] is None
    assert summary["commit_sha"] is None
    assert summary["provenance_warnings"]
    assert summary["failures"] == []
    assert not sqlite_db.exists()


def test_index_cli_writes_scanned_items_to_configured_database(tmp_path: Path) -> None:
    sample_root = _sample_project(tmp_path)
    sqlite_db = sample_root / "index.sqlite"
    output = StringIO()

    exit_code = run(
        ["--root", str(sample_root), "--repo", "payment-app"],
        environ={"ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}"},
        stdout=output,
    )

    summary = _summary(output)
    assert exit_code == 0
    assert summary["repo"] == "payment-app"
    assert summary["files_scanned"] == 3
    assert summary["files_indexed"] == 3
    assert summary["items_written"] == 7
    assert summary["symbols_written"] == 5
    assert summary["embedding_written"] == 0

    engine = create_engine(f"sqlite:///{sqlite_db.as_posix()}")
    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        code_items = repository.list(asset_type=AssetType.CODE)
        schema_items = repository.list(asset_type=AssetType.DB_SCHEMA)
        doc_items = repository.list(asset_type=AssetType.DOC)
        method_symbols = repository.find_symbols_exact(
            repo="payment-app",
            query="example.PaymentService.build(PaymentRequest)",
        )
        table_symbols = repository.find_symbols_exact(
            repo="payment-app",
            query="payment_order",
            kinds=["table"],
        )

    assert len(code_items) == 2
    assert len(schema_items) == 3
    assert len(doc_items) == 2
    assert {item.source.repo for item in code_items + schema_items + doc_items} == {
        "payment-app"
    }
    assert {
        item.source.index_batch_id for item in code_items + schema_items + doc_items
    } == {summary["index_batch_id"]}
    assert all(item.source.indexed_at is not None for item in code_items + schema_items + doc_items)
    assert all(item.source.file_hash for item in code_items + schema_items + doc_items)
    assert {item.source.branch for item in code_items + schema_items + doc_items} == {
        summary["branch"]
    }
    assert {item.source.commit_sha for item in code_items + schema_items + doc_items} == {
        summary["commit_sha"]
    }
    assert code_items[0].source.file_hash == _sha256(
        sample_root / "src/main/java/example/PaymentService.java"
    )
    assert code_items[0].source.path == "src/main/java/example/PaymentService.java"
    assert len(method_symbols) == 1
    assert method_symbols[0].kind == "method"
    assert len(table_symbols) == 1
    assert table_symbols[0].kind == "table"


def test_include_and_exclude_rules_filter_files(tmp_path: Path) -> None:
    sample_root = _sample_project(tmp_path)
    (sample_root / "target/generated").mkdir(parents=True)
    (sample_root / "target/generated/Generated.java").write_text(
        "class Generated { void skip() {} }",
        encoding="utf-8",
    )
    output = StringIO()

    exit_code = run(
        [
            "--root",
            str(sample_root),
            "--dry-run",
            "--include",
            "**/*.java",
            "--exclude",
            "src/main/java/example/PaymentService.java",
        ],
        environ={},
        stdout=output,
    )

    summary = _summary(output)
    assert exit_code == 0
    assert summary["files_scanned"] == 2
    assert summary["files_indexed"] == 0
    assert summary["items_estimated"] == 0


def test_path_scope_reindexes_changed_file_without_touching_other_paths(
    tmp_path: Path,
) -> None:
    sample_root = _sample_project(tmp_path)
    sqlite_db = sample_root / "index.sqlite"
    initial_output = StringIO()
    run(
        ["--root", str(sample_root), "--repo", "payment-app"],
        environ={"ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}"},
        stdout=initial_output,
    )
    initial_summary = _summary(initial_output)
    java_path = sample_root / "src/main/java/example/PaymentService.java"
    java_path.write_text(
        """package example;

public class PaymentService {
    public String build(PaymentRequest request) {
        return "changed";
    }
}
""",
        encoding="utf-8",
    )
    output = StringIO()

    exit_code = run(
        [
            "--root",
            str(sample_root),
            "--repo",
            "payment-app",
            "--path",
            "src/main/java/example/PaymentService.java",
        ],
        environ={"ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}"},
        stdout=output,
    )

    summary = _summary(output)
    assert exit_code == 0
    assert summary["scope_paths"] == ["src/main/java/example/PaymentService.java"]
    assert summary["files_scanned"] == 1
    assert summary["files_changed"] == 1
    assert summary["files_unchanged"] == 0
    assert summary["files_deleted"] == 0
    assert summary["items_written"] == 2
    assert summary["symbols_written"] == 2
    assert summary["items_deleted"] == 0

    engine = create_engine(f"sqlite:///{sqlite_db.as_posix()}")
    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        code_items = repository.list(
            asset_type=AssetType.CODE,
            repo="payment-app",
            path="src/main/java/example/PaymentService.java",
        )
        doc_items = repository.list(asset_type=AssetType.DOC, repo="payment-app")
        code_symbols = repository.find_symbols_prefix(
            repo="payment-app",
            query="example.PaymentService",
            language="java",
        )

    assert {item.source.index_batch_id for item in code_items} == {
        summary["index_batch_id"]
    }
    assert {item.source.index_batch_id for item in doc_items} == {
        initial_summary["index_batch_id"]
    }
    assert {symbol.index_batch_id for symbol in code_symbols} == {
        summary["index_batch_id"]
    }


def test_path_scope_deletes_missing_items_without_cross_repo_deletion(
    tmp_path: Path,
) -> None:
    sample_root = _sample_project(tmp_path)
    sqlite_db = sample_root / "index.sqlite"
    for repo in ("payment-app", "order-app"):
        output = StringIO()
        run(
            ["--root", str(sample_root), "--repo", repo],
            environ={"ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}"},
            stdout=output,
        )
    java_path = sample_root / "src/main/java/example/PaymentService.java"
    java_path.unlink()
    output = StringIO()

    exit_code = run(
        [
            "--root",
            str(sample_root),
            "--repo",
            "payment-app",
            "--path",
            "src/main/java/example",
        ],
        environ={"ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}"},
        stdout=output,
    )

    summary = _summary(output)
    assert exit_code == 0
    assert summary["files_deleted"] == 1
    assert summary["items_deleted"] == 2
    assert summary["symbols_deleted"] == 2
    assert summary["items_written"] == 0

    engine = create_engine(f"sqlite:///{sqlite_db.as_posix()}")
    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        assert repository.list(asset_type=AssetType.CODE, repo="payment-app") == []
        assert repository.find_symbols_prefix(
            repo="payment-app",
            query="example.PaymentService",
        ) == []
        assert len(repository.list(asset_type=AssetType.CODE, repo="order-app")) == 2
        assert len(
            repository.find_symbols_prefix(
                repo="order-app",
                query="example.PaymentService",
            )
        ) == 2


def test_unchanged_path_scope_skips_item_and_embedding_writes(tmp_path: Path) -> None:
    sample_root = _sample_project(tmp_path)
    sqlite_db = sample_root / "index.sqlite"
    initial_provider = FakeEmbeddingProvider()
    initial_output = StringIO()
    run(
        ["--root", str(sample_root), "--repo", "payment-app", "--with-embedding"],
        environ={
            "ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}",
            "ACP_EMBEDDING_BASE_URL": "https://embedding.example.test",
            "ACP_EMBEDDING_API_KEY": "secret",
            "ACP_EMBEDDING_MODEL": "mvp-index-cli",
            "ACP_EMBEDDING_DIMENSION": "3",
            "ACP_EMBEDDING_BATCH_SIZE": "2",
        },
        stdout=initial_output,
        embedding_provider_factory=lambda _settings: initial_provider,
    )
    provider = FakeEmbeddingProvider()
    output = StringIO()

    exit_code = run(
        [
            "--root",
            str(sample_root),
            "--repo",
            "payment-app",
            "--path",
            "src/main/java/example/PaymentService.java",
            "--with-embedding",
        ],
        environ={
            "ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}",
            "ACP_EMBEDDING_BASE_URL": "https://embedding.example.test",
            "ACP_EMBEDDING_API_KEY": "secret",
            "ACP_EMBEDDING_MODEL": "mvp-index-cli",
            "ACP_EMBEDDING_DIMENSION": "3",
            "ACP_EMBEDDING_BATCH_SIZE": "2",
        },
        stdout=output,
        embedding_provider_factory=lambda _settings: provider,
    )

    summary = _summary(output)
    assert exit_code == 0
    assert summary["files_changed"] == 0
    assert summary["files_unchanged"] == 1
    assert summary["items_written"] == 0
    assert summary["symbols_written"] == 0
    assert summary["embedding_written"] == 0
    assert provider.requests == []


def test_parse_failure_keeps_existing_items_for_failed_path(tmp_path: Path) -> None:
    sample_root = _sample_project(tmp_path)
    sqlite_db = sample_root / "index.sqlite"
    initial_output = StringIO()
    run(
        ["--root", str(sample_root), "--repo", "payment-app"],
        environ={"ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}"},
        stdout=initial_output,
    )
    initial_summary = _summary(initial_output)
    (sample_root / "schema/payment.sql").write_text(
        "CREATE TABLE broken (",
        encoding="utf-8",
    )
    output = StringIO()

    exit_code = run(
        [
            "--root",
            str(sample_root),
            "--repo",
            "payment-app",
            "--path",
            "schema/payment.sql",
        ],
        environ={"ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}"},
        stdout=output,
    )

    summary = _summary(output)
    assert exit_code == 1
    assert summary["files_changed"] == 0
    assert summary["files_unchanged"] == 0
    assert summary["files_deleted"] == 0
    assert summary["items_deleted"] == 0
    assert summary["failures"][0]["path"] == "schema/payment.sql"

    engine = create_engine(f"sqlite:///{sqlite_db.as_posix()}")
    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        schema_items = repository.list(asset_type=AssetType.DB_SCHEMA, repo="payment-app")

    assert len(schema_items) == 3
    assert {item.source.index_batch_id for item in schema_items} == {
        initial_summary["index_batch_id"]
    }


def test_dry_run_reports_incremental_changes_without_database_mutation(
    tmp_path: Path,
) -> None:
    sample_root = _sample_project(tmp_path)
    sqlite_db = sample_root / "index.sqlite"
    initial_output = StringIO()
    run(
        ["--root", str(sample_root), "--repo", "payment-app"],
        environ={"ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}"},
        stdout=initial_output,
    )
    initial_summary = _summary(initial_output)
    java_path = sample_root / "src/main/java/example/PaymentService.java"
    java_path.write_text(
        """package example;

public class PaymentService {
    public String build(PaymentRequest request) {
        return "dry-run";
    }
}
""",
        encoding="utf-8",
    )
    (sample_root / "docs/payment.md").unlink()
    output = StringIO()

    exit_code = run(
        [
            "--root",
            str(sample_root),
            "--repo",
            "payment-app",
            "--path",
            "src/main/java/example/PaymentService.java",
            "--path",
            "docs",
            "--dry-run",
        ],
        environ={"ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}"},
        stdout=output,
    )

    summary = _summary(output)
    assert exit_code == 0
    assert summary["files_changed"] == 1
    assert summary["files_deleted"] == 1
    assert summary["items_deleted"] == 2
    assert summary["items_written"] == 0

    engine = create_engine(f"sqlite:///{sqlite_db.as_posix()}")
    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        code_items = repository.list(asset_type=AssetType.CODE, repo="payment-app")
        doc_items = repository.list(asset_type=AssetType.DOC, repo="payment-app")

    assert {item.source.index_batch_id for item in code_items + doc_items} == {
        initial_summary["index_batch_id"]
    }
    assert len(doc_items) == 2


def test_include_scope_does_not_delete_existing_items_outside_include_patterns(
    tmp_path: Path,
) -> None:
    sample_root = _sample_project(tmp_path)
    sqlite_db = sample_root / "index.sqlite"
    initial_output = StringIO()
    run(
        ["--root", str(sample_root), "--repo", "payment-app"],
        environ={"ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}"},
        stdout=initial_output,
    )
    (sample_root / "src/main/java/example/PaymentService.java").unlink()
    output = StringIO()

    exit_code = run(
        [
            "--root",
            str(sample_root),
            "--repo",
            "payment-app",
            "--include",
            "**/*.java",
        ],
        environ={"ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}"},
        stdout=output,
    )

    summary = _summary(output)
    assert exit_code == 0
    assert summary["files_deleted"] == 1
    assert summary["items_deleted"] == 2

    engine = create_engine(f"sqlite:///{sqlite_db.as_posix()}")
    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        assert repository.list(asset_type=AssetType.CODE, repo="payment-app") == []
        assert len(repository.list(asset_type=AssetType.DB_SCHEMA, repo="payment-app")) == 3
        assert len(repository.list(asset_type=AssetType.DOC, repo="payment-app")) == 2


def test_with_embedding_explicitly_writes_embeddings(tmp_path: Path) -> None:
    sample_root = _sample_project(tmp_path)
    sqlite_db = sample_root / "index.sqlite"
    provider = FakeEmbeddingProvider()
    output = StringIO()

    exit_code = run(
        ["--root", str(sample_root), "--with-embedding"],
        environ={
            "ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}",
            "ACP_EMBEDDING_BASE_URL": "https://embedding.example.test",
            "ACP_EMBEDDING_API_KEY": "secret",
            "ACP_EMBEDDING_MODEL": "mvp-index-cli",
            "ACP_EMBEDDING_DIMENSION": "3",
            "ACP_EMBEDDING_BATCH_SIZE": "2",
        },
        stdout=output,
        embedding_provider_factory=lambda _settings: provider,
    )

    summary = _summary(output)
    assert exit_code == 0
    assert summary["items_written"] == 7
    assert summary["embedding_written"] == 7
    assert len(provider.requests) == 4

    engine = create_engine(f"sqlite:///{sqlite_db.as_posix()}")
    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        code_embeddings = repository.list_with_embeddings(
            asset_type=AssetType.CODE,
            embedding_identity=provider.identity,
        )
    assert all(embedding == [1.0, 0.0, 0.0] for _item, embedding in code_embeddings)


def test_with_embedding_accepts_cli_configuration(tmp_path: Path) -> None:
    sample_root = _sample_project(tmp_path)
    sqlite_db = sample_root / "index.sqlite"
    provider = FakeEmbeddingProvider()
    output = StringIO()
    seen_database_urls: list[str] = []

    def provider_factory(settings):
        seen_database_urls.append(settings.database_url)
        assert settings.embedding is not None
        assert settings.embedding.provider == "openai"
        assert settings.embedding.base_url == "https://embedding.example.test/v1"
        assert settings.embedding.api_key == "secret"
        assert settings.embedding.model == "mvp-index-cli"
        assert settings.embedding.dimension == 3
        assert settings.embedding.batch_size == 2
        return provider

    exit_code = run(
        [
            "--root",
            str(sample_root),
            "--repo",
            "payment-app",
            "--database-url",
            f"sqlite:///{sqlite_db.as_posix()}",
            "--with-embedding",
            "--embedding-base-url",
            "https://embedding.example.test/v1",
            "--embedding-api-key",
            "secret",
            "--embedding-model",
            "mvp-index-cli",
            "--embedding-dimension",
            "3",
            "--embedding-batch-size",
            "2",
        ],
        environ={},
        stdout=output,
        embedding_provider_factory=provider_factory,
    )

    summary = _summary(output)
    assert exit_code == 0
    assert summary["repo"] == "payment-app"
    assert summary["database"].startswith("sqlite:///")
    assert summary["embedding_written"] == 7
    assert seen_database_urls == [f"sqlite:///{sqlite_db.as_posix()}"]


def test_embedding_configuration_is_ignored_without_explicit_flag(tmp_path: Path) -> None:
    sample_root = _sample_project(tmp_path)
    sqlite_db = sample_root / "index.sqlite"
    provider = FakeEmbeddingProvider()
    output = StringIO()

    exit_code = run(
        ["--root", str(sample_root)],
        environ={
            "ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}",
            "ACP_EMBEDDING_BASE_URL": "https://embedding.example.test",
            "ACP_EMBEDDING_API_KEY": "secret",
            "ACP_EMBEDDING_MODEL": "mvp-index-cli",
            "ACP_EMBEDDING_DIMENSION": "3",
            "ACP_EMBEDDING_BATCH_SIZE": "2",
        },
        stdout=output,
        embedding_provider_factory=lambda _settings: provider,
    )

    summary = _summary(output)
    assert exit_code == 0
    assert summary["embedding_written"] == 0
    assert provider.requests == []


def test_parse_failure_is_reported_and_other_files_continue(tmp_path: Path) -> None:
    sample_root = _sample_project(tmp_path)
    (sample_root / "schema/payment.sql").write_text(
        "CREATE TABLE broken (",
        encoding="utf-8",
    )
    sqlite_db = sample_root / "index.sqlite"
    output = StringIO()

    exit_code = run(
        ["--root", str(sample_root)],
        environ={"ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}"},
        stdout=output,
    )

    summary = _summary(output)
    assert exit_code == 1
    assert summary["files_scanned"] == 3
    assert summary["files_indexed"] == 2
    assert summary["items_written"] == 4
    assert summary["items_failed"] == 1
    assert summary["failures"][0]["path"] == "schema/payment.sql"
    assert summary["failures"][0]["stage"] == "index"


def test_with_embedding_requires_complete_embedding_configuration(tmp_path: Path) -> None:
    sample_root = _sample_project(tmp_path)
    output = StringIO()

    exit_code = run(
        ["--root", str(sample_root), "--with-embedding"],
        environ={
            "ACP_DATABASE_URL": "sqlite:///index.sqlite",
            "ACP_EMBEDDING_BASE_URL": "https://embedding.example.test",
        },
        stdout=output,
    )

    summary = _summary(output)
    assert exit_code == 1
    assert summary["failures"][0]["stage"] == "config"
    assert "ACP_EMBEDDING_API_KEY" in summary["failures"][0]["error"]


def test_with_embedding_reports_provider_failure_without_traceback(tmp_path: Path) -> None:
    sample_root = _sample_project(tmp_path)
    sqlite_db = sample_root / "index.sqlite"
    output = StringIO()

    exit_code = run(
        ["--root", str(sample_root), "--with-embedding"],
        environ={
            "ACP_DATABASE_URL": f"sqlite:///{sqlite_db.as_posix()}",
            "ACP_EMBEDDING_BASE_URL": "https://embedding.example.test",
            "ACP_EMBEDDING_API_KEY": "secret",
            "ACP_EMBEDDING_MODEL": "mvp-index-cli",
            "ACP_EMBEDDING_DIMENSION": "3",
            "ACP_EMBEDDING_BATCH_SIZE": "2",
        },
        stdout=output,
        embedding_provider_factory=lambda _settings: FailingEmbeddingProvider(),
    )

    summary = _summary(output)
    assert exit_code == 1
    assert summary["items_written"] == 0
    assert summary["embedding_written"] == 0
    assert summary["failures"][0]["stage"] == "embedding"
    assert "simulated provider failure" in summary["failures"][0]["error"]


def _sample_project(tmp_path: Path) -> Path:
    sample_root = tmp_path / "payment-service"
    (sample_root / "src/main/java/example").mkdir(parents=True)
    (sample_root / "schema").mkdir()
    (sample_root / "docs").mkdir()
    (sample_root / "src/main/java/example/PaymentService.java").write_text(
        """package example;

public class PaymentService {
    public String build(PaymentRequest request) {
        return "ok";
    }
}
""",
        encoding="utf-8",
    )
    (sample_root / "schema/payment.sql").write_text(
        """CREATE TABLE payment_order (
    id BIGINT PRIMARY KEY,
    status VARCHAR(32) NOT NULL
);
""",
        encoding="utf-8",
    )
    (sample_root / "docs/payment.md").write_text(
        """# Payment Integration

Build payment messages.

## Error Handling

Map provider errors.
""",
        encoding="utf-8",
    )
    return sample_root


def _summary(output: StringIO) -> dict[str, object]:
    return json.loads(output.getvalue())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
