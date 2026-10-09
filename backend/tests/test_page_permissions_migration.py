"""Migration 020: page permissions keep every role's menu exactly as before,
and downgrade puts back what it removed. Runs the migration on SQLite."""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from app.db.base import Base
from app.models import models  # noqa: F401  (register tables)

spec = importlib.util.spec_from_file_location(
    "m020", Path(__file__).resolve().parents[1] / "alembic" / "versions" / "020_page_permissions.py")
m020 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m020)

BEFORE = {  # role -> resources with View before the migration (seed defaults)
    "CEO": {"dashboard", "operations", "team_leaders", "leads", "reports", "users"},
    "Team Leader": {"dashboard", "operations", "team_leaders", "leads", "reports", "performance", "instagram"},
    "Telecaller": {"dashboard", "leads", "operations"},
    "Store Owner": {"dashboard"},
}


def _views(conn, role):
    return set(conn.execute(text(
        "SELECT p.resource FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id "
        "JOIN roles r ON r.id = rp.role_id WHERE r.name = :n AND p.action = 'view'"), {"n": role}).scalars())


def _run(fn, engine):
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            fn()


def test_menus_unchanged_then_restored():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        resources = sorted(set().union(*BEFORE.values()))
        for r in resources:
            conn.execute(text("INSERT INTO permissions (resource, action) VALUES (:r, 'view')"), {"r": r})
        for role, views in BEFORE.items():
            conn.execute(text("INSERT INTO roles (name) VALUES (:n)"), {"n": role})
            for r in views:
                conn.execute(text(
                    "INSERT INTO role_permissions (role_id, permission_id) SELECT r.id, p.id FROM roles r, permissions p "
                    "WHERE r.name = :n AND p.resource = :res AND p.action = 'view'"), {"n": role, "res": r})

    _run(m020.upgrade, engine)
    with engine.connect() as conn:
        # CEO saw Store Overview (via operations) and the four "dashboard" pages
        assert _views(conn, "CEO") >= {"store_overview", "social_performance", "stock_position",
                                       "country_comparison", "sales_reports", "operations", "users"}
        # Team Leader: those pages were hidden for TLs, so they don't gain them,
        # and the ticked-but-hidden Operations/Team Leaders/Reports/Performance/
        # Instagram views are removed — their menu is unchanged
        assert _views(conn, "Team Leader") == {"dashboard", "leads", "social_performance"}
        # Telecaller: only Dashboard and the Leads pages, as before
        assert _views(conn, "Telecaller") == {"dashboard", "leads"}
        # Store Owner: Dashboard + Social Performance (shown to store accounts)
        assert _views(conn, "Store Owner") == {"dashboard", "social_performance"}

    _run(m020.downgrade, engine)
    with engine.connect() as conn:
        for role, views in BEFORE.items():
            assert _views(conn, role) == views, role
        assert not conn.execute(text("SELECT COUNT(*) FROM permissions WHERE resource = 'store_overview'")).scalar()
