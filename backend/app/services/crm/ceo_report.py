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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...models.models import Role, Store, TeleCallLead, User, WhatsAppContact
from .config import _get_json, _set_json
from .engine import user_names
from .timeutil import from_ist, to_ist, utcnow

logger = logging.getLogger(__name__)

REPORT_KEY = "crm.ceo_report"
LAST_KEY = "crm.ceo_report.last"
DEFAULT_REPORT = {"enabled": True, "emails": [], "whatsapp": True}
TEMPLATE_KEY = "C1"  # services/whatsapp/templates.py — its name can be changed in Settings → WhatsApp
DAY_STARTS_AT = time(20, 0)  # a "lead day" runs from 8 PM the evening before
SOURCES = {"website": "Website", "facebook": "Facebook", "instagram": "Instagram", "meta_sheet": "Meta (sheet)"}


async def get_report_settings(db: AsyncSession) -> dict:
    return {**DEFAULT_REPORT, **(await _get_json(db, REPORT_KEY) or {})}


async def save_report_settings(db: AsyncSession, value: dict, user_id: int | None) -> dict:
    merged = {**await get_report_settings(db), **{k: v for k, v in (value or {}).items() if k in DEFAULT_REPORT}}
    merged["emails"] = sorted({e.strip() for e in merged["emails"] if e and "@" in e})
    await _set_json(db, REPORT_KEY, merged, user_id)
    return merged


def report_window(now: datetime) -> tuple[datetime, datetime]:
    """(start, end) as naive UTC: 8 PM IST the evening before → now."""
    ist = to_ist(now)
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
    }


# ── PDF ────────────────────────────────────────────────────────────
def _t(text) -> str:
    """The PDF core font is Latin-1: anything else becomes '?'."""
    return str(text).replace("—", "-").replace("–", "-").replace("→", "->").encode("latin-1", "replace").decode("latin-1")


def render_pdf(r: dict) -> bytes:
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    w = pdf.w - pdf.l_margin - pdf.r_margin
    nl = {"new_x": XPos.LMARGIN, "new_y": YPos.NEXT}

    pdf.set_fill_color(15, 23, 42)
    pdf.rect(0, 0, pdf.w, 30, "F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(pdf.l_margin, 8)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(w, 8, _t("BreakProtection - " + r["title"]), **nl)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(w, 6, _t(f"Leads received {r['period']}"), **nl)
    pdf.set_text_color(15, 23, 42)
    pdf.ln(8)

    t = r["total"]
    tiles = [("Leads received", t["received"], (37, 99, 235)), ("Attended", t["attended"], (16, 185, 129)),
             ("Not attended", t["not_attended"], (239, 68, 68)), ("Escalated to TL", t["escalated"], (245, 158, 11))]
    tw, y = (w - 3 * 4) / 4, pdf.get_y()
    for i, (label, value, color) in enumerate(tiles):
        x = pdf.l_margin + i * (tw + 4)
        pdf.set_draw_color(*color)
        pdf.set_line_width(0.6)
        pdf.rect(x, y, tw, 22)
        pdf.set_xy(x, y + 3)
        pdf.set_font("Helvetica", "B", 18)
        pdf.set_text_color(*color)
        pdf.cell(tw, 9, str(value), align="C")
        pdf.set_xy(x, y + 13)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(71, 85, 105)
        pdf.cell(tw, 5, label, align="C")
    pdf.set_y(y + 26)
    pdf.set_text_color(15, 23, 42)
    pdf.set_font("Helvetica", "", 10)
    avg = f"{r['avg_first_call_minutes']} min" if r["avg_first_call_minutes"] is not None else "-"
    pdf.cell(w, 6, _t(f"Attended: {r['attended_pct']}%   ·   Average time to first call: {avg}   ·   "
                     f"Converted: {r['converted']}   ·   Waiting in night queue: {r['waiting_in_queue']}   ·   "
                     f"Unassigned: {r['unassigned']}"), **nl)
    pdf.ln(3)

    def table(title: str, head: list[str], widths: list[float], rows: list[list], red_col: int | None = None):
        if pdf.get_y() > pdf.h - 40:
            pdf.add_page()
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(w, 8, _t(title), **nl)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(241, 245, 249)
        for h, cw in zip(head, widths):
            pdf.cell(cw * w, 7, _t(h), border="B", fill=True, align="L" if h == head[0] else "C")
        pdf.ln()
        pdf.set_font("Helvetica", "", 9)
        if not rows:
            pdf.cell(w, 7, "None", **nl)
        for row in rows:
            if pdf.get_y() > pdf.h - 20:
                pdf.add_page()
            for i, (val, cw) in enumerate(zip(row, widths)):
                pdf.set_text_color(220, 38, 38) if red_col == i and val not in (0, "0", "") else pdf.set_text_color(15, 23, 42)
                pdf.cell(cw * w, 6.5, _t(val)[:60], border="B", align="L" if i == 0 else "C")
            pdf.ln()
        pdf.set_text_color(15, 23, 42)
        pdf.ln(4)

    cols, widths = ["", "Received", "Attended", "Not attended", "Escalated"], [0.4, 0.15, 0.15, 0.15, 0.15]

    def counts(rows):
        return [[x["name"], x["received"], x["attended"], x["not_attended"], x["escalated"]] for x in rows]

    table("By team leader", ["Team leader"] + cols[1:], widths, counts(r["by_team_leader"]), red_col=3)
    table("By telecaller", ["Telecaller"] + cols[1:], widths, counts(r["by_telecaller"]), red_col=3)
    table("By source", ["Source"] + cols[1:], widths, counts(r["by_source"]), red_col=3)
    table("Not attended yet", ["Customer", "Store", "Source", "Owner", "Received"], [0.24, 0.24, 0.14, 0.24, 0.14],
          [[p["name"] + (" (escalated)" if p["escalated"] else ""), p["store"], p["source"], p["owner"], p["received"]]
           for p in r["not_attended"]])
    if r["not_attended_more"]:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(w, 6, f"... and {r['not_attended_more']} more - see Leads in the dashboard.", **nl)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(w, 6, _t(f"Generated {r['generated_at']} IST by BP Analytics. Attended = a call or status was logged."), **nl)
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
