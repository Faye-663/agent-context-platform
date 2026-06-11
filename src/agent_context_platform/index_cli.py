from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

import sys
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from agent_context_platform.embeddings import (
    EmbeddingDimensionError,
    EmbeddingProvider,
    EmbeddingProviderError,
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
    build_embedding_provider,
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
    file_hash: str
    items: list[IndexedItem]


@dataclass(frozen=True)
class IndexRunProvenance:
    branch: str | None
    commit_sha: str | None
    indexed_at: datetime
    index_batch_id: str
    warnings: list[str]


@dataclass(frozen=True)
class IndexScope:
    summary_paths: list[str]
    full_root: bool
    exact_paths: frozenset[str]
    path_prefixes: frozenset[str]


@dataclass(frozen=True)
class IncrementalPlan:
    changed_files: list[IndexedFile]
    unchanged_paths: list[str]
    deleted_paths: list[str]
    items_deleted: int


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
    provenance = _build_index_run_provenance(root)
    include_patterns = tuple(args.include) if args.include else DEFAULT_INCLUDE_PATTERNS
    exclude_patterns = DEFAULT_EXCLUDE_PATTERNS + tuple(args.exclude or ())

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
                incremental_plan=IncrementalPlan([], [], [], 0),
                scope_paths=[],
                items_written=0,
                embedding_written=0,
                failures=failures,
                provenance=provenance,
                started=started,
            ),
        )
        return 1

    scope = _build_index_scope(root=root, raw_paths=args.path, failures=failures)
    scanned_files = _scan_scope_files(
        root=root,
        scope=scope,
        exclude_patterns=exclude_patterns,
    )
    indexable_files = [
        path
        for path in scanned_files
        if _is_included(_relative_posix(path, root), include_patterns)
    ]
    indexed_files = _index_files(
        root=root,
        repo=repo,
        files=indexable_files,
        failures=failures,
        provenance=provenance,
    )

    if args.dry_run:
        incremental_plan = _preview_incremental_plan(
            values=values,
            repo=repo,
            scope=scope,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            indexed_files=indexed_files,
            failures=failures,
        )
        _write_summary(
            output,
            _summary(
                repo=repo,
                database=database,
                files_scanned=len(scanned_files),
                indexed_files=indexed_files,
                incremental_plan=incremental_plan,
                scope_paths=scope.summary_paths,
                items_written=0,
                embedding_written=0,
                failures=failures,
                provenance=provenance,
                started=started,
            ),
        )
        return 1 if failures else 0

    incremental_plan = IncrementalPlan([], [], [], 0)
    try:
        settings = _load_cli_settings(values, with_embedding=args.with_embedding)
        database = _redact_database_url(settings.database_url)
        embedding_provider = _build_embedding_provider(
            settings,
            with_embedding=args.with_embedding,
            provider_factory=embedding_provider_factory,
        )
        incremental_plan, items_written, embedding_written = _write_items(
            settings=settings,
            repo=repo,
            scope=scope,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            indexed_files=indexed_files,
            failures=failures,
            embedding_provider=embedding_provider,
        )
    except (EmbeddingProviderError, EmbeddingDimensionError) as exc:
        failures.append(Failure(path=None, stage="embedding", error=str(exc)))
        items_written = 0
        embedding_written = 0
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
            incremental_plan=incremental_plan,
            scope_paths=scope.summary_paths,
            items_written=items_written,
            embedding_written=embedding_written,
            failures=failures,
            provenance=provenance,
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
    parser.add_argument(
        "--path",
        action="append",
        type=Path,
        help="Relative file or directory path to reindex. Can be passed multiple times.",
    )
    return parser.parse_args(argv)


def _build_index_scope(
    *,
    root: Path,
    raw_paths: Sequence[Path] | None,
    failures: list[Failure],
) -> IndexScope:
    if not raw_paths:
        return IndexScope(
            summary_paths=["."],
            full_root=True,
            exact_paths=frozenset(),
            path_prefixes=frozenset(),
        )

    summary_paths: set[str] = set()
    exact_paths: set[str] = set()
    path_prefixes: set[str] = set()
    root_resolved = root.resolve()
    full_root = False

    for raw_path in raw_paths:
        candidate = raw_path if raw_path.is_absolute() else root / raw_path
        resolved = candidate.resolve(strict=False)
        try:
            relative_path = resolved.relative_to(root_resolved).as_posix()
        except ValueError:
            failures.append(
                Failure(
                    path=str(raw_path),
                    stage="config",
                    error="--path must stay within --root",
                )
            )
            continue

        if relative_path == ".":
            full_root = True
            summary_paths.add(".")
            continue

        normalized_path = relative_path.rstrip("/")
        summary_paths.add(normalized_path)
        if resolved.is_dir():
            path_prefixes.add(f"{normalized_path}/")
        else:
            exact_paths.add(normalized_path)

    return IndexScope(
        summary_paths=sorted(summary_paths),
        full_root=full_root,
        exact_paths=frozenset(exact_paths),
        path_prefixes=frozenset(path_prefixes),
    )


