"""daily_store_tracker.extra_fields: sheet columns added later

Google/review columns an admin adds to the Daily Input tab (e.g. "Positive
reviews") have no column of their own; the sync keeps them here by header
label so the store portfolio can show them without a code change. Existing
rows stay NULL.

Revision ID: 019
Revises: 018
Create Date: 2026-10-08
"""
from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("daily_store_tracker", sa.Column("extra_fields", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("daily_store_tracker", "extra_fields")
