"""WhatsApp Business: contact numbers (CEO, team leaders, telecallers,
stores) and a log of sent template messages with their delivery status.
The Cloud API credentials live in the settings table ("whatsapp.config").

Revision ID: 024
Revises: 023
Create Date: 2026-10-18
"""
from alembic import op
import sqlalchemy as sa

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "whatsapp_contacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(100), nullable=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_wa_contacts_role", "whatsapp_contacts", ["role"])
    op.create_table(
        "whatsapp_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("wa_message_id", sa.String(128), nullable=True, unique=True),
        sa.Column("to_phone", sa.String(20), nullable=False),
        sa.Column("template", sa.String(100), nullable=False),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("purpose", sa.String(30), nullable=False, server_default="test"),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="accepted"),
        sa.Column("error_code", sa.String(20), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("tele_call_leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sent_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("failed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_wa_messages_created", "whatsapp_messages", ["created_at"])


def downgrade():
    op.drop_index("ix_wa_messages_created", table_name="whatsapp_messages")
    op.drop_table("whatsapp_messages")
    op.drop_index("ix_wa_contacts_role", table_name="whatsapp_contacts")
    op.drop_table("whatsapp_contacts")
