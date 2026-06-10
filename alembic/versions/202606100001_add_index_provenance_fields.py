from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202606100001"
down_revision = "202605190001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "indexed_items",
        sa.Column("branch", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "indexed_items",
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "indexed_items",
        sa.Column("file_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "indexed_items",
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "indexed_items",
        sa.Column("index_batch_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("indexed_items", "index_batch_id")
    op.drop_column("indexed_items", "indexed_at")
    op.drop_column("indexed_items", "file_hash")
    op.drop_column("indexed_items", "commit_sha")
    op.drop_column("indexed_items", "branch")
