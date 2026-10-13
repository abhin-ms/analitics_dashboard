"""Check the bill number noted on a lead against the MCP bills.

MCP sends no customer on a bill, so a sale can't be matched to a lead by
phone. Instead the telecaller or store notes the bill number on the lead
(the TL sheet's "Bill No" column, or the CRM) and this confirms it:

    verified   the bill is a New Sale with an amount — the lead becomes a
               Sale Conversion at the bill's shop, for the bill's amount,
               on the bill's date
    not_found  no such bill in the sales report (yet): rechecked every run
    duplicate  the bill is already verified on another lead
    check      a bill, but not one that fits: a Replacement / zero amount,
               dated before the lead arrived, or not a number at all

When the bill itself carries the customer's mobile (the Sales Report API's
mobile_number, which stores rarely fill today) none of that typing is
needed: match_bills_by_mobile finds the lead with that phone and does the
same thing automatically.

Reads only the mcp_bills table (filled by the MCP sync), never MCP itself.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.models import McpBill, TeleAppointment, TeleCallLead
from .engine import emit_alerts
from .sale_match import _apply_match
from .timeutil import from_ist, to_ist, utcnow

logger = logging.getLogger(__name__)

VERIFIED, NOT_FOUND, DUPLICATE, CHECK = "verified", "not_found", "duplicate", "check"
# A bill is matched to a lead that arrived up to this long before it.
MATCH_LOOKBACK_DAYS = 120


def parse_bill_no(text: str | None) -> int | None:
    """'#117180', 'Bill 117180', '117180.0' → 117180; nothing numeric → None."""
    m = re.search(r"\d{3,}", (text or "").replace(",", ""))
    return int(m.group(0)) if m else None


def _note(bill: McpBill) -> str:
    return f"#{bill.id} · {bill.shop} · ₹{float(bill.amount or 0):,.0f} · {bill.date.isoformat()}"[:200]


async def verify_lead_bill(db: AsyncSession, lead: TeleCallLead, *, now: datetime | None = None,
                           alerts: list | None = None) -> str | None:
    """Check one lead's bill number and act on it; returns the new status."""
    now = now or utcnow()
    alerts = alerts if alerts is not None else []
    lead.bill_checked_at = now
    if not (lead.bill_no or "").strip():
        lead.bill_status = lead.bill_note = None
        return None
    number = parse_bill_no(lead.bill_no)
    if number is None:
        lead.bill_status, lead.bill_note = CHECK, "That isn't a bill number"
        return CHECK

    other = (await db.execute(
        select(TeleCallLead.full_name).join(TeleAppointment, TeleAppointment.lead_id == TeleCallLead.id)
        .where(TeleAppointment.matched_purchase_id == str(number), TeleCallLead.id != lead.id).limit(1)
    )).scalar()
    if other is not None:
        lead.bill_status, lead.bill_note = DUPLICATE, f"Bill #{number} is already on another lead ({other})"[:200]
        return DUPLICATE

    bill = (await db.execute(select(McpBill).where(McpBill.id == number))).scalar_one_or_none()
    if bill is None:
        lead.bill_status, lead.bill_note = NOT_FOUND, f"Bill #{number} isn't in the sales report yet"
        return NOT_FOUND
    if "new sale" not in (bill.category or "").lower() or float(bill.amount or 0) <= 0:
        lead.bill_status = CHECK
        lead.bill_note = f"Bill #{number} is a {bill.category or 'zero-amount bill'}, not a new sale"[:200]
        return CHECK
    arrived = to_ist(lead.submitted_at or lead.created_at).date() if (lead.submitted_at or lead.created_at) else None
    if arrived and bill.date < arrived:
        lead.bill_status = CHECK
        lead.bill_note = f"Bill #{number} is dated {bill.date.isoformat()}, before this lead arrived ({arrived.isoformat()})"
        return CHECK

    # A real new sale: record the store visit it stands for, then convert the lead.
    visit = (await db.execute(select(TeleAppointment).where(
        TeleAppointment.lead_id == lead.id, TeleAppointment.matched_purchase_id == str(number)))).scalar_one_or_none()
    if visit is None:
        sold_at = from_ist(datetime.combine(bill.date, time(12, 0)))
        visit = TeleAppointment(lead_id=lead.id, scheduled_at=sold_at, purpose="Store visit (bill verified)",
                                attendance="attended", source="bill", created_at=now)
        db.add(visit)
        await db.flush()
        await _apply_match(db, visit, lead,
                           {"id": bill.id, "amount": float(bill.amount or 0), "shop": bill.shop, "date": bill.date.isoformat()},
                           now, alerts, sold_at=sold_at, exact_amount=True)
    lead.bill_status, lead.bill_note = VERIFIED, _note(bill)
    return VERIFIED


