"""Fix leads that arrived without an owner: merge Meta leads with their
Google Sheet copy, re-match Meta lead forms and the unassigned leads of the
last weeks with the current matching rules, and give them to the store's
team — or, when no store can be found, to the team leader of the area to
assign by hand. Always previewed first (apply=False writes nothing);
applying never touches a form an admin mapped by hand or a lead someone
already owns. Writes the database only, never the Google Sheets."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.models import MetaFormStore, MetaLead, Store, TeleCallLead, User
from .config import get_automation
from .engine import create_followup, transfer_ownership
from .intake import _real_team_leader, canonical_store, fallback_team_leader, match_store, pick_telecaller
from .meta_leads import candidate_names, merge_sheet_twin, route_unassigned_for_form, unmerged_sheet_twins
from .night_queue import not_waiting
from .status import CLOSED_STAGES
from .timeutil import add_working_minutes, utcnow

FIXABLE_SOURCES = ("website", "facebook", "instagram")


async def _waiting_form_leads(db: AsyncSession, form_id: str) -> int:
    return len((await db.execute(
        select(TeleCallLead.id).join(MetaLead, MetaLead.lead_id == TeleCallLead.id)
        .where(MetaLead.form_id == form_id, MetaLead.status == "created", TeleCallLead.owner_user_id.is_(None))
    )).all())


async def rematch_stores(db: AsyncSession, actor: User, *, apply: bool, days: int = 30) -> dict:
    now = utcnow()
    forms_out, leads_out, merged_out = [], [], []
    remapped_forms: set[str] = set()
    automation = await get_automation(db)

    async def team(store: Store) -> str:
        tl = await _real_team_leader(db, store)
        return tl.name if tl else ""

    # 0. the same Meta lead twice: the webhook lead and its sheet copy
    for keep, drop in await unmerged_sheet_twins(db):
        merged_out.append({"lead_id": keep.id, "copy_id": drop.id, "name": keep.full_name,
                           "sheet": drop.sheet_tl_name})
        if apply:
            await merge_sheet_twin(db, keep, drop, now=now, automation=automation, actor_id=actor.id)
    if apply:
        await db.flush()

    # 1. lead forms the webhook couldn't place (never the ones set by hand),
    #    and automatic matches that landed on a duplicate store with no team
    for f in (await db.execute(select(MetaFormStore))).scalars().all():
        if f.match_source == "manual":
            continue
        current = await db.get(Store, f.store_id) if f.store_id else None
        if current is None:
            new = None
            for cand in candidate_names(f.form_name):
                new = await match_store(db, cand, "")
                if new:
                    break
        else:
            new = await canonical_store(db, current)
        if not new or (current and new.id == current.id):
            continue
        forms_out.append({"form": f.form_name or f.form_id, "from": current.name if current else None,
                          "to": new.name, "team_leader": await team(new),
                          "waiting_leads": await _waiting_form_leads(db, f.form_id)})
        remapped_forms.add(f.form_id)
        if apply:
            f.store_id, f.match_source, f.updated_by, f.updated_at = new.id, "auto", actor.id, now
            await db.flush()
            await route_unassigned_for_form(db, f.form_id, actor)

    # 2. open website / Meta leads still without an owner: their store (found
    #    now, or already set), else the area's team leader to assign by hand
    form_of = dict((await db.execute(select(MetaLead.lead_id, MetaLead.form_id))).all())
    leads = (await db.execute(select(TeleCallLead).where(
        TeleCallLead.owner_user_id.is_(None), not_waiting(),  # night-queue leads get handed over in the morning
        TeleCallLead.source_channel.in_(FIXABLE_SOURCES),
        TeleCallLead.created_at >= now - timedelta(days=days),
    ))).scalars().all()
    for lead in leads:
        if form_of.get(lead.id) in remapped_forms or lead.stage in CLOSED_STAGES:
            continue  # handled with its form above / nothing left to do
        text = lead.preferred_store_text or ""
        store = await db.get(Store, lead.store_id) if lead.store_id else None
        if store is None:
            store = await match_store(db, text, "") if text else None
        if store is None and lead.source_channel in ("facebook", "instagram") and lead.remarks:
            store = await match_store(db, lead.remarks, "")  # the Meta form's city answer
        tl = await _real_team_leader(db, store) if store else None
        by_area = None
        if not tl:
            by_area = await fallback_team_leader(
                db, [store.name if store else None, text, lead.customer_state,
                     lead.remarks if lead.source_channel != "website" else None],
                lead.customer_country)
            if not by_area:
                continue
        leads_out.append({"lead_id": lead.id, "name": lead.full_name, "source": lead.source_channel,
                          "said": text or lead.remarks or "",
                          "to": store.name if tl else "Team leader to assign",
                          "team_leader": (tl or by_area).name})
        if apply:
            if tl:
                lead.store_id = store.id
                owner = await pick_telecaller(db, tl, store) or tl
                reason = f"Store matched: {store.name}"
            else:
                owner, reason = by_area, "Store not matched — team leader of the area to assign"
            await transfer_ownership(db, lead, owner.id, source="manual", actor_id=actor.id, now=now,
                                     automation=automation, reason=reason)
            if not lead.status:
                create_followup(db, lead, kind="first_call", owner_id=owner.id, at=now,
                                reason="Call the lead" if tl else "Assign the lead to a telecaller",
                                due_at=add_working_minutes(now, automation["first_call_minutes"],
                                                           automation["working_hours"]))
    if apply:
        await db.commit()
    return {"applied": apply, "merged": merged_out, "forms": forms_out, "leads": leads_out}
