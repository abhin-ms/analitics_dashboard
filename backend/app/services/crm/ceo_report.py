"""Twice-daily lead report for the CEO (1 PM and 8 PM IST): how many leads
came in since 8 PM the evening before, how many were attended (a call
logged) and how many not, per team leader / telecaller, as a PDF.

Sent by email when SMTP is configured (SMTP_* settings) and there are
report emails, and by WhatsApp (template C1, "lead_report" unless renamed
in Settings → WhatsApp → Templates) when the Cloud API is active and CEO
numbers exist (Settings → WhatsApp → Numbers) — both when both are set. The CEO gets no per-lead escalation alerts; those
stop at the team leader.

The WhatsApp template must be approved by Meta first: a DOCUMENT header
and a body with the named variables {{period}}, {{received}},
{{attended}} and {{not_attended}} (see template_fit)."""
from __future__ import annotations

import asyncio
import logging
import smtplib
from datetime import datetime, time, timedelta
from email.message import EmailMessage

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...models.models import Role, Store, TeleCallLead, TeleLeadActivity, User, WhatsAppContact
from .config import _get_json, _set_json
from .engine import user_names
from .timeutil import from_ist, to_ist, utcnow

logger = logging.getLogger(__name__)

REPORT_KEY = "crm.ceo_report"
LAST_KEY = "crm.ceo_report.last"
DEFAULT_REPORT = {"enabled": True, "emails": [], "whatsapp": True}
TEMPLATE_KEY = "C1"  # services/whatsapp/templates.py — its name can be changed in Settings → WhatsApp
DAY_STARTS_AT = time(20, 0)  # a "lead day" runs from 8 PM the evening before
REPORT_GRACE_MINUTES = 30  # the scheduler's misfire grace for the 8 PM run
SOURCES = {"website": "Website", "facebook": "Facebook", "instagram": "Instagram", "meta_sheet": "Meta (sheet)"}


async def get_report_settings(db: AsyncSession) -> dict:
    return {**DEFAULT_REPORT, **(await _get_json(db, REPORT_KEY) or {})}


async def save_report_settings(db: AsyncSession, value: dict, user_id: int | None) -> dict:
    merged = {**await get_report_settings(db), **{k: v for k, v in (value or {}).items() if k in DEFAULT_REPORT}}
    merged["emails"] = sorted({e.strip() for e in merged["emails"] if e and "@" in e})
    await _set_json(db, REPORT_KEY, merged, user_id)
    return merged


def report_window(now: datetime) -> tuple[datetime, datetime]:
    """(start, end) as naive UTC: 8 PM IST the evening before → now. The
    8 PM report itself (sent up to 30 min late) still covers the day that
    is ending, not the few seconds of the new one."""
    ist = to_ist(now) - timedelta(minutes=REPORT_GRACE_MINUTES)
    start_day = ist.date() if ist.time() >= DAY_STARTS_AT else ist.date() - timedelta(days=1)
    return from_ist(datetime.combine(start_day, DAY_STARTS_AT)), now


def _attended(l: TeleCallLead) -> bool:
    return bool(l.first_contact_at or (l.status or "").strip())


