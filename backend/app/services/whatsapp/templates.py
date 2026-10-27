"""The WhatsApp templates submitted to Meta for approval (Utility category,
English), as in "Break Protection – WhatsApp Template Approval".

Body variables are named ({{customer_name}}), so they are sent as named
parameters; a link button's {{1}} is the one positional value it takes.
`body` is only for previews — Meta holds the approved text.
"""
from __future__ import annotations

TEMPLATES: list[dict] = [
    {
        "key": "A1", "name": "booking_received", "label": "Booking received", "recipient": "Customer",
        "trigger": "₹99 booking paid on website",
        "params": [("customer_name", "Rahul"), ("booking_date", "20 Oct 2026"), ("time_slot", "11:00 AM"),
                   ("mobile_model", "iPhone 15"), ("store_name", "Indiranagar")],
        "body": "Hi {{customer_name}},\n\nThank you for your ₹99 Priority Booking with Break Protection. Your slot is reserved.\n\n"
                "Date: {{booking_date}}\nTime: {{time_slot}}\nModel: {{mobile_model}}\nStore: {{store_name}}\n\n"
                "We are checking stock for your model and will update you shortly.\n\nThank you,\nTeam Break Protection",
        "buttons": [],
    },
    {
        "key": "A2", "name": "store_priority_booking", "label": "New priority booking", "recipient": "Store (branch)",
        "trigger": "Same booking, at the same time",
        "params": [("customer_name", "Rahul"), ("customer_number", "9876543210"), ("mobile_model", "iPhone 15"),
                   ("booking_date", "20 Oct 2026"), ("time_slot", "11:00 AM")],
        "body": "New Priority Booking received\n\nCustomer: {{customer_name}}\nMobile No: {{customer_number}}\n"
                "Model: {{mobile_model}}\nDate: {{booking_date}}\nTime: {{time_slot}}\n\nPlease check stock and tap an option below.",
        "buttons": [{"type": "quick_reply", "text": "Stock Available"}, {"type": "quick_reply", "text": "Not Available"}],
    },
    {
        "key": "A3", "name": "stock_unavailable_reschedule", "label": "Stock not available, pick new slot", "recipient": "Store",
        "trigger": "Store taps \"Not Available\"",
        "params": [("customer_name", "Rahul"), ("mobile_model", "iPhone 15"), ("booking_date", "20 Oct 2026"),
                   ("time_slot", "11:00 AM")],
        "body": "Stock not available for this booking.\n\nCustomer: {{customer_name}}\nModel: {{mobile_model}}\n"
                "Original slot: {{booking_date}} at {{time_slot}}\n\n"
                "Please tap Reschedule and select a new date and time. The customer will be informed automatically.",
        "buttons": [{"type": "flow", "text": "Reschedule"}],
    },
    {
        "key": "A4", "name": "booking_confirmed", "label": "Booking confirmed", "recipient": "Customer",
        "trigger": "Store taps \"Stock Available\"",
        "params": [("customer_name", "Rahul"), ("mobile_model", "iPhone 15"), ("booking_date", "20 Oct 2026"),
                   ("time_slot", "11:00 AM"), ("store_name", "Indiranagar")],
        "body": "Hi {{customer_name}},\n\nStock is available for your {{mobile_model}} and your booking is confirmed.\n\n"
                "Date: {{booking_date}}\nTime: {{time_slot}}\nStore: {{store_name}}\n\n"
                "Please reach the store 10 minutes before your booking time.\n\nThank you,\nTeam Break Protection",
        "buttons": [{"type": "url", "text": "Get Directions", "url": "https://maps.google.com/?q={{1}}",
                     "sample": "Break+Protection+Indiranagar", "optional": True}],
    },
    {
        "key": "A5", "name": "booking_rescheduled", "label": "New slot", "recipient": "Customer",
        "trigger": "Store picks a new slot",
        "params": [("customer_name", "Rahul"), ("mobile_model", "iPhone 15"), ("new_date", "21 Oct 2026"),
                   ("new_time_slot", "4:00 PM"), ("store_name", "Indiranagar")],
        "body": "Hi {{customer_name}},\n\nWe are sorry, stock for your {{mobile_model}} was not available for your original slot.\n\n"
                "Your booking has been moved to:\nNew Date: {{new_date}}\nNew Time: {{new_time_slot}}\nStore: {{store_name}}\n\n"
                "Please reach the store 10 minutes before your new booking time. Sorry for the inconvenience.\n\nTeam Break Protection",
        "buttons": [{"type": "quick_reply", "text": "Confirm Slot", "optional": True},
                    {"type": "quick_reply", "text": "Change Slot", "optional": True}],
    },
    {
        "key": "B1", "name": "telecaller_new_lead", "label": "New lead alert", "recipient": "Telecaller",
        "trigger": "When a lead is given to them (a night lead: at hand-over)",
        "params": [("lead_name", "Priya"), ("lead_source", "PM"), ("received_time", "18 Oct 2026, 7:30 PM")],
        "body": "New Lead Received\n\nName: {{lead_name}}\nSource: {{lead_source}}\nReceived at: {{received_time}}\n\n"
                "Please call this customer within 15 minutes.",
        "buttons": [{"type": "url", "text": "View Lead", "url": "https://dash.breakprotection.com/leads/{{1}}", "sample": "1024"}],
    },
    {
        "key": "B2", "name": "lead_not_attended", "label": "Lead not attended", "recipient": "Team leader",
        "trigger": "When a lead isn't called in time and is escalated",
        "params": [("lead_name", "Priya"), ("lead_source", "PM"), ("telecaller_name", "Anil"),
                   ("received_time", "18 Oct 2026, 7:30 PM")],
        "body": "Lead Not Attended\n\nName: {{lead_name}}\nSource: {{lead_source}}\nAssigned to: {{telecaller_name}}\n"
                "Received at: {{received_time}}\n\nThis lead has not been called within 15 minutes. Please follow up.",
        "buttons": [{"type": "url", "text": "View Lead", "url": "https://dash.breakprotection.com/leads/{{1}}", "sample": "1024"}],
    },
    {
        "key": "C1", "name": "lead_report", "label": "CEO lead report (PDF)", "recipient": "CEO",
        "trigger": "Every day at 1 PM and 8 PM",
        "header": "document",  # the report PDF; sent from CRM Settings → CEO lead report, not the test tab
        "params": [("period", "23 Oct 08:00 PM – 24 Oct 01:00 PM"), ("received", "570"), ("attended", "128"),
                   ("not_attended", "442")],
        "body": "Lead report for {{period}}\n\nLeads received: {{received}}\nAttended: {{attended}}\n"
                "Not attended: {{not_attended}}\n\nThe full report is attached as a PDF.",
        "buttons": [],
    },
]

