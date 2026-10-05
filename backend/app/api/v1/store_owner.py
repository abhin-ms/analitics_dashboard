"""Store Owner dashboard: sales (from MCP), leads and staff for the store(s)
the owner is linked to (Settings → Users → Assigned Stores). Read-only."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db, get_current_user
from ...models.models import (
    Role, Store, StoreStaff, TeleAppointment, TeleCallLead, User, UserStoreAccess,
)
from ...services.crm import metrics as crm_metrics
from ...services.crm.config import get_automation, get_targets
from ...services.crm.engine import parse_amount
from ...services.crm.timeutil import utcnow
from ...services.sales_report_service import get_sales_report

router = APIRouter(prefix="/store-owner", tags=["store-owner"])

OWNER_ROLES = {"Store Owner"}
# Staff whose lead work is measured (they own leads in the CRM).
LEAD_ROLES = {"Telecaller", "Salesperson"}
RECENT_LEADS = 100


async def _owner_store_ids(user: User, db: AsyncSession) -> list[int]:
    role = (await db.execute(select(Role.name).where(Role.id == user.role_id))).scalar_one_or_none()
    if role not in OWNER_ROLES:
        raise HTTPException(status_code=403, detail="Only store owners have a store owner dashboard")
    ids = {sa.store_id for sa in user.store_access}
    if user.store_id:
        ids.add(user.store_id)
    return sorted(ids)


def _same_name(a: Optional[str], b: Optional[str]) -> bool:
    return bool(a and b) and " ".join(a.lower().split()) == " ".join(b.lower().split())


@router.get("/overview")
async def store_owner_overview(
    start: Optional[date] = None,
    end: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    store_ids = await _owner_store_ids(user, db)
    today = date.today()
    end = end or today
    start = start or end.replace(day=1)
    if start > end:
        raise HTTPException(status_code=400, detail="start must be on or before end")

    stores = (await db.execute(
        select(Store, User.name).outerjoin(User, Store.team_leader_id == User.id)
        .where(Store.id.in_(store_ids or [-1])).order_by(Store.name)
    )).all()
    store_name = {s.id: s.name for s, _ in stores}
    base = {
        "stores": [{"id": s.id, "name": s.name, "country": s.country, "team_leader": tl or ""} for s, tl in stores],
        "period": {"start": start.isoformat(), "end": end.isoformat()},
    }
    if not store_ids:
        return {**base, "sales": None, "leads": None, "staff": [], "staff_records": []}

    # ── Sales: the same MCP-backed figures the admin dashboard uses ──
    granularity = "day" if (end - start).days <= 62 else "month"
    report = await get_sales_report(
        db, granularity=granularity, start=start.isoformat(), end=end.isoformat(),
        store_ids=store_ids, group_by="branch",
    )
    sales = {
        "total_revenue": report["total_revenue"],
        "total_target": report["total_target"],
        "achievement_pct": report["achievement_pct"],
        "units_sold": report.get("total_units_sold", 0),
        "walkins": report["total_walkins"],
        "conversions": report["total_conversions"],
        "granularity": granularity,
        "trend": report["trend"],
        "by_store": [
            {"store": g["key"], "country": g["country"], "revenue": g["revenue"], "target": g["target"],
             "achievement_pct": g["achievement_pct"], "units_sold": g["units_sold"],
             "walkins": g["walkins"], "conversions": g["conversions"]}
            for g in report["breakdown"]
        ],
        "needs_review": report["needs_review"],
    }

    # ── Leads: linked to these stores directly or through an appointment ──
    appt_lead_ids = select(TeleAppointment.lead_id).where(TeleAppointment.store_id.in_(store_ids))
    in_stores = or_(TeleCallLead.store_id.in_(store_ids), TeleCallLead.id.in_(appt_lead_ids))
    p_start, p_end = crm_metrics.period_bounds(start, end)
    leads = await crm_metrics.leads_in_period(db, in_stores, p_start, p_end)

    # A lead's store: its own, else the store of its latest appointment here.
    appt_store = {
        lid: sid for lid, sid in (await db.execute(
            select(TeleAppointment.lead_id, TeleAppointment.store_id)
            .where(TeleAppointment.store_id.in_(store_ids))
            .order_by(TeleAppointment.scheduled_at)
        )).all()
    }
    lead_store = {l.id: (l.store_id if l.store_id in store_name else appt_store.get(l.id)) for l in leads}

    owner_ids = {l.owner_user_id for l in leads if l.owner_user_id}
    owner_names = dict((await db.execute(select(User.id, User.name).where(User.id.in_(owner_ids or {-1})))).all())

    now = utcnow()
    upcoming = (await db.execute(
        select(func.count(TeleAppointment.id)).where(
            TeleAppointment.store_id.in_(store_ids), TeleAppointment.scheduled_at >= now,
            TeleAppointment.attendance == "scheduled",
        )
    )).scalar() or 0

    by_store_leads = []
    for sid in store_ids:
        k = crm_metrics.lead_kpis([l for l in leads if lead_store.get(l.id) == sid])
        by_store_leads.append({"store": store_name.get(sid, ""), **k})

    recent = sorted(leads, key=lambda l: (l.submitted_at or l.created_at), reverse=True)[:RECENT_LEADS]
    leads_out = {
        "kpis": crm_metrics.lead_kpis(leads),
        "status_counts": crm_metrics.status_counts(leads),
        "upcoming_appointments": upcoming,
        "by_store": by_store_leads,
        "recent": [
            {
                "id": l.id, "name": l.full_name, "phone": l.phone, "status": l.status or "",
                "stage": l.stage, "priority": l.priority, "appointment_date": l.appointment_date,
                "salesperson": l.salesperson, "handled_by": owner_names.get(l.owner_user_id) or l.person_calling or "",
                "store": store_name.get(lead_store.get(l.id), ""), "source": l.source_channel or l.lead_source or "",
                "sale_amount": parse_amount(l.sale_amount) if l.status == "Sale Conversion" else 0,
                "received_at": ((l.submitted_at or l.created_at).isoformat() + "Z") if (l.submitted_at or l.created_at) else None,
            }
            for l in recent
        ],
    }

    # ── Staff: everyone linked to these stores, plus their team leaders ──
    staff_rows = (await db.execute(
        select(User, Role.name).join(Role, Role.id == User.role_id)
        .outerjoin(UserStoreAccess, UserStoreAccess.user_id == User.id)
        .where(or_(User.store_id.in_(store_ids), UserStoreAccess.store_id.in_(store_ids)),
               Role.name.notin_(OWNER_ROLES))
    )).unique().all()
    tl_ids = {s.team_leader_id for s, _ in stores if s.team_leader_id}
    seen = {u.id for u, _ in staff_rows}
    for u, role in (await db.execute(
        select(User, Role.name).join(Role, Role.id == User.role_id).where(User.id.in_(tl_ids or {-1}))
    )).all():
        if u.id not in seen:
            staff_rows.append((u, role))

    access = {}
    for uid, sid in (await db.execute(
        select(UserStoreAccess.user_id, UserStoreAccess.store_id).where(UserStoreAccess.store_id.in_(store_ids))
    )).all():
        access.setdefault(uid, set()).add(sid)

    def staff_stores(u: User) -> list[str]:
        sids = set(access.get(u.id, set()))
        if u.store_id in store_name:
            sids.add(u.store_id)
        sids |= {s.id for s, _ in stores if s.team_leader_id == u.id}
        return sorted(store_name[s] for s in sids if s in store_name)

    agents = [{"id": u.id, "name": u.name, "role": role, "available": u.available_for_leads is not False}
              for u, role in staff_rows if role in LEAD_ROLES]
    report_rows = {
        r["user_id"]: r for r in await crm_metrics.agent_report(
            db, agents, start, end, now=now, automation=await get_automation(db), targets=await get_targets(db),
        )
    }
    staff = []
    for u, role in sorted(staff_rows, key=lambda x: (x[1] != "Team Leader", x[0].name.lower())):
        r = report_rows.get(u.id, {})
        sold = [l for l in leads if l.status == "Sale Conversion" and _same_name(l.salesperson, u.name)]
        staff.append({
            "user_id": u.id, "name": u.name, "email": u.email, "role": role,
            "is_active": bool(u.is_active), "stores": staff_stores(u),
            "measured": role in LEAD_ROLES,
            "total_leads": r.get("total_leads", 0), "converted": r.get("converted", 0),
            "conversion_pct": r.get("conversion_pct", 0.0), "connected_pct": r.get("connected_pct", 0.0),
            "appointments": r.get("appointments", 0), "no_status": r.get("no_status", 0),
            "first_call_pct": r.get("first_call_pct"), "followups_on_time_pct": r.get("followups_on_time_pct"),
            "calls_logged": r.get("calls_logged", 0),
            "sales_closed": len(sold), "sales_amount": sum(parse_amount(l.sale_amount) for l in sold),
        })

    # Monthly staffing record per store (headcount, accommodation, attrition risk…).
    month = end.strftime("%Y-%m")
    records = (await db.execute(
        select(StoreStaff).where(StoreStaff.store_id.in_(store_ids), StoreStaff.month <= month)
        .order_by(StoreStaff.month.desc())
    )).scalars().all()
    latest_record = {}
    for rec in records:
        latest_record.setdefault(rec.store_id, rec)
    staff_records = [
        {"store": store_name.get(sid, ""), "month": r.month, "manager_name": r.manager_name,
         "staff_count": r.staff_count, "total_headcount": r.total_headcount,
         "has_accommodation": r.has_accommodation, "resignation_risk": r.resignation_risk,
         "training_active": r.training_active, "notes": r.notes}
        for sid, r in latest_record.items()
    ]

    return {**base, "sales": sales, "leads": leads_out, "staff": staff, "staff_records": staff_records}
