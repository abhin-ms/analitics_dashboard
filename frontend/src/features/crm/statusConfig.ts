/**
 * One status / stage / priority vocabulary and colour set for every page
 * that shows telecalling leads (Leads, Leads Update, both role dashboards
 * and the CRM pages). Mirrors backend app/services/crm/status.py.
 */

export const NO_STATUS = "No Status";

/** Contact statuses, in display order (same list the sheets use). */
export const STATUS_OPTIONS = [
  "Call Not Connected",
  "Call back later",
  "Not Interested",
  "Will Visit",
  "Appointment",
  "Sale Conversion",
  "Wrong number",
  "Unattended",
] as const;

export const STATUS_COLORS: Record<string, string> = {
  "Call Not Connected": "#ef4444",
  "Call back later": "#f59e0b",
  "Not Interested": "#6b7280",
  "Will Visit": "#3b82f6",
  "Appointment": "#8b5cf6",
  "Sale Conversion": "#10b981",
  "Wrong number": "#6b7280",
  "Unattended": "#f97316",
  [NO_STATUS]: "#64748b",
};

export const UNKNOWN_STATUS_COLOR = "#94a3b8";

export function statusColor(status: string | null | undefined): string {
  return STATUS_COLORS[status || NO_STATUS] || UNKNOWN_STATUS_COLOR;
}

/** Status list with "No Status" first — the order status chips use. */
export const STATUS_CHIP_ORDER = [NO_STATUS, ...STATUS_OPTIONS];

export const NOT_CONNECTED_STATUSES = ["Call Not Connected", "Wrong number", "Unattended"];
export const FOLLOW_UP_STATUSES = ["Call Not Connected", "Unattended", "Call back later"];

export const STAGES = [
  { key: "new", label: "New", color: "#64748b" },
  { key: "contacting", label: "Contacting", color: "#f59e0b" },
  { key: "qualified", label: "Qualified", color: "#3b82f6" },
  { key: "paid_advance", label: "Paid Advance", color: "#ec4899" },
  { key: "converted", label: "Converted Customer", color: "#10b981" },
  { key: "not_interested", label: "Not Interested", color: "#6b7280" },
] as const;

export type StageKey = (typeof STAGES)[number]["key"];

export function stageMeta(key: string | null | undefined) {
  return STAGES.find((s) => s.key === key) || STAGES[0];
}

export const PRIORITIES = [
  { key: "hot", label: "Hot", color: "#ef4444" },
  { key: "warm", label: "Warm", color: "#f59e0b" },
  { key: "cold", label: "Cold", color: "#3b82f6" },
] as const;

export function priorityMeta(key: string | null | undefined) {
  return PRIORITIES.find((p) => p.key === key) || PRIORITIES[1];
}

export const ATTENDANCE = [
  { key: "scheduled", label: "Scheduled", color: "#3b82f6" },
  { key: "attended", label: "Attended", color: "#10b981" },
  { key: "no_show", label: "No-show", color: "#ef4444" },
  { key: "rescheduled", label: "Rescheduled", color: "#f59e0b" },
  { key: "cancelled", label: "Cancelled", color: "#6b7280" },
] as const;

export const FOLLOWUP_KIND_LABELS: Record<string, string> = {
  first_call: "First call",
  call: "Call",
  callback: "Callback",
  appointment_confirm: "Confirm appointment",
};

/** Log-activity outcomes, grouped the way the dialog shows them. */
export const OUTCOME_GROUPS: { label: string; outcomes: { key: string; label: string; hint: string }[] }[] = [
  {
    label: "Did not connect",
    outcomes: [
      { key: "no_answer", label: "No answer", hint: "Retry in 3½ hours" },
      { key: "switched_off", label: "Switched off", hint: "Retry next working day" },
      { key: "busy", label: "Busy", hint: "Retry in 45 min · max 2 calls a day" },
      { key: "wrong_number", label: "Wrong number", hint: "Stops the sequence" },
    ],
  },
  {
    label: "Connected",
    outcomes: [
      { key: "callback_requested", label: "Callback requested", hint: "Pick the customer's time" },
      { key: "will_visit", label: "Will visit", hint: "Warm · confirm next working day" },
      { key: "appointment_booked", label: "Appointment booked", hint: "Pick date & time" },
      { key: "advance_paid", label: "Advance paid", hint: "Stage → Paid Advance (Hot)" },
      { key: "converted", label: "Converted (sale)", hint: "Closes the lead" },
      { key: "not_interested", label: "Not interested", hint: "Closes the lead" },
      { key: "connected_other", label: "Connected – other", hint: "Set the next follow-up" },
    ],
  },
  {
    label: "Other",
    outcomes: [{ key: "note", label: "Note only", hint: "No call — just a note" }],
  },
];

export const OUTCOME_LABELS: Record<string, string> = Object.fromEntries(
  OUTCOME_GROUPS.flatMap((g) => g.outcomes.map((o) => [o.key, o.label])),
);

export const ALERT_KIND_LABELS: Record<string, string> = {
  first_call_overdue: "First call overdue",
  first_call_escalated: "Escalated",
  followup_overdue: "Follow-up overdue",
  reassigned_to_you: "Reassigned to you",
  unassigned: "Unassigned lead",
  no_agent_available: "No agent available",
  weekly_review: "Weekly review",
  coaching: "Coaching",
};