def _scan_scope_files(
    *,
    root: Path,
    scope: IndexScope,
    exclude_patterns: Sequence[str],
) -> list[Path]:
    if scope.full_root:
        return _scan_files(root=root, exclude_patterns=exclude_patterns)

    files: set[Path] = set()
    for path_prefix in scope.path_prefixes:
        files.update(
            _scan_files(root=root / path_prefix, exclude_patterns=exclude_patterns, base_root=root)
        )
    for relative_path in scope.exact_paths:
        path = root / relative_path
        if path.is_file() and not _is_excluded(relative_path, exclude_patterns):
            files.add(path)
    return sorted(files, key=lambda candidate: _relative_posix(candidate, root))


def _scan_files(
    *,
    root: Path,
    exclude_patterns: Sequence[str],
    base_root: Path | None = None,
) -> list[Path]:
    files: list[Path] = []
    relative_root = base_root or root
    for current_root, dirnames, filenames in os.walk(root):
        current_path = Path(current_root)
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not _is_excluded(
                _relative_posix(current_path / dirname, relative_root),
                exclude_patterns,
            )
        ]
        for filename in filenames:
            path = current_path / filename
            relative_path = _relative_posix(path, relative_root)
            if _is_excluded(relative_path, exclude_patterns):
                continue
            files.append(path)
    return sorted(files, key=lambda candidate: _relative_posix(candidate, relative_root))


def _index_files(
    *,
    root: Path,
    repo: str,
    files: Sequence[Path],
    failures: list[Failure],
    provenance: IndexRunProvenance,
) -> list[IndexedFile]:
    indexed_files: list[IndexedFile] = []
    for path in files:
        relative_path = _relative_posix(path, root)
        try:
            raw_content = path.read_bytes()
            content = raw_content.decode("utf-8")
        except OSError as exc:
            failures.append(Failure(path=relative_path, stage="read", error=str(exc)))
            continue
        except UnicodeDecodeError as exc:
            failures.append(Failure(path=relative_path, stage="read", error=str(exc)))
            continue

        try:
            items = _index_content(relative_path, content, repo)
        except Exception as exc:  # noqa: BLE001 - CLI must keep indexing other files.
            failures.append(Failure(path=relative_path, stage="index", error=str(exc)))
            continue

        file_hash = _sha256_bytes(raw_content)
        if items:
            items = [
                _with_source_provenance(
                    item,
                    provenance=provenance,
                    file_hash=file_hash,
                )
                for item in items
            ]
        indexed_files.append(IndexedFile(path=relative_path, file_hash=file_hash, items=items))
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
    return build_embedding_provider(settings.embedding)


def _write_items(
    *,
    settings: RuntimeSettings,
    repo: str,
    scope: IndexScope,
    include_patterns: Sequence[str],
    exclude_patterns: Sequence[str],
    indexed_files: Sequence[IndexedFile],
    failures: Sequence[Failure],
    embedding_provider: EmbeddingProvider | None,
) -> tuple[IncrementalPlan, int, int]:
    engine = make_engine(settings.database_url, echo=settings.sql_echo)
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        try:
            incremental_plan = _plan_incremental_changes(
                repository=repository,
                repo=repo,
                scope=scope,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
                indexed_files=indexed_files,
                failures=failures,
            )
            for path in incremental_plan.deleted_paths:
                repository.delete_by_path(repo=repo, path=path)
            items = [
                item
                for indexed_file in incremental_plan.changed_files
                for item in indexed_file.items
            ]
            for indexed_file in incremental_plan.changed_files:
                repository.delete_by_path(repo=repo, path=indexed_file.path)
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
    return incremental_plan, len(items), embedding_written


def _preview_incremental_plan(
    *,
    values: Mapping[str, str],
    repo: str,
    scope: IndexScope,
    include_patterns: Sequence[str],
    exclude_patterns: Sequence[str],
    indexed_files: Sequence[IndexedFile],
    failures: Sequence[Failure],
) -> IncrementalPlan:
    database_url = values.get("ACP_DATABASE_URL")
    if not database_url or not _database_exists(database_url):
        return IncrementalPlan(
            changed_files=[indexed_file for indexed_file in indexed_files if indexed_file.items],
            unchanged_paths=[],
            deleted_paths=[],
            items_deleted=0,
        )
    try:
        engine = make_engine(database_url)
        with Session(engine) as session:
            repository = IndexedItemRepository(session)
            return _plan_incremental_changes(
                repository=repository,
                repo=repo,
                scope=scope,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
                indexed_files=indexed_files,
                failures=failures,
            )
    except SQLAlchemyError:
        return IncrementalPlan(
            changed_files=[indexed_file for indexed_file in indexed_files if indexed_file.items],
            unchanged_paths=[],
            deleted_paths=[],
            items_deleted=0,
        )


