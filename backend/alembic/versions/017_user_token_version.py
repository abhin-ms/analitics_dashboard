"""users.token_version: end a user's sessions on every device

Every access/refresh token carries the version it was issued with; bumping
it (password change, deactivation) makes all of that user's existing tokens
invalid. Existing rows start at 0, which also matches tokens issued before
this column existed, so nobody is signed out by the migration itself.

Revision ID: 017
Revises: 016
Create Date: 2026-10-07
"""
from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("users", "token_version")
