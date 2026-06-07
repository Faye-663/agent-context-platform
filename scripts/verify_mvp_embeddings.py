from __future__ import annotations

import argparse
import os
from pathlib import Path

from sqlalchemy.orm import Session

from agent_context_platform.embeddings import (
    embed_and_save_items,
)
from agent_context_platform.indexers import (
    index_java_source,
    index_markdown_document,
    index_sql_ddl,
)
from agent_context_platform.models import AssetType
from agent_context_platform.retrieval import HybridSearchQuery, HybridSearchService
from agent_context_platform.runtime import build_embedding_provider, load_runtime_settings
from agent_context_platform.storage import IndexedItemRepository, make_engine


def main() -> None:
    # MVP embedding 验证会真实调用外部 provider；运行前必须确认 .env/ACP_EMBEDDING_*。
    args = _parse_args()
    _load_env_file(args.env_file)
    settings = load_runtime_settings()
    if settings.embedding is None:
        raise SystemExit("缺少 ACP_EMBEDDING_* 配置，无法验证 MVP embedding。")

    provider = build_embedding_provider(settings.embedding)
    engine = make_engine(settings.database_url, echo=settings.sql_echo)
    items = _sample_items()
    sample_item_ids = {item.id for item in items}

    with Session(engine) as session:
        repository = IndexedItemRepository(session)
        saved_count = embed_and_save_items(repository, provider, items)
        session.commit()

        code_results = repository.list_with_embeddings(
            asset_type=AssetType.CODE,
            embedding_identity=provider.identity,
        )
        schema_results = repository.list_with_embeddings(
            asset_type=AssetType.DB_SCHEMA,
            embedding_identity=provider.identity,
        )
        doc_results = repository.list_with_embeddings(
            asset_type=AssetType.DOC,
            embedding_identity=provider.identity,
        )
        search_results = HybridSearchService(repository, provider).search(
            HybridSearchQuery(
                query="payment message build",
                asset_type=AssetType.CODE,
                limit=3,
                filters={"language": "java"},
            )
        )

    code_results = _filter_rows_by_ids(code_results, sample_item_ids)
    schema_results = _filter_rows_by_ids(schema_results, sample_item_ids)
    doc_results = _filter_rows_by_ids(doc_results, sample_item_ids)
    _assert_embeddings("code", code_results, settings.embedding.dimension)
    _assert_embeddings("db_schema", schema_results, settings.embedding.dimension)
    _assert_embeddings("doc", doc_results, settings.embedding.dimension)
    if not search_results:
        raise AssertionError("query embedding search returned no code results")
    if (
        not search_results[0].score_parts
        or search_results[0].score_parts["vector"] <= 0
    ):
        raise AssertionError("query embedding search did not contribute vector score")

    print("MVP embedding verification passed")
    print(f"provider={provider.identity.provider}")
    print(f"model={settings.embedding.model}")
    print(f"dimension={settings.embedding.dimension}")
    print(f"batch_size={settings.embedding.batch_size}")
    print(f"saved_count={saved_count}")
    print(
        "embedding_counts="
        f"code:{len(code_results)},db_schema:{len(schema_results)},doc:{len(doc_results)}"
    )
    print(
        "top_code_result="
        f"{search_results[0].item.id},vector={search_results[0].score_parts['vector']}"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify MVP embedding generation and storage."
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


def _sample_items():
    # 使用最小脱敏样本覆盖 code/db_schema/doc 三类资产，验证批量 embedding 写入链路。
    java_items = index_java_source(
        "src/main/java/example/MvpPaymentService.java",
        """
        class MvpPaymentService {
            void buildPaymentMessage() {
            }
        }
        """,
    )
    sql_items = index_sql_ddl(
        "db/mvp_embedding_payment.sql",
        "CREATE TABLE mvp_embedding_payment_order (id bigint, status varchar(20));",
    )
    doc_items = index_markdown_document(
        "docs/mvp-embedding-payment.md",
        "# MVP Payment Integration\n\nBuild payment messages for order events.",
    )
    return [java_items[0], sql_items[0], doc_items[0]]


def _filter_rows_by_ids(
    rows: list[tuple[object, list[float] | None]],
    item_ids: set[str],
) -> list[tuple[object, list[float] | None]]:
    # 真实验证库可能已有其他索引项；脚本只断言本次样本写入链路。
    return [(item, embedding) for item, embedding in rows if item.id in item_ids]


def _assert_embeddings(
    name: str,
    rows: list[tuple[object, list[float] | None]],
    dimension: int,
) -> None:
    if not rows:
        raise AssertionError(f"{name} embedding rows are empty")
    for _item, embedding in rows:
        if embedding is None:
            raise AssertionError(f"{name} embedding is missing")
        if len(embedding) != dimension:
            raise AssertionError(
                f"{name} embedding dimension mismatch: expected {dimension}, "
                f"got {len(embedding)}"
            )


if __name__ == "__main__":
    main()
