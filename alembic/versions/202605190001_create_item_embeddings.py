from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import VECTOR


revision = "202605190001"
down_revision = "202605120001"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
        # 历史阶段验证写入过没有模型身份的测试向量，迁移到 legacy 身份后再删除旧列。
        op.execute(
            """
            INSERT INTO item_embeddings (item_id, provider, model, dimension, embedding)
            SELECT id, 'legacy', 'legacy', vector_dims(embedding), embedding
            FROM indexed_items
            WHERE embedding IS NOT NULL
            """
        )

    op.drop_column("indexed_items", "embedding")


def downgrade() -> None:
    op.add_column(
        "indexed_items",
        sa.Column("embedding", VECTOR().with_variant(sa.JSON(), "sqlite"), nullable=True),
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            UPDATE indexed_items
            SET embedding = selected.embedding
            FROM (
                SELECT DISTINCT ON (item_id) item_id, embedding
                FROM item_embeddings
                ORDER BY item_id, provider, model, dimension
            ) AS selected
            WHERE indexed_items.id = selected.item_id
            """
        )

    op.drop_table("item_embeddings")
