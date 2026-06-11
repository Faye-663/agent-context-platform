from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202606110001"
down_revision = "202606100002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "symbols",
        sa.Column("repo", sa.String(length=255), nullable=False),
        sa.Column("symbol_id", sa.String(length=1000), nullable=False),
        sa.Column("path", sa.String(length=1000), nullable=False),
        sa.Column("language", sa.String(length=64), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("qualified_name", sa.String(length=1000), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column("source_item_id", sa.String(length=255), nullable=True),
        sa.Column("branch", sa.String(length=255), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("file_hash", sa.String(length=64), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("index_batch_id", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["repo", "source_item_id"],
            ["indexed_items.repo", "indexed_items.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("repo", "symbol_id", name="pk_symbols"),
    )
    op.create_index("ix_symbols_path", "symbols", ["path"])
    op.create_index("ix_symbols_language", "symbols", ["language"])
    op.create_index("ix_symbols_kind", "symbols", ["kind"])
    op.create_index("ix_symbols_name", "symbols", ["name"])
    op.create_index("ix_symbols_qualified_name", "symbols", ["qualified_name"])


def downgrade() -> None:
    op.drop_index("ix_symbols_qualified_name", table_name="symbols")
    op.drop_index("ix_symbols_name", table_name="symbols")
    op.drop_index("ix_symbols_kind", table_name="symbols")
    op.drop_index("ix_symbols_language", table_name="symbols")
    op.drop_index("ix_symbols_path", table_name="symbols")
    op.drop_table("symbols")
