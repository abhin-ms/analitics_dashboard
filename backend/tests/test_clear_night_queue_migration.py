"""Migration 027: the old night queue is cleared once — waiting leads go to
their telecaller quietly (no first-call task), the rest just leave the
queue. Runs the migration on SQLite."""
import importlib.util
from datetime import datetime
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from app.db.base import Base
from app.models import models  # noqa: F401  (register tables)

spec = importlib.util.spec_from_file_location(
    "m027", Path(__file__).resolve().parents[1] / "alembic" / "versions" / "027_clear_night_queue.py")
m027 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m027)


def test_waiting_leads_go_to_their_telecaller_quietly():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    night = datetime(2026, 10, 28, 16, 0)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO roles (id, name) VALUES (1, 'Telecaller')"))
        for uid, name, active in ((1, "Ashok", True), (2, "Gone", False), (3, "Riya", True)):
            conn.execute(text("INSERT INTO users (id, name, email, password_hash, role_id, is_active) "
                              "VALUES (:i, :n, :e, 'x', 1, :a)"), {"i": uid, "n": name, "e": f"{name}@x", "a": active})
        rows = [  # id, owner, queued for, released
            (1, None, 1, None),    # waiting for Ashok → his
            (2, None, 2, None),    # waiting for a telecaller who left → out of the queue, unassigned
            (3, 3, 1, None),       # moved to Riya by hand at night → stays Riya's
            (4, None, 1, night),   # already handed over → untouched
        ]
        for lid, owner, queued, released in rows:
            conn.execute(text(
                "INSERT INTO tele_call_leads (id, sheet_tl_name, spreadsheet_id, full_name, phone, owner_user_id, "
                "queued_at, queued_owner_id, queue_released_at) VALUES (:i, 'Hitech City', '', 'L', '9', :o, :q, :qo, :r)"),
                {"i": lid, "o": owner, "q": night, "qo": queued, "r": released})

    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            m027.upgrade()

    with engine.connect() as conn:
        got = {r[0]: r[1:] for r in conn.execute(text(
            "SELECT id, owner_user_id, queue_released_at IS NOT NULL FROM tele_call_leads"))}
        assert got == {1: (1, 1), 2: (None, 1), 3: (3, 1), 4: (None, 1)}
        assert conn.execute(text("SELECT COUNT(*) FROM tele_call_leads WHERE queued_at IS NOT NULL "
                                 "AND queue_released_at IS NULL")).scalar() == 0          # queue empty
        acts = conn.execute(text("SELECT lead_id, new_value FROM tele_lead_activities")).all()
        assert acts == [(1, "Ashok")]                                                     # on the timeline
        assert conn.execute(text("SELECT COUNT(*) FROM tele_lead_followups")).scalar() == 0  # no clock started