async def build_report(db: AsyncSession, now: datetime | None = None) -> dict:
    now = now or utcnow()
    start, end = report_window(now)
    leads = (await db.execute(select(TeleCallLead).where(
        TeleCallLead.created_at >= start, TeleCallLead.created_at < end))).scalars().all()
    people = {l.owner_user_id or l.queued_owner_id for l in leads} - {None}
    users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_(people or [-1])))).scalars().all()}
    tl_role = (await db.execute(select(Role.id).where(Role.name == "Team Leader"))).scalar()
    stores = {s.id: s for s in (await db.execute(select(Store))).scalars().all()}
    names = await user_names(db, {u.team_leader_id for u in users.values()}
                             | {s.team_leader_id for s in stores.values()} | set(users))

    def team_leader(l: TeleCallLead) -> str:
        u = users.get(l.owner_user_id or l.queued_owner_id)
        if u and u.role_id == tl_role:
            return u.name
        if u and u.team_leader_id:
            return names.get(u.team_leader_id, "—")
        st = stores.get(l.store_id)
        return names.get(st.team_leader_id, "—") if st else "—"

    def row() -> dict:
        return {"received": 0, "attended": 0, "not_attended": 0, "escalated": 0}

    total, by_tl, by_agent, by_source, pending = row(), {}, {}, {}, []
    waiting = unassigned = converted = 0
    first_call_minutes = []
    for l in leads:
        att = _attended(l)
        esc = bool(l.escalated_at)
        agent = names.get(l.owner_user_id) or (f"{names.get(l.queued_owner_id)} (queued)" if l.queued_owner_id else "Unassigned")
        for bucket in (total, by_tl.setdefault(team_leader(l), row()), by_agent.setdefault(agent, row()),
                       by_source.setdefault(SOURCES.get(l.source_channel or "", "Other"), row())):
            bucket["received"] += 1
            bucket["attended" if att else "not_attended"] += 1
            bucket["escalated"] += esc
        if l.queued_at and not l.queue_released_at and not l.owner_user_id:
            waiting += 1
        elif not l.owner_user_id:
            unassigned += 1
        converted += l.stage == "converted"
        if l.first_contact_at:
            began = l.queue_released_at or l.created_at
            if began and l.first_contact_at >= began:
                first_call_minutes.append((l.first_contact_at - began).total_seconds() / 60)
        if not att:
            st = stores.get(l.store_id)
            pending.append({"name": l.full_name or "—", "store": st.name if st else (l.preferred_store_text or l.sheet_tl_name or "—"),
                            "source": SOURCES.get(l.source_channel or "", "Other"), "owner": agent,
                            "received": to_ist(l.created_at).strftime("%d %b %H:%M"), "escalated": esc})

    def ordered(d: dict) -> list[dict]:
        return [{"name": k, **v} for k, v in sorted(d.items(), key=lambda kv: (-kv[1]["received"], kv[0]))]

    s_ist, e_ist = to_ist(start), to_ist(end)
    performance = await _performance(db, leads, start, end)
    return {
        "title": f"Lead report — {e_ist.strftime('%a %d %b %Y, %I:%M %p')}",
        "period": f"{s_ist.strftime('%d %b %I:%M %p')} – {e_ist.strftime('%d %b %I:%M %p')}",
        "generated_at": e_ist.strftime("%d %b %Y %I:%M %p"),
        "total": total, "waiting_in_queue": waiting, "unassigned": unassigned, "converted": converted,
        "attended_pct": round(total["attended"] / total["received"] * 100) if total["received"] else 0,
        "avg_first_call_minutes": round(sum(first_call_minutes) / len(first_call_minutes)) if first_call_minutes else None,
        "by_team_leader": ordered(by_tl), "by_telecaller": ordered(by_agent), "by_source": ordered(by_source),
        "not_attended": sorted(pending, key=lambda p: p["received"])[:40],
        "not_attended_more": max(0, len(pending) - 40),
        **performance,
    }


