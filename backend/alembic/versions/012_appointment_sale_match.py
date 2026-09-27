"""appointment → sale matching fields on tele_appointments

The daily sale check compares each appointment's customer phone with the
MCP sales report (appointment day + 2 days). These columns store the
result. Purely additive; downgrade removes only these.

Revision ID: 012
Revises: 011
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tele_appointments", sa.Column("sale_match_status", sa.String(20), nullable=True))
    op.add_column("tele_appointments", sa.Column("sale_checked_at", sa.DateTime(), nullable=True))
    op.add_column("tele_appointments", sa.Column("matched_purchase_id", sa.String(40), nullable=True))
    op.add_column("tele_appointments", sa.Column("matched_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("tele_appointments", sa.Column("matched_shop", sa.String(150), nullable=True))
    op.add_column("tele_appointments", sa.Column("matched_sale_date", sa.String(20), nullable=True))
    op.create_index("ix_tele_appointments_matched_purchase_id", "tele_appointments", ["matched_purchase_id"])


def downgrade() -> None:
    op.drop_index("ix_tele_appointments_matched_purchase_id", table_name="tele_appointments")
    for col in ("matched_sale_date", "matched_shop", "matched_amount", "matched_purchase_id",
                "sale_checked_at", "sale_match_status"):
        op.drop_column("tele_appointments", col)
