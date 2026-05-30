from __future__ import annotations

import argparse
import fnmatch
import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import sys
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from agent_context_platform.embeddings import (
    DashScopeEmbeddingProvider,
    EmbeddingProvider,
    embed_and_save_items,
)
from agent_context_platform.indexers import (
    index_java_source,
    index_markdown_document,
    index_sql_ddl,
)
from agent_context_platform.models import IndexedItem
from agent_context_platform.runtime import (
    RuntimeConfigError,
    RuntimeSettings,
    load_runtime_settings,
)
from agent_context_platform.storage import Base, IndexedItemRepository, make_engine


DEFAULT_INCLUDE_PATTERNS = ("**/*.java", "**/*.sql", "**/*.md")
DEFAULT_EXCLUDE_PATTERNS = (
    ".git",
    "target",
    "build",
    "dist",
    "node_modules",
    ".venv",
    "__pycache__",
)
_EMBEDDING_ENV_PREFIX = "ACP_EMBEDDING_"


EmbeddingProviderFactory = Callable[[RuntimeSettings], EmbeddingProvider]


@dataclass(frozen=True)
class Failure:
    path: str | None
    stage: str
    error: str

    def as_dict(self) -> dict[str, str | None]:
        return {"path": self.path, "stage": self.stage, "error": self.error}


@dataclass(frozen=True)
class IndexedFile:
    path: str
    items: list[IndexedItem]


def main() -> None:
    raise SystemExit(run())


def run(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    embedding_provider_factory: EmbeddingProviderFactory | None = None,
) -> int:
    started = time.perf_counter()
    args = _parse_args(argv)
    output = stdout or sys.stdout
    values = dict(os.environ if environ is None else environ)
    failures: list[Failure] = []

    root = args.root.resolve()
    repo = args.repo or root.name
    database = _redact_database_url(values.get("ACP_DATABASE_URL"))

    if not root.is_dir():
        failures.append(
            Failure(path=str(args.root), stage="config", error="--root must be a directory")
        )
        _write_summary(
            output,
            _summary(
                repo=repo,
                database=database,
                files_scanned=0,
                indexed_files=[],
                items_written=0,
                embedding_written=0,
                failures=failures,
                started=started,
            ),
        )
        return 1

    scanned_files = _scan_files(
        root=root,
        exclude_patterns=DEFAULT_EXCLUDE_PATTERNS + tuple(args.exclude or ()),
    )
    include_patterns = tuple(args.include) if args.include else DEFAULT_INCLUDE_PATTERNS
    indexable_files = [
        path
        for path in scanned_files
        if _is_included(_relative_posix(path, root), include_patterns)
    ]
    indexed_files = _index_files(root=root, repo=repo, files=indexable_files, failures=failures)
    items = [item for indexed_file in indexed_files for item in indexed_file.items]

    if args.dry_run:
        _write_summary(
            output,
            _summary(
                repo=repo,
                database=database,
                files_scanned=len(scanned_files),
                indexed_files=indexed_files,
                items_written=0,
                embedding_written=0,
                failures=failures,
                started=started,
            ),
        )
        return 1 if failures else 0

    try:
        settings = _load_cli_settings(values, with_embedding=args.with_embedding)
        database = _redact_database_url(settings.database_url)
        embedding_provider = _build_embedding_provider(
            settings,
            with_embedding=args.with_embedding,
            provider_factory=embedding_provider_factory,
        )
        items_written, embedding_written = _write_items(
            settings=settings,
            items=items,
            embedding_provider=embedding_provider,
        )
    except (RuntimeConfigError, ValueError) as exc:
        failures.append(Failure(path=None, stage="config", error=str(exc)))
        items_written = 0
        embedding_written = 0
    except SQLAlchemyError as exc:
        failures.append(Failure(path=None, stage="database", error=str(exc)))
        items_written = 0
        embedding_written = 0

    _write_summary(
        output,
        _summary(
            repo=repo,
            database=database,
            files_scanned=len(scanned_files),
            indexed_files=indexed_files,
            items_written=items_written,
            embedding_written=embedding_written,
            failures=failures,
            started=started,
        ),
    )
    return 1 if failures else 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize an Agent Context Platform index from a project directory."
    )
    parser.add_argument("--root", required=True, type=Path, help="Project root to scan.")
    parser.add_argument(
        "--repo",
        default=None,
        help="Repository identifier to store in source citations. Defaults to root name.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and parse files without writing indexed items or embeddings.",
    )
    parser.add_argument(
        "--with-embedding",
        action="store_true",
        help="Generate and write item embeddings using ACP_EMBEDDING_* settings.",
    )
    parser.add_argument(
        "--include",
        action="append",
        help="Glob pattern to include. Defaults to Java, SQL and Markdown files.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        help="Glob pattern to exclude. Excludes take precedence over includes.",
    )
    return parser.parse_args(argv)