async def _performance(db: AsyncSession, leads: list[TeleCallLead], start: datetime, end: datetime) -> dict:
    """Who is doing well and who isn't: each telecaller's leads, attended %,
    calls (leads they called or updated in the window — in the app or on the
    Google Sheet, follow-ups of older leads too, each lead once), average
    minutes to the first call and sales; each team leader's whole team.
    Ranked by % attended, then calls."""
    # most telecallers work on the sheet: its status updates arrive with no
    # user, so they count for the lead's owner
    worker = func.coalesce(TeleLeadActivity.user_id, TeleCallLead.owner_user_id)
    calls = dict((await db.execute(
        select(worker, func.count(func.distinct(TeleLeadActivity.lead_id)))
        .join(TeleCallLead, TeleCallLead.id == TeleLeadActivity.lead_id)
        .where(TeleLeadActivity.type.in_(("call", "status_change")), worker.is_not(None),
               TeleLeadActivity.created_at >= start, TeleLeadActivity.created_at < end)
        .group_by(worker))).all())
    roles = dict((await db.execute(select(Role.name, Role.id).where(Role.name.in_(("Telecaller", "Team Leader"))))).all())
    tc_role, tl_role = roles.get("Telecaller"), roles.get("Team Leader")
    owners = {l.owner_user_id for l in leads} - {None}
    people = {u.id: u for u in (await db.execute(select(User).where(
        User.role_id.in_([r for r in (tc_role, tl_role) if r]),
        User.id.in_(owners | set(calls) or [-1])))).scalars().all()}
    tl_ids = {u.id for u in people.values() if u.role_id == tl_role} | {
        u.team_leader_id for u in people.values() if u.role_id == tc_role and u.team_leader_id}
    tl_names = await user_names(db, tl_ids)

    def stats() -> dict:
        return {"leads": 0, "attended": 0, "calls": 0, "converted": 0, "first_call": []}

    agents = {uid: stats() for uid, u in people.items() if u.role_id == tc_role}
    teams = {tid: stats() for tid in tl_ids}

    def team_of(uid: int):
        u = people.get(uid)
        if u is None:
            return None
        return u.id if u.role_id == tl_role else u.team_leader_id

    for l in leads:
        if l.owner_user_id not in people:
            continue  # unassigned / still in the night queue: nobody's to rank
        began = l.queue_released_at or l.created_at
        for s in (agents.get(l.owner_user_id), teams.get(team_of(l.owner_user_id))):
            if s is None:
                continue
            s["leads"] += 1
            s["attended"] += _attended(l)
            s["converted"] += l.stage == "converted"
            if l.first_contact_at and began and l.first_contact_at >= began:
                s["first_call"].append((l.first_contact_at - began).total_seconds() / 60)
    for uid, n in calls.items():
        for s in (agents.get(uid), teams.get(team_of(uid))):
            if s is not None:
                s["calls"] += n

    def done(name: str, s: dict, **extra) -> dict:
        fc = s.pop("first_call")
        return {"name": name, **s, **extra, "missed": s["leads"] - s["attended"],
                "attended_pct": round(s["attended"] / s["leads"] * 100) if s["leads"] else None,
                "avg_first_call": round(sum(fc) / len(fc)) if fc else None}

    def rank(rows: list[dict]) -> list[dict]:
        # % attended first (people with no leads after), then calls made
        return sorted(rows, key=lambda r: (r["attended_pct"] is None, -(r["attended_pct"] or 0), -r["calls"], r["name"]))

    telecallers = rank([done(people[uid].name, s, team_leader=tl_names.get(people[uid].team_leader_id, "-"))
                        for uid, s in agents.items() if s["leads"] or s["calls"]])
    team_leaders = rank([done(tl_names.get(tid, "-"), s) for tid, s in teams.items() if s["leads"] or s["calls"]])
    return {"telecallers": telecallers, "team_leaders": team_leaders,
            "calls_made": sum(s["calls"] for s in telecallers)}


# ── PDF ────────────────────────────────────────────────────────────
def _t(text) -> str:
    """The PDF core font is Latin-1: anything else becomes '?'."""
    return str(text).replace("—", "-").replace("–", "-").replace("→", "->").encode("latin-1", "replace").decode("latin-1")


GREEN, RED, BLUE, AMBER = (16, 185, 129), (239, 68, 68), (37, 99, 235), (245, 158, 11)
INK, MUTED, LINE, HEAD = (15, 23, 42), (100, 116, 139), (226, 232, 240), (241, 245, 249)
LIGHT_GREEN, LIGHT_RED = (236, 253, 245), (254, 242, 242)


def _pct(row: dict) -> str:
    return "-" if row["attended_pct"] is None else f"{row['attended_pct']}%"


def _highlights(r: dict) -> list[tuple[str, str, str, bool]]:
    """(label, name, line, good) cards: best and worst, only when there are
    at least two to compare."""
    cards = []
    ranked = [t for t in r["telecallers"] if t["attended_pct"] is not None]
    if len(ranked) >= 2:
        b, w = ranked[0], ranked[-1]
        cards += [("BEST TELECALLER", b["name"], f"{_pct(b)} attended, {b['calls']} calls", True),
                  ("NEEDS ATTENTION", w["name"], f"{_pct(w)} attended, {w['missed']} missed", False)]
    teams = [t for t in r["team_leaders"] if t["attended_pct"] is not None]
    if len(teams) >= 2:
        b, w = teams[0], teams[-1]
        cards += [("BEST TEAM LEADER", b["name"], f"team attended {_pct(b)} of {b['leads']} leads", True),
                  ("WEAKEST TEAM LEADER", w["name"], f"team attended {_pct(w)} of {w['leads']} leads", False)]
    if len(r["telecallers"]) >= 2:
        by_calls = sorted(r["telecallers"], key=lambda t: (-t["calls"], t["name"]))
        most, least = by_calls[0], by_calls[-1]
        cards += [("MOST CALLS", most["name"], f"{most['calls']} calls", True),
                  ("FEWEST CALLS", least["name"], f"only {least['calls']} calls", False)]
    return cards