def _plan_incremental_changes(
    *,
    repository: IndexedItemRepository,
    repo: str,
    scope: IndexScope,
    include_patterns: Sequence[str],
    exclude_patterns: Sequence[str],
    indexed_files: Sequence[IndexedFile],
    failures: Sequence[Failure],
) -> IncrementalPlan:
    failed_paths = {
        failure.path
        for failure in failures
        if failure.path is not None and failure.stage in {"read", "index"}
    }
    old_paths = {
        path
        for path in _list_scope_indexed_paths(repository=repository, repo=repo, scope=scope)
        if _is_included(path, include_patterns) and not _is_excluded(path, exclude_patterns)
    }
    changed_files: list[IndexedFile] = []
    unchanged_paths: list[str] = []
    empty_paths: set[str] = set()

    for indexed_file in indexed_files:
        existing_items = repository.list(repo=repo, path=indexed_file.path)
        existing_hashes = {item.source.file_hash for item in existing_items}
        if existing_items and existing_hashes == {indexed_file.file_hash}:
            unchanged_paths.append(indexed_file.path)
            continue
        if indexed_file.items:
            changed_files.append(indexed_file)
        else:
            empty_paths.add(indexed_file.path)

    current_success_paths = {indexed_file.path for indexed_file in indexed_files}
    deleted_paths = sorted(
        (old_paths - current_success_paths - failed_paths) | (old_paths & empty_paths)
    )
    items_deleted = sum(
        len(repository.list(repo=repo, path=deleted_path)) for deleted_path in deleted_paths
    )
    return IncrementalPlan(
        changed_files=changed_files,
        unchanged_paths=sorted(unchanged_paths),
        deleted_paths=deleted_paths,
        items_deleted=items_deleted,
    )


def _list_scope_indexed_paths(
    *,
    repository: IndexedItemRepository,
    repo: str,
    scope: IndexScope,
) -> list[str]:
    if scope.full_root:
        return repository.list_paths(repo=repo)

    paths: set[str] = set()
    for path_prefix in scope.path_prefixes:
        paths.update(repository.list_paths(repo=repo, path_prefix=path_prefix))
    for path in scope.exact_paths:
        if repository.list(repo=repo, path=path):
            paths.add(path)
    return sorted(paths)


def _summary(
    *,
    repo: str,
    database: str | None,
    files_scanned: int,
    indexed_files: Sequence[IndexedFile],
    incremental_plan: IncrementalPlan,
    scope_paths: Sequence[str],
    items_written: int,
    embedding_written: int,
    failures: Sequence[Failure],
    provenance: IndexRunProvenance,
    started: float,
) -> dict[str, Any]:
    items_estimated = sum(len(indexed_file.items) for indexed_file in indexed_files)
    return {
        "repo": repo,
        "database": database,
        "scope_paths": list(scope_paths),
        "files_scanned": files_scanned,
        "files_indexed": sum(1 for indexed_file in indexed_files if indexed_file.items),
        "files_changed": len(incremental_plan.changed_files),
        "files_unchanged": len(incremental_plan.unchanged_paths),
        "files_deleted": len(incremental_plan.deleted_paths),
        "items_estimated": items_estimated,
        "items_written": items_written,
        "items_deleted": incremental_plan.items_deleted,
        "items_failed": len(failures),
        "embedding_written": embedding_written,
        "branch": provenance.branch,
        "commit_sha": provenance.commit_sha,
        "indexed_at": _isoformat_utc(provenance.indexed_at),
        "index_batch_id": provenance.index_batch_id,
        "provenance_warnings": provenance.warnings,
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


def _build_index_run_provenance(root: Path) -> IndexRunProvenance:
    warnings: list[str] = []
    branch = _git_output(root, "branch", "--show-current")
    if not branch:
        warnings.append("git branch unavailable; branch provenance is null")
        branch = None

    commit_sha = _git_output(root, "rev-parse", "HEAD")
    if not commit_sha:
        warnings.append("git commit unavailable; commit_sha provenance is null")
        commit_sha = None

    return IndexRunProvenance(
        branch=branch,
        commit_sha=commit_sha,
        indexed_at=datetime.now(UTC),
        index_batch_id=str(uuid4()),
        warnings=warnings,
    )


def _git_output(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            check=False,
            encoding="utf-8",
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    return output or None


def _with_source_provenance(
    item: IndexedItem,
    *,
    provenance: IndexRunProvenance,
    file_hash: str,
) -> IndexedItem:
    source = item.source.model_copy(
        update={
            "branch": provenance.branch,
            "commit_sha": provenance.commit_sha,
            "file_hash": file_hash,
            "indexed_at": provenance.indexed_at,
            "index_batch_id": provenance.index_batch_id,
        }
    )
    return item.model_copy(update={"source": source})


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _redact_database_url(database_url: str | None) -> str | None:
    if not database_url:
        return None
    try:
        return make_url(database_url).render_as_string(hide_password=True)
    except Exception:  # noqa: BLE001 - summary should not fail while reporting config.
        return database_url


def _database_exists(database_url: str) -> bool:
    try:
        url = make_url(database_url)
    except Exception:  # noqa: BLE001 - invalid config will be reported by non-dry-run paths.
        return False
    if url.drivername.startswith("sqlite"):
        database = url.database
        if not database or database in {":memory:", ""}:
            return False
        return Path(database).exists()
    return True


if __name__ == "__main__":
    main()
