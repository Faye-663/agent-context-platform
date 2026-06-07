from __future__ import annotations

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
    assert summary["items_written"] == 0
    assert summary["items_failed"] == 0
    assert summary["embedding_written"] == 0
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
    assert summary["embedding_written"] == 0

    engine = create_engine(f"sqlite:///{sqlite_db.as_posix()}")
    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        code_items = repository.list(asset_type=AssetType.CODE)
        schema_items = repository.list(asset_type=AssetType.DB_SCHEMA)
        doc_items = repository.list(asset_type=AssetType.DOC)

    assert len(code_items) == 2
    assert len(schema_items) == 3
    assert len(doc_items) == 2
    assert {item.source.repo for item in code_items + schema_items + doc_items} == {
        "payment-app"
    }
    assert code_items[0].source.path == "src/main/java/example/PaymentService.java"


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
