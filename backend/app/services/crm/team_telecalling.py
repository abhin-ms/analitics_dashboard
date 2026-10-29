"""Telecalling performance of one team leader's team for a period: for each
telecaller (and the team leader, and leads still unassigned) the leads that
arrived, how many were attended (called or given a status) and not, calls
made, sales — overall and per lead source (Website, Facebook, Instagram…).

Uses the same definitions as the CEO report (ceo_report.py): a lead counts
in the period it arrived; "attended" = first contact made or a status set;
"calls" = distinct leads called or updated in the period (in the app or on
the Google Sheet — a sheet update counts for the lead's owner), so a
follow-up call on an older lead counts too."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.models import Role, Store, TeleCallLead, TeleLeadActivity, User, UserStoreAccess
from .metrics import lead_date_col

SOURCE_LABEL = {"website": "Website", "facebook": "Facebook", "instagram": "Instagram", "meta_sheet": "Google Sheet",
                "walk_in": "Walk-in", "whatsapp": "WhatsApp", "referral": "Referral", "phone": "Phone", "app": "App"}
SOURCE_ORDER = ["website", "facebook", "instagram", "meta_sheet"]


def _attended(l: TeleCallLead) -> bool:
    return bool(l.first_contact_at or (l.status or "").strip())


def _blank() -> dict:
    return {"leads": 0, "attended": 0, "calls": 0, "converted": 0, "by_source": {}}


def _finish(s: dict) -> dict:
    s["not_attended"] = s["leads"] - s["attended"]
    s["attended_pct"] = round(s["attended"] / s["leads"] * 100) if s["leads"] else None
    for b in s["by_source"].values():
        b["not_attended"] = b["leads"] - b["attended"]
    return s


async def team_telecalling(db: AsyncSession, tl: User, start: datetime, end: datetime) -> dict:
    """start / end: naive UTC, end exclusive."""
    store_ids = set((await db.execute(select(Store.id).where(Store.team_leader_id == tl.id))).scalars().all())
    stores = dict((await db.execute(select(Store.id, Store.name).where(Store.id.in_(store_ids or {-1})))).all())
    tc_role = (await db.execute(select(Role.id).where(Role.name == "Telecaller"))).scalar()
    covers = select(UserStoreAccess.user_id).where(UserStoreAccess.store_id.in_(store_ids or {-1}))
    team = (await db.execute(select(User).where(
        User.role_id == tc_role, User.is_active == True,  # noqa: E712
        or_(User.team_leader_id == tl.id, User.store_id.in_(store_ids or {-1}), User.id.in_(covers)),
    ).order_by(User.name))).scalars().all()
    people = {u.id: u for u in team}
    people[tl.id] = tl

    leads = (await db.execute(select(TeleCallLead).where(
        lead_date_col() >= start, lead_date_col() < end,
        or_(TeleCallLead.owner_user_id.in_(set(people)),
            TeleCallLead.owner_user_id.is_(None) & TeleCallLead.store_id.in_(store_ids or {-1})),
    ))).scalars().all()

    rows: dict = {uid: _blank() for uid in people}
    rows[None] = _blank()  # unassigned leads of the team's stores
    total = _blank()
    sources: set[str] = set()
    for l in leads:
        src = l.source_channel or "other"
        sources.add(src)
        att = _attended(l)
        for s in (rows[l.owner_user_id], total):
            s["leads"] += 1
            s["attended"] += att
            s["converted"] += l.stage == "converted"
            b = s["by_source"].setdefault(src, {"leads": 0, "attended": 0, "calls": 0})
            b["leads"] += 1
            b["attended"] += att

    # calls in the period: each lead once per person, split by the lead's source
    worker = func.coalesce(TeleLeadActivity.user_id, TeleCallLead.owner_user_id)
    for uid, src, n in (await db.execute(
        select(worker, TeleCallLead.source_channel, func.count(func.distinct(TeleLeadActivity.lead_id)))
        .join(TeleCallLead, TeleCallLead.id == TeleLeadActivity.lead_id)
        .where(TeleLeadActivity.type.in_(("call", "status_change")), worker.in_(set(people)),
               TeleLeadActivity.created_at >= start, TeleLeadActivity.created_at < end)
        .group_by(worker, TeleCallLead.source_channel))).all():
        src = src or "other"
        sources.add(src)
        for s in (rows[uid], total):
            s["calls"] += n
            s["by_source"].setdefault(src, {"leads": 0, "attended": 0, "calls": 0})["calls"] += n

    def person(uid) -> dict:
        u = people.get(uid)
        is_tl = uid == tl.id
        store = stores.get(u.store_id) if u and u.store_id in stores else None
        return {"user_id": uid, "name": u.name if u else "Unassigned",
                "role": "Team leader" if is_tl else ("Telecaller" if u else "Unassigned"),
                "store": store or ("—" if u and not is_tl else None),
                "available": (u.available_for_leads is not False) if u and not is_tl else None,
                **_finish(rows[uid])}

    out = [person(u.id) for u in team]
    out.sort(key=lambda r: (r["attended_pct"] is None, -(r["attended_pct"] or 0), -r["calls"], r["name"].lower()))
    for uid in (tl.id, None):  # the team leader's own leads and unassigned ones, only when there are any
        if rows[uid]["leads"] or rows[uid]["calls"]:
            out.append(person(uid))
    order = [s for s in SOURCE_ORDER if s in sources] + sorted(sources - set(SOURCE_ORDER))
    return {
        "team_leader": {"id": tl.id, "name": tl.name},
        "stores": sorted(stores.values()),
        "sources": [{"key": s, "label": SOURCE_LABEL.get(s, s.replace("_", " ").title())} for s in order],
        "telecallers": out,
        "total": _finish(total),
    }
