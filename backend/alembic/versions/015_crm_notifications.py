"""live "new lead" notifications (bell, sound, popup)

One row per person per new lead: the owner, the branch team, or — for an
unassigned lead — every telecaller and admin. Additive only.

Revision ID: 015
Revises: 014
Create Date: 2026-10-02
"""
from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE",
                                                          name="fk_crm_notif_user"), nullable=False),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("tele_call_leads.id", ondelete="CASCADE",
                                                          name="fk_crm_notif_lead"), nullable=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.String(300), nullable=True),
        sa.Column("is_hot", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_crm_notif_user_read", "crm_notifications", ["user_id", "read_at"])
    op.create_index("ix_crm_notif_user_time", "crm_notifications", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("crm_notifications")
