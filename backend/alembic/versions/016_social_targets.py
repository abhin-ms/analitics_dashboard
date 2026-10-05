"""social performance: per-store view targets, Facebook views, sheet update times

- social_view_targets: monthly views target per store per platform
  (instagram / youtube / facebook). Stores without a row use the company
  default, so this table starts empty.
- daily_store_tracker.fb_views: Facebook views, once the sheet has a
  FACEBOOK section.
- daily_store_tracker.row_hash / sheet_updated_at: when a store's row last
  changed in the sheet. Existing rows are back-filled from updated_at (the
  ORM only bumps it when a value actually changed).
- "Store Owner" role with dashboard:view, for owners who watch their own
  store(s). Skipped if a role with that name already exists.

Additive only.

Revision ID: 016
Revises: 015
Create Date: 2026-10-05
"""
from alembic import op
import sqlalchemy as sa

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "social_view_targets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE",
                                                           name="fk_social_target_store"), nullable=False),
        sa.Column("platform", sa.String(20), nullable=False),
        sa.Column("monthly_target", sa.BigInteger(), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL",
                                                             name="fk_social_target_user"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("store_id", "platform", name="uq_social_target_store_platform"),
    )

    op.add_column("daily_store_tracker", sa.Column("fb_views", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("daily_store_tracker", sa.Column("row_hash", sa.String(64), nullable=True))
    op.add_column("daily_store_tracker", sa.Column("sheet_updated_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE daily_store_tracker SET sheet_updated_at = COALESCE(updated_at, created_at)")

    op.execute(
        "INSERT INTO roles (name, description, created_at, updated_at) "
        "SELECT 'Store Owner', 'Owner of one or more stores; sees those stores only', NOW(), NOW() "
        "FROM DUAL WHERE NOT EXISTS (SELECT 1 FROM roles WHERE name = 'Store Owner')"
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT r.id, p.id FROM roles r JOIN permissions p "
        "ON p.resource = 'dashboard' AND p.action = 'view' "
        "WHERE r.name = 'Store Owner' AND NOT EXISTS ("
        "  SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
    )


def downgrade() -> None:
    # The Store Owner role is left in place: users may already hold it.
    op.drop_column("daily_store_tracker", "sheet_updated_at")
    op.drop_column("daily_store_tracker", "row_hash")
    op.drop_column("daily_store_tracker", "fb_views")
    op.drop_table("social_view_targets")
