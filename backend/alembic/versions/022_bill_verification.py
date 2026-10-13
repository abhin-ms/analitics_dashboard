"""Bill verification: MCP bills kept per transaction, and the bill number
a lead bought with (see app/services/crm/bill_verify.py).

Revision ID: 022
Revises: 021
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mcp_bills",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("shop", sa.String(150), server_default=""),
        sa.Column("category", sa.String(60), server_default=""),
        sa.Column("model", sa.String(150), server_default=""),
        sa.Column("imei", sa.String(40), server_default=""),
        sa.Column("amount", sa.Numeric(12, 2), server_default="0"),
        sa.Column("discount", sa.Numeric(12, 2), server_default="0"),
        sa.Column("paid", sa.Boolean(), server_default=sa.false()),
        sa.Column("country_id", sa.Integer(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_mcp_bills_date", "mcp_bills", ["date"])
    op.add_column("tele_call_leads", sa.Column("bill_no", sa.String(30), nullable=True))
    op.add_column("tele_call_leads", sa.Column("bill_status", sa.String(20), nullable=True))
    op.add_column("tele_call_leads", sa.Column("bill_note", sa.String(200), nullable=True))
    op.add_column("tele_call_leads", sa.Column("bill_checked_at", sa.DateTime(), nullable=True))
    op.create_index("ix_tele_call_leads_bill_no", "tele_call_leads", ["bill_no"])


def downgrade():
    op.drop_index("ix_tele_call_leads_bill_no", table_name="tele_call_leads")
    for col in ("bill_checked_at", "bill_note", "bill_status", "bill_no"):
        op.drop_column("tele_call_leads", col)
    op.drop_index("ix_mcp_bills_date", table_name="mcp_bills")
    op.drop_table("mcp_bills")
