"""Daily appointment → sale check against the MCP sales report.

For every appointment, the MCP transaction list is searched for a New Sale
to the lead's phone number (last 10 digits; the MCP's customer search is a
"contains" match on phone/IMEI) from the appointment day up to 2 days
after. A match turns the lead into a Sale Conversion and marks the
appointment attended. When the 2-day window has passed with no sale, the
appointment is marked "no sale" and the owner gets a call-back task.

Runs every day (scheduler) and on demand ("Check sales now").
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.models import TeleAppointment, TeleCallLead
from .config import get_automation
from .engine import (
    add_activity, close_open_followups, create_alert, create_followup, emit_alerts, mark_edited,
    norm_phone, parse_amount, recompute_next_follow_up, refresh_derived, resolve_alerts_for_lead,
    team_leader_ids,
)
from .timeutil import add_working_minutes, from_ist, ist_today, parse_sheet_datetime, to_ist, utcnow

logger = logging.getLogger(__name__)

MATCH_WINDOW_DAYS = 2      # appointment day + 2 days
MCP_INDIA_COUNTRY_ID = 1   # all telecalling city sheets are in India

Fetcher = Callable[[date, date, str], Awaitable[list[dict]]]


async def mcp_sales_for_phone(start: date, end: date, phone10: str) -> list[dict]:
    """New-sale rows from the MCP for a customer phone in [start, end]."""
    from ..smart_service_client import smart_service
    from ..mcp_parsers import parse_transaction_detail
    raw = await smart_service.transaction_detail(
        from_date=start.isoformat(), to_date=end.isoformat(), country_id=MCP_INDIA_COUNTRY_ID,
        customer_search=phone10, limit=50,
    )
    return parse_transaction_detail(raw)


def _is_new_sale(row: dict) -> bool:
    return "new sale" in (row.get("category") or "").lower() and float(row.get("amount") or 0) > 0


async def _materialise_sheet_appointments(db: AsyncSession, scope_clause, first: date, last: date) -> int:
    """Sheet 'Appointment Date' values in range become appointment records
    (source='sheet') so their check result can be stored."""
    leads = (await db.execute(
        select(TeleCallLead).where(scope_clause, func.coalesce(TeleCallLead.appointment_date, "") != "")
    )).scalars().all()
    created = 0
    for lead in leads:
        dt = parse_sheet_datetime(lead.appointment_date)
        if not dt:
            continue
        day = to_ist(dt).date()
        if not (first <= day <= last):
            continue
        start, end = from_ist(datetime.combine(day, time(0, 0))), from_ist(datetime.combine(day + timedelta(days=1), time(0, 0)))
        exists = (await db.execute(select(TeleAppointment.id).where(
            TeleAppointment.lead_id == lead.id, TeleAppointment.scheduled_at >= start, TeleAppointment.scheduled_at < end,
        ))).first()
        if exists:
            continue
        db.add(TeleAppointment(lead_id=lead.id, scheduled_at=dt, purpose=lead.service_type or lead.product or "Store visit",
                               attendance="scheduled", source="sheet", created_at=utcnow()))
        created += 1
    if created:
        await db.flush()
    return created


async def _apply_match(db: AsyncSession, appt: TeleAppointment, lead: TeleCallLead, row: dict,
                       now: datetime, alerts: list) -> None:
    amount = float(row.get("amount") or 0)
    appt.sale_match_status = "matched"
    appt.matched_purchase_id = str(row.get("id"))
    appt.matched_amount = amount
    appt.matched_shop = (row.get("shop") or "")[:150]
    appt.matched_sale_date = row.get("date") or None
    if appt.attendance in ("scheduled", "rescheduled", "no_show"):
        appt.attendance = "attended"

    old = lead.status or ""
    if old != "Sale Conversion":
        lead.status = "Sale Conversion"
        mark_edited(lead, "status")
    if not parse_amount(lead.sale_amount):
        lead.sale_amount = f"{amount:.0f}"
        mark_edited(lead, "sale_amount")
    lead.edited_by_user = True
    refresh_derived(lead)
    lead.is_urgent = False
    await close_open_followups(db, lead, status="done", user_id=None, outcome="sale_matched", now=now)
    await resolve_alerts_for_lead(db, lead.id, ["first_call_overdue", "first_call_escalated",
                                                "followup_overdue", "unassigned"], now)
    add_activity(db, lead, "system", old_value=old or "No Status", new_value="Sale Conversion",
                 notes=f"Sale matched from the sales report: bill #{row.get('id')} · {row.get('shop')} · "
                       f"₹{amount:,.0f} on {row.get('date')}",
                 meta={"source": "sale_match", "purchase_id": row.get("id")}, at=now)
    recipients = set(await team_leader_ids(db, lead.sheet_tl_name, lead.owner_user_id))
    if lead.owner_user_id:
        recipients.add(lead.owner_user_id)
    for rid in recipients:
        await create_alert(db, recipient_id=rid, kind="sale_matched", level=1, lead=lead,
                           title="Appointment converted to a sale",
                           body=f"{lead.full_name} bought at {row.get('shop')} for ₹{amount:,.0f} (bill #{row.get('id')}).",
                           dedupe_key=f"salematch:{appt.id}:{rid}", out=alerts)


async def run_sale_match(db: AsyncSession, *, scope_clause=None, today: date | None = None,
                         fetch: Fetcher | None = None) -> dict:
    now = utcnow()
    today = today or ist_today(now)
    fetch = fetch or mcp_sales_for_phone
    scope_clause = scope_clause if scope_clause is not None else TeleCallLead.id.isnot(None)
    first = today - timedelta(days=MATCH_WINDOW_DAYS + 1)
    automation = await get_automation(db)
    stats = {"checked": 0, "matched": 0, "no_sale": 0, "pending": 0, "no_phone": 0, "errors": 0,
             "sheet_appointments_added": await _materialise_sheet_appointments(db, scope_clause, first, today)}

    start_utc = from_ist(datetime.combine(first, time(0, 0)))
    end_utc = from_ist(datetime.combine(today + timedelta(days=1), time(0, 0)))
    rows = (await db.execute(
        select(TeleAppointment, TeleCallLead).join(TeleCallLead, TeleCallLead.id == TeleAppointment.lead_id)
        .where(scope_clause, TeleAppointment.scheduled_at >= start_utc, TeleAppointment.scheduled_at < end_utc,
               TeleAppointment.attendance != "cancelled",
               func.coalesce(TeleAppointment.sale_match_status, "pending").in_(["pending", "no_phone"]))
        .order_by(TeleAppointment.scheduled_at)
    )).all()
    used = set((await db.execute(
        select(TeleAppointment.matched_purchase_id).where(TeleAppointment.matched_purchase_id.isnot(None))
    )).scalars().all())
    alerts: list = []
    for appt, lead in rows:
        stats["checked"] += 1
        appt.sale_checked_at = now
        phone10 = norm_phone(lead.phone)
        if len(phone10) < 10:
            appt.sale_match_status = "no_phone"
            stats["no_phone"] += 1
            continue
        appt_day = to_ist(appt.scheduled_at).date()
        window_end = min(appt_day + timedelta(days=MATCH_WINDOW_DAYS), today)
        try:
            sales = await fetch(appt_day, window_end, phone10)
        except Exception as e:  # MCP down: leave pending, retry on the next run
            logger.warning("Sale check failed for appointment %s: %s", appt.id, e)
            appt.sale_match_status = "pending"
            stats["errors"] += 1
            continue
        match = next((r for r in sales if _is_new_sale(r) and str(r.get("id")) not in used), None)
        if match:
            used.add(str(match.get("id")))
            await _apply_match(db, appt, lead, match, now, alerts)
            stats["matched"] += 1
        elif appt_day + timedelta(days=MATCH_WINDOW_DAYS) < today:
            appt.sale_match_status = "no_sale"
            stats["no_sale"] += 1
            if lead.status != "Sale Conversion" and (lead.stage or "") not in ("converted", "not_interested"):
                create_followup(db, lead, kind="call",
                                due_at=add_working_minutes(now, 30, automation["working_hours"]),
                                owner_id=lead.owner_user_id, created_by=None,
                                reason="No sale found after the appointment — call the customer", at=now)
                add_activity(db, lead, "system", at=now,
                             notes=f"No sale found in the sales report within {MATCH_WINDOW_DAYS} days of the "
                                   f"appointment on {appt_day.isoformat()}")
                await recompute_next_follow_up(db, lead)
        else:
            appt.sale_match_status = "pending"
            stats["pending"] += 1
    await db.commit()
    await emit_alerts(alerts)
    return stats
