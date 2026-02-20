"""add documents table

Revision ID: 1c2e7a5d9f1b
Revises: a0d0de1140fc
Create Date: 2026-02-18 04:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1c2e7a5d9f1b"
down_revision: Union[str, Sequence[str], None] = "cef4c3dbe442"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "documents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=True),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("source_type", sa.String(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("uploader_id", sa.String(), nullable=False),
        sa.Column("uploader_email", sa.String(), nullable=True),
        sa.Column("pdf_sha256", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_id", "documents", ["id"], unique=False)
    op.create_index("ix_documents_uploader_id", "documents", ["uploader_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_documents_uploader_id", table_name="documents")
    op.drop_index("ix_documents_id", table_name="documents")
    op.drop_table("documents")
