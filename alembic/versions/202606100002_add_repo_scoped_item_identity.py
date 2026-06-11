from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import VECTOR


revision = "202606100002"
down_revision = "202606100001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 索引数据是可重建派生数据；repo identity 变更不尝试猜测旧数据归属。
    op.drop_table("item_embeddings")
    op.drop_index("ix_indexed_items_table_name", table_name="indexed_items")
    op.drop_index("ix_indexed_items_symbol_type", table_name="indexed_items")
    op.drop_index("ix_indexed_items_source_type", table_name="indexed_items")
    op.drop_index("ix_indexed_items_path", table_name="indexed_items")
    op.drop_index("ix_indexed_items_language", table_name="indexed_items")
    op.drop_index("ix_indexed_items_asset_type", table_name="indexed_items")
    op.drop_table("indexed_items")
    _create_repo_scoped_indexed_items()
    _create_repo_scoped_item_embeddings()


def downgrade() -> None:
    op.drop_table("item_embeddings")
    op.drop_index("ix_indexed_items_table_name", table_name="indexed_items")
    op.drop_index("ix_indexed_items_symbol_type", table_name="indexed_items")
    op.drop_index("ix_indexed_items_source_type", table_name="indexed_items")
    op.drop_index("ix_indexed_items_path", table_name="indexed_items")
    op.drop_index("ix_indexed_items_language", table_name="indexed_items")
    op.drop_index("ix_indexed_items_asset_type", table_name="indexed_items")
    op.drop_table("indexed_items")
    _create_legacy_indexed_items()
    _create_legacy_item_embeddings()


def _create_repo_scoped_indexed_items() -> None:
    op.create_table(
        "indexed_items",
        sa.Column("repo", sa.String(length=255), nullable=False),
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("file_hash", sa.String(length=64), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("index_batch_id", sa.String(length=64), nullable=True),
        sa.Column("path", sa.String(length=1000), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(length=500), nullable=True),
        sa.Column("table_name", sa.String(length=255), nullable=True),
        sa.Column("column_name", sa.String(length=255), nullable=True),
        sa.Column("heading_path", sa.String(length=1000), nullable=True),
        sa.Column("language", sa.String(length=64), nullable=True),
        sa.Column("symbol_type", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("repo", "id", name="pk_indexed_items"),
    )
    _create_indexed_item_indexes()


def _create_repo_scoped_item_embeddings() -> None:
    op.create_table(
        "item_embeddings",
        sa.Column("repo", sa.String(length=255), nullable=False),
        sa.Column("item_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", VECTOR().with_variant(sa.JSON(), "sqlite"), nullable=False),
        sa.CheckConstraint(
            "dimension > 0",
            name="ck_item_embeddings_dimension_positive",
        ),
        sa.ForeignKeyConstraint(
            ["repo", "item_id"],
            ["indexed_items.repo", "indexed_items.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "repo",
            "item_id",
            "provider",
            "model",
            "dimension",
            name="pk_item_embeddings",
        ),
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_check_constraint(
            "ck_item_embeddings_vector_matches_dimension",
            "item_embeddings",
            "vector_dims(embedding) = dimension",
        )


def _create_legacy_indexed_items() -> None:
    op.create_table(
        "indexed_items",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "metadata",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("repo", sa.String(length=255), nullable=True),
        sa.Column("branch", sa.String(length=255), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("file_hash", sa.String(length=64), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("index_batch_id", sa.String(length=64), nullable=True),
        sa.Column("path", sa.String(length=1000), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(length=500), nullable=True),
        sa.Column("table_name", sa.String(length=255), nullable=True),
        sa.Column("column_name", sa.String(length=255), nullable=True),
        sa.Column("heading_path", sa.String(length=1000), nullable=True),
        sa.Column("language", sa.String(length=64), nullable=True),
        sa.Column("symbol_type", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_indexed_item_indexes()


def _create_legacy_item_embeddings() -> None:
    op.create_table(
        "item_embeddings",
        sa.Column("item_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", VECTOR().with_variant(sa.JSON(), "sqlite"), nullable=False),
        sa.CheckConstraint(
            "dimension > 0",
            name="ck_item_embeddings_dimension_positive",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["indexed_items.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "item_id",
            "provider",
            "model",
            "dimension",
            name="pk_item_embeddings",
        ),
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_check_constraint(
            "ck_item_embeddings_vector_matches_dimension",
            "item_embeddings",
            "vector_dims(embedding) = dimension",
        )


def _create_indexed_item_indexes() -> None:
    op.create_index("ix_indexed_items_asset_type", "indexed_items", ["asset_type"])
    op.create_index("ix_indexed_items_language", "indexed_items", ["language"])
    op.create_index("ix_indexed_items_path", "indexed_items", ["path"])
    op.create_index("ix_indexed_items_source_type", "indexed_items", ["source_type"])
    op.create_index("ix_indexed_items_symbol_type", "indexed_items", ["symbol_type"])
    op.create_index("ix_indexed_items_table_name", "indexed_items", ["table_name"])
