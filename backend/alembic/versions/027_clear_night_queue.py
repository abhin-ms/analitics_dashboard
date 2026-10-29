"""clear the old night queue once: the leads still waiting under the old
one-every-15-minutes hand-over are given to the telecaller they were
waiting for, quietly (no WhatsApp, no pop-up, no first-call clock) and
taken out of the queue. From now on night leads are given at once and
announced one every 5 minutes — see app/services/crm/night_queue.py.
A lead whose telecaller is no longer active stays unassigned (for the
admins), just out of the queue.

Revision ID: 027
Revises: 026
Create Date: 2026-10-29
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None

WAITING = "queued_at IS NOT NULL AND queue_released_at IS NULL"


def upgrade():
    bind = op.get_bind()
    now = datetime.utcnow()
    active = "SELECT id FROM users WHERE is_active = :t"
    # timeline entry first, while the rows can still be found as waiting
    bind.execute(sa.text(f"""
        INSERT INTO tele_lead_activities (lead_id, type, old_value, new_value, notes, created_at)
        SELECT l.id, 'assignment', 'Unassigned', u.name,
               'Old night queue cleared — given to its telecaller quietly (no message)', :now
        FROM tele_call_leads l JOIN users u ON u.id = l.queued_owner_id
        WHERE l.queued_at IS NOT NULL AND l.queue_released_at IS NULL AND l.owner_user_id IS NULL
          AND u.is_active = :t
    """), {"now": now, "t": True})
    bind.execute(sa.text(f"""
        UPDATE tele_call_leads
        SET owner_user_id = queued_owner_id, assignment_source = 'auto', assigned_at = :now, queue_released_at = :now
        WHERE {WAITING} AND owner_user_id IS NULL AND queued_owner_id IN ({active})
    """), {"now": now, "t": True})
    # the rest (taken by hand meanwhile, or their telecaller has left): just out of the queue
    bind.execute(sa.text(f"UPDATE tele_call_leads SET queue_released_at = :now WHERE {WAITING}"), {"now": now})


def downgrade():
    pass  # a one-off clean-up; nothing to undo