def render_pdf(r: dict) -> bytes:
    """Page 1: who is doing well and who isn't (cards, team leader ranking,
    calls per telecaller). Then the full telecaller leaderboard and the
    leads still waiting for a call."""
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    w, left = pdf.w - pdf.l_margin - pdf.r_margin, pdf.l_margin
    nl = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}

    def page(sub: str):
        pdf.add_page()
        pdf.set_fill_color(*INK)
        pdf.rect(0, 0, pdf.w, 26, "F")
        pdf.set_text_color(255, 255, 255)
        pdf.set_xy(left, 6)
        pdf.set_font("Helvetica", "B", 15)
        pdf.cell(w, 8, _t("BreakProtection - " + r["title"]), **nl)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(w, 6, _t(f"Leads received {r['period']}   |   {sub}"), **nl)
        pdf.set_text_color(*INK)
        pdf.set_y(32)

    def room(h: float, sub: str):
        if pdf.get_y() + h > pdf.h - 16:
            page(sub)

    def heading(text: str, note: str = ""):
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*INK)
        pdf.cell(pdf.get_string_width(text) + 3, 8, _t(text))
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(0, 8, _t(note), **nl)
        pdf.set_text_color(*INK)

    def bar(x: float, y: float, width: float, h: float, value: float, top: float, color):
        pdf.set_fill_color(*LINE)
        pdf.rect(x, y, width, h, "F")
        if top and value:
            pdf.set_fill_color(*color)
            pdf.rect(x, y, width * min(value, top) / top, h, "F")

    # ── page 1: at a glance ──
    sub = "who is doing well, who is not"
    page(sub)
    t = r["total"]
    tiles = [("Leads received", t["received"], BLUE), ("Attended", f"{r['attended_pct']}%", GREEN),
             ("Not attended", t["not_attended"], RED), ("Calls made", r["calls_made"], AMBER)]
    tw, y = (w - 12) / 4, pdf.get_y()
    for i, (label, value, color) in enumerate(tiles):
        x = left + i * (tw + 4)
        pdf.set_fill_color(*color)
        pdf.rect(x, y, tw, 20, "F")
        pdf.set_text_color(255, 255, 255)
        pdf.set_xy(x, y + 2)
        pdf.set_font("Helvetica", "B", 19)
        pdf.cell(tw, 10, str(value), align="C")
        pdf.set_xy(x, y + 12)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(tw, 5, label, align="C")
    pdf.set_xy(left, y + 22)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    avg = f"{r['avg_first_call_minutes']} min" if r["avg_first_call_minutes"] is not None else "-"
    sources = ", ".join(f"{s['name']} {s['received']}" for s in r["by_source"]) or "-"
    pdf.multi_cell(w, 4.5, _t(f"Escalated to TL: {t['escalated']}   |   Avg time to first call: {avg}   |   "
                              f"Sales: {r['converted']}   |   Night queue: {r['waiting_in_queue']}   |   "
                              f"Unassigned: {r['unassigned']}\nSources: {sources}"), **nl)
    pdf.ln(3)

    cards = _highlights(r)
    cw, ch, y = (w - 4) / 2, 19, pdf.get_y()
    for i, (label, name, line, good) in enumerate(cards):
        x, yy = left + (i % 2) * (cw + 4), y + (i // 2) * (ch + 3)
        pdf.set_fill_color(*(LIGHT_GREEN if good else LIGHT_RED))
        pdf.rect(x, yy, cw, ch, "F")
        pdf.set_fill_color(*(GREEN if good else RED))
        pdf.rect(x, yy, 2, ch, "F")
        pdf.set_xy(x + 5, yy + 2)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*(GREEN if good else RED))
        pdf.cell(cw - 6, 4, ("+ " if good else "! ") + label)
        pdf.set_xy(x + 5, yy + 6.5)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(*INK)
        pdf.cell(cw - 6, 6, _t(name)[:34])
        pdf.set_xy(x + 5, yy + 12.5)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(cw - 6, 5, _t(line))
    pdf.set_y(y + ((len(cards) + 1) // 2) * (ch + 3) + 3)

    teams = r["team_leaders"]
    room(20, sub)
    heading("Team leader ranking", "   by % of their team's leads attended")
    if not teams:
        pdf.cell(w, 7, "No leads given to a team yet.", **nl)
    for i, tl in enumerate(teams):
        room(7, sub)
        yy = pdf.get_y()
        color = GREEN if i == 0 and len(teams) > 1 else RED if i == len(teams) - 1 and len(teams) > 1 else BLUE
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*color)
        pdf.cell(9, 7, f"#{i + 1}")
        pdf.set_text_color(*INK)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(34, 7, _t(tl["name"])[:22])
        bar(left + 43, yy + 1.5, w - 43 - 64, 4.5, tl["attended_pct"] or 0, 100, color)
        pdf.set_xy(left + w - 62, yy)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(14, 7, _pct(tl), align="R")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(48, 7, f"{tl['attended']}/{tl['leads']} leads, {tl['calls']} calls", align="R", **nl)
    pdf.ln(4)

    by_calls = sorted(r["telecallers"], key=lambda x: (-x["calls"], x["name"]))
    room(20, sub)
    heading("Calls made", "   leads called or updated (app or sheet) - green = top 3, red = bottom 3")
    if not by_calls:
        pdf.cell(w, 7, "No calls logged yet.", **nl)
    top = by_calls[0]["calls"] if by_calls else 0
    many = len(by_calls) > 6
    for i, tc in enumerate(by_calls):
        room(6, sub)
        yy = pdf.get_y()
        color = GREEN if many and i < 3 else RED if many and i >= len(by_calls) - 3 else BLUE
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(*INK)
        pdf.cell(42, 6, _t(tc["name"])[:26])
        bar(left + 42, yy + 1.2, w - 42 - 16, 3.6, tc["calls"], top, color)
        pdf.set_xy(left + w - 14, yy)
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(*color)
        pdf.cell(14, 6, str(tc["calls"]), align="R", **nl)

    # ── page 2: leaderboard + who still needs a call ──
    sub = "telecaller leaderboard"
    page(sub)
    heading("All telecallers, best to worst", "   ranked by % attended, then calls made")
    cols = [("#", 8, "C"), ("Telecaller", 36, "L"), ("TL", 24, "L"), ("Leads", 13, "C"), ("Attended", 30, "L"),
            ("Missed", 14, "C"), ("Calls", 13, "C"), ("1st call", 18, "C"), ("Sales", w - 156, "C")]

    def head():
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(*HEAD)
        pdf.set_text_color(*INK)
        for h, cw_, a in cols:
            pdf.cell(cw_, 7, h, fill=True, align=a)
        pdf.ln()
    head()
    rows = r["telecallers"]
    if not rows:
        pdf.cell(w, 7, "No telecaller had leads or calls yet.", **nl)
    flagged = len(rows) > 6
    for i, tc in enumerate(rows):
        if pdf.get_y() + 7 > pdf.h - 16:
            page(sub)
            head()
        yy = pdf.get_y()
        good, bad = flagged and i < 3, flagged and i >= len(rows) - 3
        if good or bad:
            pdf.set_fill_color(*(LIGHT_GREEN if good else LIGHT_RED))
            pdf.rect(left, yy, w, 7, "F")
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(*(GREEN if good else RED if bad else INK))
        pdf.cell(8, 7, str(i + 1), align="C")
        pdf.set_text_color(*INK)
        pdf.cell(36, 7, _t(tc["name"])[:22])
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(24, 7, _t(tc["team_leader"])[:14])
        pdf.cell(13, 7, str(tc["leads"]), align="C")
        p = tc["attended_pct"]
        if p is not None:
            bar(left + 81, yy + 2.3, 15, 2.6, p, 100, GREEN if p >= 80 else AMBER if p >= 50 else RED)
        pdf.set_x(left + 98)
        pdf.cell(13, 7, _pct(tc))
        pdf.set_text_color(*(RED if tc["missed"] else MUTED))
        pdf.cell(14, 7, str(tc["missed"]), align="C")
        pdf.set_text_color(*INK)
        pdf.cell(13, 7, str(tc["calls"]), align="C")
        fc = tc["avg_first_call"]
        pdf.set_text_color(*(RED if fc is not None and fc > 15 else INK))
        pdf.cell(18, 7, f"{fc} min" if fc is not None else "-", align="C")
        pdf.set_text_color(*INK)
        pdf.cell(w - 156, 7, str(tc["converted"]), align="C", **nl)
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(w, 4, "Attended = the lead got a call or a status. Calls = leads called or updated in this period, in the "
                   "app or on the Google Sheet, follow-ups of older leads too (each lead once). 1st call = average minutes from the lead arriving to its first "
                   "call (red over 15 min). Sales = leads converted. Green rows = top 3, red rows = bottom 3.", **nl)
    pdf.ln(5)

    pending = r["not_attended"][:15]
    room(24, sub)
    heading("Still waiting for a call", f"   {t['not_attended']} leads - oldest first, ! = escalated to TL")
    pcols = [("Customer", 44), ("Store", 36), ("Source", 26), ("With", 42), ("Came at", w - 148)]
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(*HEAD)
    for h, cw_ in pcols:
        pdf.cell(cw_, 7, h, fill=True)
    pdf.ln()
    if not pending:
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(w, 7, "None - every lead got a call.", **nl)
    for p in pending:
        esc = p["escalated"]
        pdf.set_font("Helvetica", "B" if esc else "", 9)
        pdf.set_text_color(*(RED if esc else INK))
        pdf.cell(44, 6.5, _t(("! " if esc else "") + p["name"])[:26], border="B")
        pdf.set_font("Helvetica", "", 9)
        for val, cw_ in zip((p["store"], p["source"], p["owner"], p["received"]), [c[1] for c in pcols[1:]]):
            pdf.set_text_color(*(RED if val == "Unassigned" else INK))
            pdf.cell(cw_, 6.5, _t(val)[:24], border="B")
        pdf.ln()
    more = t["not_attended"] - len(pending)
    if more > 0:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(w, 6, f"... and {more} more - see Leads in the dashboard.", **nl)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(w, 6, _t(f"Generated {r['generated_at']} IST by BP Analytics."), **nl)
    return bytes(pdf.output())


REPORT_VARIABLES = ("period", "received", "attended", "not_attended")


def template_fit(t: dict) -> list[str]:
    """What's wrong with a Meta template for this report ([] = usable)."""
    comps = {c.get("type", "").upper(): c for c in t.get("components") or []}
    problems = []
    if (comps.get("HEADER") or {}).get("format", "").upper() != "DOCUMENT":
        problems.append("header must be a Document")
    body = (comps.get("BODY") or {}).get("text", "")
    missing = [v for v in REPORT_VARIABLES if "{{" + v + "}}" not in body]
    if missing:
        problems.append("body needs " + ", ".join("{{" + v + "}}" for v in missing))
    if (t.get("status") or "").upper() != "APPROVED":
        problems.append(f"not approved yet ({(t.get('status') or 'unknown').lower()})")
    return problems


async def report_template_status(db: AsyncSession) -> dict:
    """The report's WhatsApp template (C1, under its current name) as it
    is on Meta: what's wrong with it, if anything."""
    from ..whatsapp.client import WhatsAppError, list_templates
    from ..whatsapp.config import get_config
    from ..whatsapp.templates import get_template
    tpl = await get_template(db, TEMPLATE_KEY)
    out = {"name": tpl["name"], "language": tpl["language"], "problems": [], "error": None}
    cfg = await get_config(db)
    if not (cfg.ready and cfg.waba_id):
        out["error"] = "WhatsApp is not connected (Settings → WhatsApp)"
        return out
    try:
        rows = await list_templates(cfg)
    except WhatsAppError as e:
        out["error"] = str(e)
        return out
    on_meta = next((t for t in rows if t.get("name") == tpl["name"] and t.get("language") == tpl["language"]), None)
    out["problems"] = template_fit(on_meta) if on_meta else [f"no template {tpl['name']} ({tpl['language']}) on the account yet"]
    return out


# ── delivery ───────────────────────────────────────────────────────
def email_ready() -> bool:
    return bool(settings.SMTP_HOST and (settings.SMTP_FROM or settings.SMTP_USER))


def _send_email(to: list[str], subject: str, text: str, pdf: bytes, filename: str) -> None:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, settings.SMTP_FROM or settings.SMTP_USER, ", ".join(to)
    msg.set_content(text)
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=filename)
    smtp_cls = smtplib.SMTP_SSL if settings.SMTP_PORT == 465 else smtplib.SMTP
    with smtp_cls(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30) as s:
        if settings.SMTP_PORT != 465:
            s.starttls()
        if settings.SMTP_USER:
            s.login(settings.SMTP_USER, settings.SMTP_PASS)
        s.send_message(msg)


