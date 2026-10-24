"""night queue for leads: a lead arriving outside working hours (8 PM –
10:30 AM) waits for its telecaller and is handed over one by one next
morning — see app/services/crm/night_queue.py.

Revision ID: 025
Revises: 024
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tele_call_leads", sa.Column("queued_at", sa.DateTime(), nullable=True))
    op.add_column("tele_call_leads", sa.Column(
        "queued_owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL",
                                                       name="fk_tele_call_leads_queued_owner"), nullable=True))
    op.add_column("tele_call_leads", sa.Column("queue_released_at", sa.DateTime(), nullable=True))
    op.create_index("ix_tele_call_leads_queued_owner_id", "tele_call_leads", ["queued_owner_id"])


def downgrade():
    op.drop_index("ix_tele_call_leads_queued_owner_id", table_name="tele_call_leads")
    op.drop_constraint("fk_tele_call_leads_queued_owner", "tele_call_leads", type_="foreignkey")
    op.drop_column("tele_call_leads", "queue_released_at")
    op.drop_column("tele_call_leads", "queued_owner_id")
    op.drop_column("tele_call_leads", "queued_at")
