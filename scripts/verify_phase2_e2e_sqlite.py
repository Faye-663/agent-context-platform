from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from agent_context_platform.indexers import (
    index_java_source,
    index_markdown_document,
    index_sql_ddl,
)
from agent_context_platform.models import AssetType
from agent_context_platform.storage import (
    Base,
    IndexedItemRecord,
    IndexedItemRepository,
    ItemEmbeddingRecord,
    make_engine,
)


REPO_NAME = "phase2-e2e"
JAVA_PATH = "src/main/java/example/PaymentMessageBuilder.java"
SQL_PATH = "schema/payment.sql"
MARKDOWN_PATH = "docs/payment.md"


def main() -> None:
    args = _parse_args()
    result = verify_phase2_e2e(
        sample_root=args.sample_root,
        sqlite_db=args.sqlite_db or args.sample_root / "indexed-items.sqlite",
        reset=not args.keep_existing,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def verify_phase2_e2e(
    *,
    sample_root: Path,
    sqlite_db: Path,
    reset: bool = True,
) -> dict[str, Any]:
    sample_root = sample_root.resolve()
    sqlite_db = sqlite_db.resolve()
    _assert_required_files(sample_root)
    sqlite_db.parent.mkdir(parents=True, exist_ok=True)

    items = _index_sample_files(sample_root)
    engine = make_engine(f"sqlite:///{sqlite_db.as_posix()}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        if reset:
            # 保留 SQLite 文件本身，避免 IDE 打开数据库时 Windows 文件锁导致验证失败。
            _clear_indexed_rows(session)
        repository = IndexedItemRepository(session)
        for item in items:
            repository.save(item)
        session.commit()

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        code_items = repository.list(asset_type=AssetType.CODE)
        schema_items = repository.list(asset_type=AssetType.DB_SCHEMA)
        doc_items = repository.list(asset_type=AssetType.DOC)

    method_item = next(item for item in code_items if item.title.endswith(".build"))
    table_item = next(item for item in schema_items if item.title == "payment_order")
    doc_item = next(item for item in doc_items if item.title == "Message Generation")

    return {
        "status": "PASS",
        "sample_root": str(sample_root),
        "sqlite_db": str(sqlite_db),
        "indexed_total": len(items),
        "persisted_counts": {
            "code": len(code_items),
            "db_schema": len(schema_items),
            "doc": len(doc_items),
        },
        "method_source": method_item.source.model_dump(mode="json"),
        "table_metadata": table_item.metadata,
        "doc_source": doc_item.source.model_dump(mode="json"),
    }


def _parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    default_sample_root = repo_root / ".local" / "phase2-e2e"
    parser = argparse.ArgumentParser(
        description="Verify phase 2 indexers with persisted SQLite sample data."
    )
    parser.add_argument(
        "--sample-root",
        type=Path,
        default=default_sample_root,
        help="Directory containing phase2-e2e Java, SQL and Markdown sample files.",
    )
    parser.add_argument(
        "--sqlite-db",
        type=Path,
        default=None,
        help="SQLite database file to create. Defaults to sample-root/indexed-items.sqlite.",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Keep the existing SQLite file instead of recreating it before verification.",
    )
    return parser.parse_args()


def _assert_required_files(sample_root: Path) -> None:
    missing = [
        path for path in (JAVA_PATH, SQL_PATH, MARKDOWN_PATH) if not (sample_root / path).is_file()
    ]
    if missing:
        raise FileNotFoundError(
            "phase2-e2e sample files are missing: " + ", ".join(missing)
        )


def _clear_indexed_rows(session: Session) -> None:
    session.execute(delete(ItemEmbeddingRecord))
    session.execute(delete(IndexedItemRecord))
    session.flush()


def _index_sample_files(sample_root: Path):
    java_items = index_java_source(
        JAVA_PATH,
        (sample_root / JAVA_PATH).read_text(encoding="utf-8"),
        repo=REPO_NAME,
    )
    sql_items = index_sql_ddl(
        SQL_PATH,
        (sample_root / SQL_PATH).read_text(encoding="utf-8"),
        repo=REPO_NAME,
    )
    doc_items = index_markdown_document(
        MARKDOWN_PATH,
        (sample_root / MARKDOWN_PATH).read_text(encoding="utf-8"),
        repo=REPO_NAME,
    )
    return java_items + sql_items + doc_items


if __name__ == "__main__":
    main()