async def ceo_numbers(db: AsyncSession) -> list[str]:
    return sorted({r for r in (await db.execute(
        select(WhatsAppContact.phone).where(WhatsAppContact.role == "ceo"))).scalars().all() if r})


async def _send_whatsapp(db: AsyncSession, cfg, numbers: list[str], r: dict,
                         pdf: bytes, filename: str, sent_by: int | None) -> list[dict]:
    from ..whatsapp.client import WhatsAppError, _call, send_template
    from ..whatsapp.templates import get_template
    tpl = await get_template(db, TEMPLATE_KEY)
    media = await _call(cfg, "POST", f"{cfg.phone_number_id}/media",
                        data={"messaging_product": "whatsapp", "type": "application/pdf"},
                        files={"file": (filename, pdf, "application/pdf")})
    t = r["total"]
    values = {"period": r["period"], "received": t["received"], "attended": t["attended"],
              "not_attended": t["not_attended"]}
    components = [
        {"type": "header", "parameters": [{"type": "document", "document": {"id": media["id"], "filename": filename}}]},
        {"type": "body", "parameters": [{"type": "text", "parameter_name": k, "text": str(v)} for k, v in values.items()]},
    ]
    out = []
    for to in numbers:
        try:
            await send_template(db, cfg, to=to, template=tpl["name"], language=tpl["language"], components=components,
                                params=values, purpose="ceo_report", sent_by=sent_by)
            out.append({"to": to, "ok": True})
        except WhatsAppError as e:
            out.append({"to": to, "ok": False, "error": str(e)})
    return out


