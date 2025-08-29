"""Add idempotency fields to orders table

Revision ID: add_idempotency_2025
Revises: 08b04962867a
Create Date: 2025-08-29 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_idempotency_2025"
down_revision: Union[str, None] = "08b04962867a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add idempotency_key and response_json columns to orders table
    op.add_column(
        "orders", sa.Column("idempotency_key", sa.String(length=255), nullable=True)
    )
    op.add_column("orders", sa.Column("response_json", sa.JSON(), nullable=True))

    # Create index on idempotency_key for performance
    op.create_index("ix_orders_idempotency_key", "orders", ["idempotency_key"])

    # Create unique constraint on tenant_id + idempotency_key to prevent duplicates
    op.create_unique_constraint(
        "uq_orders_idempotency_key", "orders", ["tenant_id", "idempotency_key"]
    )


def downgrade() -> None:
    # Drop constraints and index
    op.drop_constraint("uq_orders_idempotency_key", "orders", type_="unique")
    op.drop_index("ix_orders_idempotency_key", table_name="orders")

    # Drop columns
    op.drop_column("orders", "response_json")
    op.drop_column("orders", "idempotency_key")
