"""add_paid_and_over_due_to_units

Revision ID: 45b7e67d5e06
Revises: 7080a42f2c62
Create Date: 2026-02-14 15:19:35.501036

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '45b7e67d5e06'
down_revision: Union[str, Sequence[str], None] = '7080a42f2c62'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add paid and over_due columns to units table."""
    op.add_column(
        "units",
        sa.Column("paid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "units",
        sa.Column("over_due", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    """Remove paid and over_due columns from units table."""
    op.drop_column("units", "paid")
    op.drop_column("units", "over_due")
