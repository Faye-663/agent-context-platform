from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import VECTOR


revision = "202605120001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
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
        sa.Column("embedding", VECTOR(), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("repo", sa.String(length=255), nullable=True),
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
    op.create_index("ix_indexed_items_asset_type", "indexed_items", ["asset_type"])
    op.create_index("ix_indexed_items_language", "indexed_items", ["language"])
    op.create_index("ix_indexed_items_path", "indexed_items", ["path"])
    op.create_index("ix_indexed_items_source_type", "indexed_items", ["source_type"])
    op.create_index("ix_indexed_items_symbol_type", "indexed_items", ["symbol_type"])
    op.create_index("ix_indexed_items_table_name", "indexed_items", ["table_name"])


def downgrade() -> None:
    op.drop_index("ix_indexed_items_table_name", table_name="indexed_items")
    op.drop_index("ix_indexed_items_symbol_type", table_name="indexed_items")
    op.drop_index("ix_indexed_items_source_type", table_name="indexed_items")
    op.drop_index("ix_indexed_items_path", table_name="indexed_items")
    op.drop_index("ix_indexed_items_language", table_name="indexed_items")
    op.drop_index("ix_indexed_items_asset_type", table_name="indexed_items")
    op.drop_table("indexed_items")