async def send_ceo_report(db: AsyncSession, *, now: datetime | None = None, sent_by: int | None = None) -> dict:
    """Build the report and send it on every configured channel."""
    from ..whatsapp.config import get_config
    cfg_report = await get_report_settings(db)
    r = await build_report(db, now)
    pdf = render_pdf(r)
    filename = f"lead-report-{to_ist(now or utcnow()).strftime('%Y-%m-%d-%H%M')}.pdf"
    t = r["total"]
    summary = (f"{r['title']}\nLeads {r['period']}: {t['received']} received, {t['attended']} attended, "
               f"{t['not_attended']} not attended, {t['escalated']} escalated to team leaders.\n"
               f"The full report is attached.")
    result: dict = {"email": None, "whatsapp": None, "period": r["period"], "totals": t}

    emails = cfg_report["emails"]
    if email_ready() and emails:
        try:
            await asyncio.to_thread(_send_email, emails, r["title"], summary, pdf, filename)
            result["email"] = {"ok": True, "to": emails}
        except (smtplib.SMTPException, OSError) as e:
            logger.error("CEO report email failed: %s", e)
            result["email"] = {"ok": False, "to": emails, "error": str(e)[:300]}
    else:
        result["email"] = {"ok": False, "skipped": "SMTP not configured" if not email_ready() else "no report emails"}

    cfg = await get_config(db)
    numbers = await ceo_numbers(db)
    if cfg.active and cfg_report["whatsapp"] and numbers:
        try:
            result["whatsapp"] = await _send_whatsapp(db, cfg, numbers, r, pdf, filename, sent_by)
        except Exception as e:  # the media upload itself failed
            logger.error("CEO report WhatsApp failed: %s", e)
            result["whatsapp"] = [{"ok": False, "error": str(e)[:300]}]
    else:
        result["whatsapp"] = {"ok": False, "skipped": "WhatsApp not active" if not cfg.active else
                              "turned off for the report" if not cfg_report["whatsapp"] else "no CEO numbers"}

    await _set_json(db, LAST_KEY, {"at": utcnow().isoformat(), **result})
    await db.commit()
    logger.info("CEO report %s: email=%s whatsapp=%s", r["period"], result["email"], result["whatsapp"])
    return result