BY_KEY = {t["key"]: t for t in TEMPLATES}

# Meta template names can be changed from Settings → WhatsApp → Templates
# (a template re-created on Meta under a new name, same variables). The
# key (A1, B1…) is what the code sends by; the name is looked up here.
NAMES_KEY = "whatsapp.template_names"
NAME_RE = r"[a-z0-9_]{1,512}"


async def name_overrides(db) -> dict[str, dict]:
    from ..crm.config import _get_json
    return await _get_json(db, NAMES_KEY) or {}


async def save_name(db, key: str, name: str, language: str, user_id: int | None) -> None:
    from ..crm.config import _set_json
    data = await name_overrides(db)
    data[key] = {"name": name, "language": language}
    await _set_json(db, NAMES_KEY, data, user_id)


def _apply(t: dict, override: dict | None) -> dict:
    o = override or {}
    return {**t, "default_name": t["name"], "name": o.get("name") or t["name"], "language": o.get("language") or "en"}


async def effective_templates(db) -> list[dict]:
    """The templates with the names (and languages) they currently have on Meta."""
    overrides = await name_overrides(db)
    return [_apply(t, overrides.get(t["key"])) for t in TEMPLATES]


async def get_template(db, key: str) -> dict:
    """One template by key, with its current name — use this to send."""
    return _apply(BY_KEY[key], (await name_overrides(db)).get(key))


async def by_name(db, name: str) -> dict | None:
    return next((t for t in await effective_templates(db) if t["name"] == name), None)


def public_view(t: dict) -> dict:
    return {**t, "params": [{"name": n, "sample": s} for n, s in t["params"]]}


def build_components(t: dict, values: dict[str, str], button_values: dict[int, str] | None = None,
                     include_buttons: set[int] | None = None, payload_prefix: str = "test") -> list[dict]:
    """The `components` of a Cloud API template message.

    values: body variable → text (every one is required).
    button_values: button index → the {{1}} of a link button.
    include_buttons: indexes of optional buttons that exist on the approved
    template (sending a value for a button Meta doesn't have is an error).
    """
    missing = [n for n, _ in t["params"] if not str(values.get(n, "")).strip()]
    if missing:
        raise ValueError(f"Fill in: {', '.join(missing)}")
    components: list[dict] = [{
        "type": "body",
        "parameters": [{"type": "text", "parameter_name": n, "text": str(values[n]).strip()} for n, _ in t["params"]],
    }]
    include = include_buttons if include_buttons is not None else {
        i for i, b in enumerate(t["buttons"]) if not b.get("optional")}
    for i, b in enumerate(t["buttons"]):
        if i not in include:
            continue
        if b["type"] == "url":
            text = ((button_values or {}).get(i) or b.get("sample") or "").strip()
            if not text:
                raise ValueError(f"Fill in the {b['text']} link value")
            components.append({"type": "button", "sub_type": "url", "index": str(i),
                               "parameters": [{"type": "text", "text": text}]})
        elif b["type"] == "quick_reply":
            components.append({"type": "button", "sub_type": "quick_reply", "index": str(i),
                               "parameters": [{"type": "payload", "payload": f"{payload_prefix}:{t['key']}:{i}"}]})
        elif b["type"] == "flow":
            components.append({"type": "button", "sub_type": "flow", "index": str(i),
                               "parameters": [{"type": "action", "action": {"flow_token": f"{payload_prefix}:{t['key']}"}}]})
    return components
