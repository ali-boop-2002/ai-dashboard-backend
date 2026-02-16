"""add_rent_date_to_units

Revision ID: 7080a42f2c62
Revises: 3d80f744c87b
Create Date: 2026-02-14 15:17:58.858309

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7080a42f2c62'
down_revision: Union[str, Sequence[str], None] = '3d80f744c87b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add rent_date column to units table (UTC)."""
    op.add_column(
        "units",
        sa.Column("rent_date", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove rent_date column from units table."""
    op.drop_column("units", "rent_date")
