"""MCP bills: customer, salesman and plan fields from the Sales Report API,
so a bill's customer mobile can be matched to a lead automatically.

Revision ID: 023
Revises: 022
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None

COLUMNS = [
    ("customer_name", sa.String(150)), ("mobile", sa.String(30)), ("mobile10", sa.String(10)),
    ("salesman", sa.String(150)), ("purchase_type", sa.String(80)), ("is_care_plus", sa.Boolean()),
    ("installation_status", sa.String(20)), ("payment_status", sa.String(20)), ("mcp_shop_id", sa.Integer()),
]


def upgrade():
    for name, type_ in COLUMNS:
        op.add_column("mcp_bills", sa.Column(name, type_, nullable=True))
    op.create_index("ix_mcp_bills_mobile10", "mcp_bills", ["mobile10"])


def downgrade():
    op.drop_index("ix_mcp_bills_mobile10", table_name="mcp_bills")
    for name, _ in reversed(COLUMNS):
        op.drop_column("mcp_bills", name)
