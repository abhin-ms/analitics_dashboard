"""Store walk-ins and the store daily form's extra fields.

* store_walkins: daily actual / DSR walk-ins per store from the
  "Walk-ins Data" sheet (see app/services/walkins_sync.py).
* daily_submissions: inbound / outbound leads, appointments set, home
  deliveries and lost-sale reasons from the Dashboard Sheet's
  "DAILY SUBMISSION" tab (see app/services/daily_submission_sync.py).

Revision ID: 021
Revises: 020
Create Date: 2026-10-10
"""
from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "store_walkins",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("actual", sa.Integer(), nullable=True),
        sa.Column("dsr", sa.Integer(), nullable=True),
        sa.Column("sheet_store_name", sa.String(100), server_default=""),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("store_id", "date"),
    )
    op.create_index("ix_store_walkins_store_date", "store_walkins", ["store_id", "date"])
    for col in ("inbound_leads", "outbound_leads", "appointments_set", "home_deliveries"):
        op.add_column("daily_submissions", sa.Column(col, sa.Integer(), nullable=True))
    op.add_column("daily_submissions", sa.Column("lost_reasons", sa.JSON(), nullable=True))


def downgrade():
    for col in ("lost_reasons", "home_deliveries", "appointments_set", "outbound_leads", "inbound_leads"):
        op.drop_column("daily_submissions", col)
    op.drop_index("ix_store_walkins_store_date", table_name="store_walkins")
    op.drop_table("store_walkins")
