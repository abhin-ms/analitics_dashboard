"""payment links: the ₹99 Razorpay link a telecaller sends a lead on
WhatsApp after a call, and whether it was paid — see
app/services/crm/payment_links.py.

Revision ID: 028
Revises: 027
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payment_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("tele_call_leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sent_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("token", sa.String(40), nullable=False, unique=True),
        sa.Column("mode", sa.String(12), nullable=False, server_default="link"),
        sa.Column("reference_id", sa.String(40), nullable=True, unique=True),
        sa.Column("rzp_link_id", sa.String(60), nullable=True, unique=True),
        sa.Column("short_url", sa.String(300), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="99"),
        sa.Column("status", sa.String(20), nullable=False, server_default="sent"),
        sa.Column("customer_name", sa.String(200), nullable=True),
        sa.Column("customer_phone", sa.String(30), nullable=True),
        sa.Column("phone_model", sa.String(120), nullable=True),
        sa.Column("service", sa.String(120), nullable=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="SET NULL"), nullable=True),
        sa.Column("visit_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("whatsapp_message_id", sa.Integer(), sa.ForeignKey("whatsapp_messages.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("payment_id", sa.String(60), nullable=True),
        sa.Column("paid_amount", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_payment_links_lead_id", "payment_links", ["lead_id"])
    op.create_index("ix_payment_links_sent_by", "payment_links", ["sent_by"])
    op.create_index("ix_payment_links_created_at", "payment_links", ["created_at"])
    op.create_index("ix_payment_links_paid_at", "payment_links", ["paid_at"])


def downgrade():
    op.drop_table("payment_links")
