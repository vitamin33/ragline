"""Add idempotency fields to orders table

Revision ID: 08b04962867a
Revises: 674c4fc5da21
Create Date: 2025-08-26 19:27:20.788051

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "08b04962867a"
down_revision: Union[str, Sequence[str], None] = "674c4fc5da21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add idempotency_key column for duplicate request detection
    op.add_column("orders", sa.Column("idempotency_key", sa.String(length=255), nullable=True))

    # Add response_json column to store cached responses
    op.add_column("orders", sa.Column("response_json", sa.JSON(), nullable=True))

    # Add unique constraint on idempotency_key for duplicate prevention
    op.create_unique_constraint("uq_orders_idempotency_key", "orders", ["idempotency_key"])


def downgrade() -> None:
    """Downgrade schema."""
    # Remove unique constraint first
    op.drop_constraint("uq_orders_idempotency_key", "orders", type_="unique")

    # Remove columns
    op.drop_column("orders", "response_json")
    op.drop_column("orders", "idempotency_key")
