from __future__ import annotations

import argparse
import os
from pathlib import Path

from sqlalchemy import delete, event
from sqlalchemy.orm import Session

from agent_context_platform.embeddings import EmbeddingIdentity
from agent_context_platform.models import AssetType, IndexedItem, SourceCitation, SourceType
from agent_context_platform.runtime import load_runtime_settings
from agent_context_platform.storage import (
    IndexedItemRecord,
    IndexedItemRepository,
    ItemEmbeddingRecord,
    make_engine,
)


ITEM_IDS = [
    "mvp-pgvector:code:vector-top",
    "mvp-pgvector:code:vector-second",
    "mvp-pgvector:code:filtered-python",
    "mvp-pgvector:db_schema:filtered-table",
]


def main() -> None:
    # MVP pgvector 验证必须连接 PostgreSQL/pgvector，用来确认排序已下推到数据库侧 <=> 算子。
    args = _parse_args()
    _load_env_file(args.env_file)
    settings = load_runtime_settings()
    engine = make_engine(settings.database_url, echo=settings.sql_echo)
    if engine.dialect.name != "postgresql":
        raise SystemExit("MVP pgvector 验证必须连接 PostgreSQL / pgvector 数据库。")

    captured_sql: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture_sql(
        _conn, _cursor, statement, _parameters, _context, _executemany
    ) -> None:
        # 捕获 SQL 是为了验证真实执行了 pgvector cosine distance，而不只是结果碰巧正确。
        captured_sql.append(statement)

    identity = EmbeddingIdentity(provider="mvp-pgvector", model="deterministic", dimension=3)
    with Session(engine) as session:
        _clear_mvp_pgvector_rows(session)
        repository = IndexedItemRepository(session)
        repository.save(
            _code_item("mvp-pgvector:code:vector-top", "VectorTop.java"),
            embedding=[0.0, 1.0, 0.0],
            embedding_identity=identity,
        )
        repository.save(
            _code_item("mvp-pgvector:code:vector-second", "VectorSecond.java"),
            embedding=[1.0, 0.0, 0.0],
            embedding_identity=identity,
        )
        repository.save(
            _python_item(),
            embedding=[0.0, 1.0, 0.0],
            embedding_identity=identity,
        )
        repository.save(
            _schema_item(),
            embedding=[0.0, 1.0, 0.0],
            embedding_identity=identity,
        )
        session.commit()

        results = repository.search_by_vector(
            asset_type=AssetType.CODE,
            query_embedding=[0.0, 1.0, 0.0],
            embedding_identity=identity,
            language="java",
            symbol_types=["method"],
            limit=1,
        )
        _clear_mvp_pgvector_rows(session)
        session.commit()

    if [(item.id, score) for item, score in results] != [
        ("mvp-pgvector:code:vector-top", 1.0)
    ]:
        raise AssertionError(f"unexpected pgvector search results: {results!r}")

    search_sql = "\n".join(captured_sql)
    if "<=>" not in search_sql:
        raise AssertionError("pgvector cosine distance operator <=> was not executed")
    if "LIMIT" not in search_sql.upper():
        raise AssertionError("pgvector search SQL did not include LIMIT")

    print("MVP pgvector search verification passed")
    print("top_result=mvp-pgvector:code:vector-top")
    print("vector_score=1.0")
    print("operator=<=>")
    print("limit_applied=true")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify MVP PostgreSQL / pgvector similarity search."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional .env file to load before reading runtime settings.",
    )
    return parser.parse_args()


def _load_env_file(path: Path | None) -> None:
    if path is None:
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", maxsplit=1)
        os.environ.setdefault(key.strip(), value.strip().strip('"'))


def _clear_mvp_pgvector_rows(session: Session) -> None:
    session.execute(
        delete(ItemEmbeddingRecord).where(ItemEmbeddingRecord.item_id.in_(ITEM_IDS))
    )
    session.execute(
        delete(IndexedItemRecord).where(IndexedItemRecord.id.in_(ITEM_IDS))
    )
    session.flush()


def _code_item(item_id: str, filename: str) -> IndexedItem:
    symbol = filename.removesuffix(".java") + ".build"
    return IndexedItem(
        id=item_id,
        asset_type=AssetType.CODE,
        title=symbol,
        content="mvp pgvector java similarity verification",
        summary=f"{symbol} deterministic vector search sample.",
        metadata={"language": "java", "symbol_type": "method"},
        source=SourceCitation(
            source_type=SourceType.CODE,
            path=f"src/main/java/example/{filename}",
            start_line=1,
            end_line=12,
            symbol=symbol,
        ),
    )


def _python_item() -> IndexedItem:
    return IndexedItem(
        id="mvp-pgvector:code:filtered-python",
        asset_type=AssetType.CODE,
        title="FilteredPython.build",
        content="mvp pgvector filtered python sample",
        summary="Python item should be filtered by language.",
        metadata={"language": "python", "symbol_type": "function"},
        source=SourceCitation(
            source_type=SourceType.CODE,
            path="src/FilteredPython.py",
            start_line=1,
            end_line=8,
            symbol="FilteredPython.build",
        ),
    )


def _schema_item() -> IndexedItem:
    return IndexedItem(
        id="mvp-pgvector:db_schema:filtered-table",
        asset_type=AssetType.DB_SCHEMA,
        title="mvp_pgvector_filtered_table",
        content="mvp pgvector filtered schema sample",
        summary="Schema item should be filtered by asset type.",
        metadata={"symbol_type": "table", "table": "mvp_pgvector_filtered_table"},
        source=SourceCitation(
            source_type=SourceType.DB_SCHEMA,
            table="mvp_pgvector_filtered_table",
        ),
    )


if __name__ == "__main__":
    main()
