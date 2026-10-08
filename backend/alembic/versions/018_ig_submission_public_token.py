"""ig_form_submissions.public_token: unguessable hosted-form links

The public booking page used to be addressed by the sequential submission
id, so anyone could walk every customer's details. Links now carry a random
token instead. Existing rows stay NULL; the bot assigns a token the next
time it sends a link for one, and old id-based links stop working.

Revision ID: 018
Revises: 017
Create Date: 2026-10-08
"""
from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ig_form_submissions", sa.Column("public_token", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_ig_form_submissions_public_token", "ig_form_submissions", ["public_token"])


def downgrade() -> None:
    op.drop_constraint("uq_ig_form_submissions_public_token", "ig_form_submissions", type_="unique")
    op.drop_column("ig_form_submissions", "public_token")