async def verify_bills(db: AsyncSession) -> dict:
    """Check every lead whose bill number isn't verified yet (new numbers,
    and ones waiting for their bill to reach the sales report)."""
    leads = (await db.execute(select(TeleCallLead).where(
        func.coalesce(TeleCallLead.bill_no, "") != "",
        func.coalesce(TeleCallLead.bill_status, "") != VERIFIED,
    ))).scalars().all()
    # a verified lead whose number was changed afterwards is checked again
    changed = (await db.execute(select(TeleCallLead).where(
        TeleCallLead.bill_status == VERIFIED, func.coalesce(TeleCallLead.bill_no, "") != ""))).scalars().all()
    leads += [l for l in changed if not (l.bill_note or "").startswith(f"#{parse_bill_no(l.bill_no)} ")]
    stats = {VERIFIED: 0, NOT_FOUND: 0, DUPLICATE: 0, CHECK: 0}
    alerts: list = []
    now = utcnow()
    for lead in leads:
        status = await verify_lead_bill(db, lead, now=now, alerts=alerts)
        if status:
            stats[status] += 1
    await db.commit()
    await emit_alerts(alerts)
    return stats


def _phone10(text: str | None) -> str:
    digits = re.sub(r"\D", "", text or "")
    return digits[-10:] if len(digits) >= 10 else ""


async def match_bills_by_mobile(db: AsyncSession, *, commit: bool = True) -> dict:
    """New-sale bills that carry a customer mobile → the lead with that
    phone. The lead must have arrived on or before the bill's date (within
    MATCH_LOOKBACK_DAYS) and not be tied to a bill already; when the same
    person is on several leads, the latest one before the sale gets it."""
    used = set((await db.execute(
        select(TeleAppointment.matched_purchase_id).where(TeleAppointment.matched_purchase_id.isnot(None))
    )).scalars().all())
    bills = [b for b in (await db.execute(
        select(McpBill).where(McpBill.mobile10.isnot(None), McpBill.amount > 0).order_by(McpBill.date, McpBill.id)
    )).scalars().all() if str(b.id) not in used and "new sale" in (b.category or "").lower()]
    stats = {"bills_with_mobile": len(bills), "matched": 0}
    if not bills:
        return stats

    wanted = {b.mobile10 for b in bills}
    by_phone: dict[str, list[TeleCallLead]] = defaultdict(list)
    for lead in (await db.execute(select(TeleCallLead))).scalars().all():
        key = _phone10(lead.phone)
        if key in wanted:
            by_phone[key].append(lead)
    taken = set((await db.execute(
        select(TeleAppointment.lead_id).where(TeleAppointment.matched_purchase_id.isnot(None))
    )).scalars().all())
    now = utcnow()
    alerts: list = []
    for bill in bills:
        fits = []
        for lead in by_phone.get(bill.mobile10, []):
            at = lead.submitted_at or lead.created_at
            if lead.id in taken or at is None:
                continue
            arrived = to_ist(at).date()
            if arrived <= bill.date <= arrived + timedelta(days=MATCH_LOOKBACK_DAYS):
                fits.append((arrived, lead.id, lead))
        if not fits:
            continue
        lead = max(fits)[2]
        sold_at = from_ist(datetime.combine(bill.date, time(12, 0)))
        visit = TeleAppointment(lead_id=lead.id, scheduled_at=sold_at, purpose="Store visit (matched by mobile)",
                                attendance="attended", source="phone", created_at=now)
        db.add(visit)
        await db.flush()
        await _apply_match(db, visit, lead,
                           {"id": bill.id, "amount": float(bill.amount or 0), "shop": bill.shop, "date": bill.date.isoformat()},
                           now, alerts, sold_at=sold_at, exact_amount=True)
        lead.bill_no, lead.bill_status, lead.bill_checked_at = str(bill.id), VERIFIED, now
        lead.bill_note = (_note(bill) + " · matched by mobile")[:200]
        taken.add(lead.id)
        stats["matched"] += 1
    if commit:  # False: a dry run the caller rolls back
        await db.commit()
        await emit_alerts(alerts)
    return stats


async def run_bill_matching(db: AsyncSession) -> dict:
    """Both ways a sale reaches its lead: the customer mobile on the bill
    (automatic), then bill numbers typed on leads."""
    by_mobile = await match_bills_by_mobile(db)
    return {"by_mobile": by_mobile, "by_bill_no": await verify_bills(db)}
