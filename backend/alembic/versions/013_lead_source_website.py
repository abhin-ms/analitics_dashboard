"""lead source, website premium leads and the inbound submission log

Adds source/premium/store/device/payment fields to tele_call_leads and a
lead_submissions table logging every inbound webhook call. Additive only.

Revision ID: 013
Revises: 012
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None

COLS = [
    ("source_channel", sa.String(30)), ("is_premium", sa.Boolean()), ("preferred_store_text", sa.String(200)),
    ("customer_state", sa.String(100)), ("customer_country", sa.String(60)), ("phone_brand", sa.String(60)),
    ("preferred_date", sa.String(30)), ("payment_ref", sa.String(120)), ("payment_amount", sa.Numeric(12, 2)),
    ("paid_at", sa.DateTime()), ("external_ref", sa.String(120)),
]


def upgrade() -> None:
    for name, typ in COLS:
        kw = {"server_default": sa.false()} if name == "is_premium" else {}
        op.add_column("tele_call_leads", sa.Column(name, typ, nullable=True, **kw))
    op.add_column("tele_call_leads", sa.Column("store_id", sa.Integer(),
                  sa.ForeignKey("stores.id", name="fk_tele_leads_store"), nullable=True))
    op.create_index("ix_tele_call_leads_source_channel", "tele_call_leads", ["source_channel"])
    op.create_unique_constraint("uq_tele_call_leads_external_ref", "tele_call_leads", ["external_ref"])

    op.create_table(
        "lead_submissions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("external_ref", sa.String(120), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("message", sa.String(300), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("tele_call_leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("remote_ip", sa.String(60), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_lead_submissions_external_ref", "lead_submissions", ["external_ref"])


def downgrade() -> None:
    op.drop_index("ix_lead_submissions_external_ref", table_name="lead_submissions")
    op.drop_table("lead_submissions")
    op.drop_constraint("fk_tele_leads_store", "tele_call_leads", type_="foreignkey")
    op.drop_constraint("uq_tele_call_leads_external_ref", "tele_call_leads", type_="unique")
    op.drop_index("ix_tele_call_leads_source_channel", table_name="tele_call_leads")
    op.drop_column("tele_call_leads", "store_id")
    for name, _ in reversed(COLS):
        op.drop_column("tele_call_leads", name)
