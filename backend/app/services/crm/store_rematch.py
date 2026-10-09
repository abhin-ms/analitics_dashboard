"""Fix leads that arrived without a store: re-match Meta lead forms and the
unassigned leads of the last weeks with the current matching rules, and
give them to the store's team. Always previewed first (apply=False writes
nothing); applying never touches a form an admin mapped by hand or a lead
someone already owns."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.models import MetaFormStore, MetaLead, Store, TeleCallLead, User
from .config import get_automation
from .engine import create_followup, transfer_ownership
from .intake import _real_team_leader, canonical_store, match_store, pick_telecaller
from .meta_leads import candidate_names, route_unassigned_for_form
from .timeutil import add_working_minutes, utcnow

FIXABLE_SOURCES = ("website", "facebook", "instagram")


async def _waiting_form_leads(db: AsyncSession, form_id: str) -> int:
    return len((await db.execute(
        select(TeleCallLead.id).join(MetaLead, MetaLead.lead_id == TeleCallLead.id)
        .where(MetaLead.form_id == form_id, MetaLead.status == "created", TeleCallLead.owner_user_id.is_(None))
    )).all())


async def rematch_stores(db: AsyncSession, actor: User, *, apply: bool, days: int = 30) -> dict:
    now = utcnow()
    forms_out, leads_out = [], []
    remapped_forms: set[str] = set()

    async def team(store: Store) -> str:
        tl = await _real_team_leader(db, store)
        return tl.name if tl else ""

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

    # 2. unassigned website / Meta leads with a store text we can now read
    form_of = dict((await db.execute(select(MetaLead.lead_id, MetaLead.form_id))).all())
    automation = await get_automation(db)
    leads = (await db.execute(select(TeleCallLead).where(
        TeleCallLead.store_id.is_(None), TeleCallLead.owner_user_id.is_(None),
        TeleCallLead.source_channel.in_(FIXABLE_SOURCES),
        TeleCallLead.created_at >= now - timedelta(days=days),
    ))).scalars().all()
    for lead in leads:
        if form_of.get(lead.id) in remapped_forms:
            continue  # handled with its form above
        text = lead.preferred_store_text or ""
        store = await match_store(db, text, "") if text else None
        if store is None and lead.source_channel in ("facebook", "instagram") and lead.remarks:
            store = await match_store(db, lead.remarks, "")  # the Meta form's city answer
        tl = await _real_team_leader(db, store) if store else None
        if not tl:
            continue
        leads_out.append({"lead_id": lead.id, "name": lead.full_name, "source": lead.source_channel,
                          "said": text or lead.remarks or "", "to": store.name, "team_leader": tl.name})
        if apply:
            lead.store_id = store.id
            owner = await pick_telecaller(db, tl) or tl
            await transfer_ownership(db, lead, owner.id, source="manual", actor_id=actor.id, now=now,
                                     automation=automation, reason=f"Store matched: {store.name}")
            if not lead.status:
                create_followup(db, lead, kind="first_call", owner_id=owner.id, at=now,
                                reason="Call the lead (store matched)",
                                due_at=add_working_minutes(now, automation["first_call_minutes"],
                                                           automation["working_hours"]))
    if apply:
        await db.commit()
    return {"applied": apply, "forms": forms_out, "leads": leads_out}
