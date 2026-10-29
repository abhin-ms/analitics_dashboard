"""call recordings: audio the phone recorded for a call, uploaded by the
mobile app after the call — see app/api/v1/call_recordings.py.

Revision ID: 026
Revises: 025
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tele_call_recordings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("activity_id", sa.Integer(), sa.ForeignKey("tele_lead_activities.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("lead_id", sa.Integer(), sa.ForeignKey("tele_call_leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_tele_call_recordings_lead_id", "tele_call_recordings", ["lead_id"])


def downgrade():
    op.drop_index("ix_tele_call_recordings_lead_id", table_name="tele_call_recordings")
    op.drop_table("tele_call_recordings")