def _scan_files(
    *,
    root: Path,
    exclude_patterns: Sequence[str],
) -> list[Path]:
    files: list[Path] = []
    for current_root, dirnames, filenames in os.walk(root):
        current_path = Path(current_root)
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not _is_excluded(_relative_posix(current_path / dirname, root), exclude_patterns)
        ]
        for filename in filenames:
            path = current_path / filename
            relative_path = _relative_posix(path, root)
            if _is_excluded(relative_path, exclude_patterns):
                continue
            files.append(path)
    return sorted(files, key=lambda candidate: _relative_posix(candidate, root))


def _index_files(
    *,
    root: Path,
    repo: str,
    files: Sequence[Path],
    failures: list[Failure],
) -> list[IndexedFile]:
    indexed_files: list[IndexedFile] = []
    for path in files:
        relative_path = _relative_posix(path, root)
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            failures.append(Failure(path=relative_path, stage="read", error=str(exc)))
            continue

        try:
            items = _index_content(relative_path, content, repo)
        except Exception as exc:  # noqa: BLE001 - CLI must keep indexing other files.
            failures.append(Failure(path=relative_path, stage="index", error=str(exc)))
            continue

        if items:
            indexed_files.append(IndexedFile(path=relative_path, items=items))
    return indexed_files


def _index_content(path: str, content: str, repo: str) -> list[IndexedItem]:
    suffix = Path(path).suffix.lower()
    if suffix == ".java":
        return index_java_source(path, content, repo=repo)
    if suffix == ".sql":
        return index_sql_ddl(path, content, repo=repo)
    if suffix == ".md":
        return index_markdown_document(path, content, repo=repo)
    return []


def _load_cli_settings(values: Mapping[str, str], *, with_embedding: bool) -> RuntimeSettings:
    if with_embedding:
        settings = load_runtime_settings(values)
        if settings.embedding is None:
            raise RuntimeConfigError(
                "--with-embedding requires complete ACP_EMBEDDING_* configuration"
            )
        return settings

    # 普通索引不应被未使用的 embedding 环境变量阻塞；只有显式开启时才解析该组配置。
    database_only_values = {
        key: value for key, value in values.items() if not key.startswith(_EMBEDDING_ENV_PREFIX)
    }
    return load_runtime_settings(database_only_values)


def _build_embedding_provider(
    settings: RuntimeSettings,
    *,
    with_embedding: bool,
    provider_factory: EmbeddingProviderFactory | None,
) -> EmbeddingProvider | None:
    if not with_embedding:
        return None
    if provider_factory is not None:
        return provider_factory(settings)
    if settings.embedding is None:
        raise RuntimeConfigError(
            "--with-embedding requires complete ACP_EMBEDDING_* configuration"
        )
    return DashScopeEmbeddingProvider(
        base_url=settings.embedding.base_url,
        api_key=settings.embedding.api_key,
        model=settings.embedding.model,
        dimension=settings.embedding.dimension,
        batch_size=settings.embedding.batch_size,
    )


def _write_items(
    *,
    settings: RuntimeSettings,
    items: Sequence[IndexedItem],
    embedding_provider: EmbeddingProvider | None,
) -> tuple[int, int]:
    engine = make_engine(settings.database_url, echo=settings.sql_echo)
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        try:
            if embedding_provider is None:
                for item in items:
                    repository.save(item)
                embedding_written = 0
            else:
                embedding_written = embed_and_save_items(repository, embedding_provider, items)
            session.commit()
        except Exception:
            session.rollback()
            raise
    return len(items), embedding_written


def _summary(
    *,
    repo: str,
    database: str | None,
    files_scanned: int,
    indexed_files: Sequence[IndexedFile],
    items_written: int,
    embedding_written: int,
    failures: Sequence[Failure],
    started: float,
) -> dict[str, Any]:
    items_estimated = sum(len(indexed_file.items) for indexed_file in indexed_files)
    return {
        "repo": repo,
        "database": database,
        "files_scanned": files_scanned,
        "files_indexed": len(indexed_files),
        "items_estimated": items_estimated,
        "items_written": items_written,
        "items_failed": len(failures),
        "embedding_written": embedding_written,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "failures": [failure.as_dict() for failure in failures],
    }


def _write_summary(output: TextIO, summary: Mapping[str, Any]) -> None:
    output.write(json.dumps(summary, ensure_ascii=False, indent=2))
    output.write("\n")


def _relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_included(path: str, include_patterns: Sequence[str]) -> bool:
    for pattern in include_patterns:
        if fnmatch.fnmatchcase(path, pattern):
            return True
        if pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:]):
            return True
    return False


def _is_excluded(path: str, exclude_patterns: Sequence[str]) -> bool:
    path_parts = tuple(Path(path).parts)
    for pattern in exclude_patterns:
        if pattern in path_parts:
            return True
        if fnmatch.fnmatchcase(path, pattern):
            return True
    return False


def _redact_database_url(database_url: str | None) -> str | None:
    if not database_url:
        return None
    try:
        return make_url(database_url).render_as_string(hide_password=True)
    except Exception:  # noqa: BLE001 - summary should not fail while reporting config.
        return database_url


if __name__ == "__main__":
    main()
