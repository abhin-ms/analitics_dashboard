"""add address/maps_link to stores

So the Instagram bot (and staff) can tell a customer the real store
address instead of having no location data anywhere in the system —
Store previously only had a short region code (e.g. "AUH"), never a
street address or map link.

Revision ID: 010
Revises: 009
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("stores", sa.Column("maps_link", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("stores", "maps_link")
    op.drop_column("stores", "address")
