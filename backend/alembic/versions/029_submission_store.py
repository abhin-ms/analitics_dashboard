"""lead_submissions.store_id: the store a website booking named, matched once
when it arrives, so a failed payment shows to that store's team (and the
list never has to match stores again on every load).

Revision ID: 029
Revises: 028
Create Date: 2026-10-31
"""
from alembic import op
import sqlalchemy as sa

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("lead_submissions", sa.Column(
        "store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="SET NULL", name="fk_lead_submissions_store"),
        nullable=True))
    op.create_index("ix_lead_submissions_store_id", "lead_submissions", ["store_id"])


def downgrade():
    op.drop_index("ix_lead_submissions_store_id", table_name="lead_submissions")
    op.drop_constraint("fk_lead_submissions_store", "lead_submissions", type_="foreignkey")
    op.drop_column("lead_submissions", "store_id")
