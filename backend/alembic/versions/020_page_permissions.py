"""Page permissions: every menu page gets its own tick in Roles & Permissions

Several pages had no permission of their own (Store Overview used
"operations"; Social Performance, Stock Position, Country Comparison and
Sales Reports used "dashboard"; Sheet Assignments used "leads"), and the menu
also hid pages by role name regardless of the ticks. From now on the ticks
alone decide what each role sees.

So that nobody's menu changes on deploy, this migration reads each role's
current ticks, works out what the old menu rules showed it, then
  * grants View on the new page permissions it could already see, and
  * removes View on pages it had ticked but the old role rules hid
    (recorded in settings, so downgrade can put them back).

Revision ID: 020
Revises: 019
Create Date: 2026-10-09
"""
import json
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None

NEW_RESOURCES = ["store_overview", "social_performance", "stock_position", "country_comparison",
                 "sales_reports", "sheet_assignments"]
ACTIONS = ["view", "create", "edit", "delete", "export", "manage"]
REVOKED_KEY = "migration_020_revoked_views"

# The menu as it was before this migration: (path, permission it used,
# permission it uses now, section).
PAGES = [
    ("/dashboard", "dashboard", "dashboard", "main"),
    ("/sales-overview", "operations", "store_overview", "main"),
    ("/operations", "operations", "operations", "main"),
    ("/team-leaders", "team_leaders", "team_leaders", "main"),
    ("/leads", "leads", "leads", "main"),
    ("/leads/update", "leads", "leads", "main"),
    ("/campaigns", "campaigns", "campaigns", "main"),
    ("/tasks", "tasks", "tasks", "main"),
    ("/investments", "investments", "investments", "main"),
    ("/performance", "performance", "performance", "main"),
    ("/social-performance", "dashboard", "social_performance", "main"),
    ("/reports", "reports", "reports", "main"),
    ("/stock-position", "dashboard", "stock_position", "main"),
    ("/country-comparison", "dashboard", "country_comparison", "main"),
    ("/sales-reports", "dashboard", "sales_reports", "main"),
    ("/instagram", "instagram", "instagram", "instagram"),
    ("/settings/roles", "settings", "settings", "settings"),
    ("/settings/users", "users", "users", "settings"),
    ("/settings/sheet-assignments", "leads", "sheet_assignments", "settings"),
]
HIDDEN_FOR_TL = {"/operations", "/stock-position", "/country-comparison", "/investments", "/sales-overview",
                 "/sales-reports", "/team-leaders", "/reports", "/performance"}
HIDDEN_FOR_TELECALLER = {"/operations", "/stock-position", "/country-comparison", "/investments",
                         "/sales-overview", "/sales-reports", "/team-leaders", "/campaigns", "/tasks",
                         "/performance", "/reports", "/social-performance"}


def _visible_before(role: str, views: set[str], path: str, old_res: str, section: str) -> bool:
    if old_res not in views:
        return False
    if section != "main":  # Instagram and Settings sections were hidden for these two roles
        return role not in ("Team Leader", "Telecaller")
    if role == "Telecaller":
        return path not in HIDDEN_FOR_TELECALLER
    if role in ("Team Leader", "Store Owner", "Store Staff"):
        return path not in HIDDEN_FOR_TL
    return True


def upgrade() -> None:
    conn = op.get_bind()
    perm_id = {}
    for res in NEW_RESOURCES:
        for act in ACTIONS:
            found = conn.execute(sa.text("SELECT id FROM permissions WHERE resource=:r AND action=:a"),
                                 {"r": res, "a": act}).scalar()
            if not found:
                conn.execute(sa.text("INSERT INTO permissions (resource, action, created_at) VALUES (:r, :a, :t)"),
                             {"r": res, "a": act, "t": datetime.utcnow()})
                found = conn.execute(sa.text("SELECT id FROM permissions WHERE resource=:r AND action=:a"),
                                     {"r": res, "a": act}).scalar()
            perm_id[(res, act)] = found
    view_id = dict(conn.execute(sa.text("SELECT resource, id FROM permissions WHERE action='view'")).all())

    revoked: dict[str, list[str]] = {}
    for role_id, role in conn.execute(sa.text("SELECT id, name FROM roles")).all():
        views = set(conn.execute(sa.text(
            "SELECT p.resource FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id "
            "WHERE rp.role_id = :rid AND p.action = 'view'"), {"rid": role_id}).scalars().all())
        seen = {new for path, old, new, sec in PAGES if _visible_before(role, views, path, old, sec)}
        for res in NEW_RESOURCES:
            if res in seen and res not in views:
                conn.execute(sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:rid, :pid)"),
                             {"rid": role_id, "pid": perm_id[(res, "view")]})
        # a page permission ticked but never shown by the old rules
        for res in {new for _, _, new, _ in PAGES} - set(NEW_RESOURCES):
            if res in views and res not in seen:
                conn.execute(sa.text("DELETE FROM role_permissions WHERE role_id=:rid AND permission_id=:pid"),
                             {"rid": role_id, "pid": view_id[res]})
                revoked.setdefault(role, []).append(res)

    conn.execute(sa.text("DELETE FROM settings WHERE `key` = :k" if conn.dialect.name == "mysql"
                         else "DELETE FROM settings WHERE key = :k"), {"k": REVOKED_KEY})
    conn.execute(sa.text("INSERT INTO settings (`key`, value, updated_at) VALUES (:k, :v, :t)" if conn.dialect.name == "mysql"
                         else "INSERT INTO settings (key, value, updated_at) VALUES (:k, :v, :t)"),
                 {"k": REVOKED_KEY, "v": json.dumps(revoked), "t": datetime.utcnow()})


def downgrade() -> None:
    conn = op.get_bind()
    key_col = "`key`" if conn.dialect.name == "mysql" else "key"
    raw = conn.execute(sa.text(f"SELECT value FROM settings WHERE {key_col} = :k"), {"k": REVOKED_KEY}).scalar()
    for role, resources in (json.loads(raw) if raw else {}).items():
        role_id = conn.execute(sa.text("SELECT id FROM roles WHERE name = :n"), {"n": role}).scalar()
        for res in resources:
            pid = conn.execute(sa.text("SELECT id FROM permissions WHERE resource=:r AND action='view'"),
                               {"r": res}).scalar()
            if role_id and pid:
                conn.execute(sa.text("INSERT INTO role_permissions (role_id, permission_id) VALUES (:rid, :pid)"),
                             {"rid": role_id, "pid": pid})
    for res in NEW_RESOURCES:
        conn.execute(sa.text("DELETE FROM role_permissions WHERE permission_id IN "
                             "(SELECT id FROM permissions WHERE resource = :r)"), {"r": res})
        conn.execute(sa.text("DELETE FROM permissions WHERE resource = :r"), {"r": res})
    conn.execute(sa.text(f"DELETE FROM settings WHERE {key_col} = :k"), {"k": REVOKED_KEY})
