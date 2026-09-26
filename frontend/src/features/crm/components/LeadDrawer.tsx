import { useEffect, useState } from "react";
import { create } from "zustand";
import {
  X, PhoneCall, CalendarPlus, UserCog, Clock, Flame, AlertTriangle, History, Smartphone, Save,
} from "lucide-react";
import { useToast } from "@/components/shared/Toast";
import { PhoneActions } from "@/components/shared/PhoneActions";
import { useCrmMeta, useLeadDetail, usePatchLead } from "../api";
import { ATTENDANCE, FOLLOWUP_KIND_LABELS, PRIORITIES, STAGES } from "../statusConfig";
import { fmtDateTime, fmtDue, fmtINR } from "../format";
import { AssignDialog, BookAppointmentDialog, LogActivityDialog, ScheduleFollowupDialog } from "./dialogs";
import { Button, Pill, PriorityBadge, StageBadge, StatusBadge, inputCls } from "./ui";

/** Open the lead drawer from anywhere: useLeadDrawer.getState().open(id) */
export const useLeadDrawer = create<{ leadId: number | null; open: (id: number) => void; close: () => void }>((set) => ({
  leadId: null,
  open: (id) => set({ leadId: id }),
  close: () => set({ leadId: null }),
}));

export function openLead(id: number) {
  useLeadDrawer.getState().open(id);
}

/** Mounted once in AppLayout; renders nothing until a lead is opened. */
export function LeadDrawerHost() {
  const leadId = useLeadDrawer((s) => s.leadId);
  const close = useLeadDrawer((s) => s.close);
  if (!leadId) return null;
  return <LeadDrawer leadId={leadId} onClose={close} />;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3 py-1.5 text-xs">
      <span className="text-[var(--text-muted)] shrink-0">{label}</span>
      <span className="text-[var(--text-primary)] text-right min-w-0 break-words">{children}</span>
    </div>
  );
}

function timelineText(t: { type: string; outcome_label?: string | null; old_value?: string | null; new_value?: string | null; label?: string; notes?: string | null }) {
  switch (t.type) {
    case "milestone": return t.label;
    case "call": return `Call · ${t.outcome_label || "logged"}${t.new_value ? ` → ${t.new_value}` : ""}`;
    case "status_change": return `Status: ${t.old_value} → ${t.new_value}`;
    case "stage_change": return `Stage: ${t.old_value} → ${t.new_value}`;
    case "assignment": return `Owner: ${t.old_value} → ${t.new_value}`;
    case "appointment": return t.old_value ? `Appointment: ${t.old_value} → ${t.new_value}` : `Appointment booked · ${t.new_value}`;
    case "note": return t.new_value ? `${t.notes || "Updated"}: ${t.old_value ? `${t.old_value} → ` : ""}${t.new_value}` : "Note";
    case "system": return t.notes || "System";
    default: return t.type;
  }
}

export function LeadDrawer({ leadId, onClose }: { leadId: number; onClose: () => void }) {
  const toast = useToast();
  const { data, isLoading, error } = useLeadDetail(leadId);
  const { data: meta } = useCrmMeta();
  const patch = usePatchLead();
  const [dialog, setDialog] = useState<"" | "log" | "assign" | "appt" | "followup">("");
  const [device, setDevice] = useState({ phone_model: "", service_type: "", coverage: "Standard" });

  const lead = data?.lead;
  useEffect(() => {
    if (lead) setDevice({ phone_model: lead.phone_model || "", service_type: lead.service_type || "", coverage: lead.coverage || "Standard" });
  }, [lead?.id, lead?.phone_model, lead?.service_type, lead?.coverage]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !dialog && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, dialog]);

  const save = async (body: Record<string, unknown>, msg: string) => {
    if (!lead) return;
    try {
      await patch.mutateAsync({ leadId: lead.id, body });
      toast.success(msg);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save");
    }
  };

  const due = fmtDue(lead?.next_follow_up_at);
  const openFollowups = (data?.followups || []).filter((f) => f.status === "open");

  return (
    <div className="fixed inset-0 z-[60] flex justify-end bg-black/50" onClick={onClose}>
      <aside
        className="h-full w-full sm:max-w-xl bg-[var(--bg-card)] border-l border-[var(--border-subtle)] shadow-2xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-[var(--border-subtle)]">
          <div className="min-w-0">
            <h2 className="text-lg font-bold text-white truncate">{lead?.full_name || (isLoading ? "Loading…" : "Lead")}</h2>
            {lead && (
              <div className="text-xs text-[var(--text-muted)] mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1">
                <span>{lead.city} · {lead.lead_source || "—"}</span>
                <PhoneActions phone={lead.phone} />
              </div>
            )}
          </div>
          <button onClick={onClose} className="text-[var(--text-muted)] hover:text-white cursor-pointer"><X size={20} /></button>
        </div>

        {error && <p className="p-5 text-sm text-rose-400">{error instanceof Error ? error.message : "Could not load lead"}</p>}

        {lead && (
          <div className="flex-1 overflow-y-auto">
            <div className="px-5 py-4 space-y-3 border-b border-[var(--border-subtle)]">
              <div className="flex flex-wrap gap-1.5">
                <StageBadge stage={lead.stage} />
                <StatusBadge status={lead.status} />
                <PriorityBadge priority={lead.priority} />
                {lead.first_call_pending && <Pill label={`Call within ${meta?.automation.first_call_minutes ?? 5} min`} color="#3b82f6" />}
                {lead.is_urgent && <Pill label={<span className="inline-flex items-center gap-1"><Flame size={10} />Urgent</span>} color="#ef4444" />}
                {lead.escalated && <Pill label={<span className="inline-flex items-center gap-1"><AlertTriangle size={10} />Escalated</span>} color="#f97316" />}
                {!lead.from_sheet && <Pill label="App lead" color="#06b6d4" />}
              </div>
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" size="sm" onClick={() => setDialog("log")}><PhoneCall size={14} />Log activity</Button>
                <Button size="sm" onClick={() => setDialog("followup")}><Clock size={14} />Schedule follow-up</Button>
                <Button size="sm" onClick={() => setDialog("appt")}><CalendarPlus size={14} />Book appointment</Button>
                {meta?.can.reassign && <Button size="sm" onClick={() => setDialog("assign")}><UserCog size={14} />Assign</Button>}
              </div>
            </div>

            <div className="px-5 py-3 border-b border-[var(--border-subtle)]">
              <Row label="Owner">{lead.owner_name || <span className="text-amber-400">Unassigned</span>}
                {lead.assignment_source && <span className="text-[var(--text-muted)]"> · {lead.assignment_source}</span>}</Row>
              <Row label="Next follow-up"><span className={due.overdue ? "text-rose-400 font-semibold" : ""}>{due.text}</span></Row>
              <Row label="Last contact">{fmtDateTime(lead.last_contact_at)}</Row>
              <Row label="Submitted on Meta">{lead.submitted_at ? fmtDateTime(lead.submitted_at, { withYear: true }) : lead.created_time || "—"}</Row>
              <Row label="Received by CRM">{fmtDateTime(lead.received_at, { withYear: true })}</Row>
              {lead.person_calling && <Row label="Person Calling (sheet)">{lead.person_calling}</Row>}
              {lead.salesperson && <Row label="Salesperson">{lead.salesperson}</Row>}
              {lead.appointment_date && <Row label="Appointment date">{lead.appointment_date}</Row>}
              {lead.sale_amount && <Row label="Sale amount">{lead.sale_amount}</Row>}
              {lead.product && <Row label="Product (sheet)">{lead.product}</Row>}
              {lead.remarks && <Row label="Remarks">{lead.remarks}</Row>}
              {lead.email && <Row label="Email">{lead.email}</Row>}
            </div>

            <div className="px-5 py-4 border-b border-[var(--border-subtle)] grid grid-cols-2 gap-3">
              <label className="block">
                <span className="block text-[11px] text-[var(--text-secondary)] mb-1">Stage</span>
                <select className={inputCls} value={lead.stage}
                  onChange={(e) => save({ stage: e.target.value }, "Stage changed")}>
                  {STAGES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
                </select>
              </label>
              <label className="block">
                <span className="block text-[11px] text-[var(--text-secondary)] mb-1">Priority{lead.priority_manual ? " (set by hand)" : " (automatic)"}</span>
                <select className={inputCls} value={lead.priority_manual ? lead.priority : "auto"}
                  onChange={(e) => save({ priority: e.target.value }, "Priority updated")}>
                  <option value="auto">Automatic ({lead.priority})</option>
                  {PRIORITIES.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
                </select>
              </label>
            </div>

            <div className="px-5 py-4 border-b border-[var(--border-subtle)] space-y-2">
              <p className="text-xs font-semibold text-white flex items-center gap-1.5"><Smartphone size={14} />Device & value</p>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                <input className={inputCls} list="drawer-models" placeholder="Phone model" value={device.phone_model}
                  onChange={(e) => setDevice({ ...device, phone_model: e.target.value })} />
                <input className={inputCls} list="drawer-services" placeholder="Service" value={device.service_type}
                  onChange={(e) => setDevice({ ...device, service_type: e.target.value })} />
                <select className={inputCls} value={device.coverage} onChange={(e) => setDevice({ ...device, coverage: e.target.value })}>
                  {(meta?.coverages || ["Standard"]).map((c) => <option key={c}>{c}</option>)}
                </select>
              </div>
              <div className="flex items-center justify-between">
                <p className="text-xs text-[var(--text-muted)]">
                  Potential value: <span className="text-white font-semibold">
                    {lead.potential_value != null ? fmtINR(lead.potential_value) : lead.phone_model ? "Price review needed" : "Model needed"}
                  </span>
                </p>
                <Button size="sm" loading={patch.isPending}
                  onClick={() => save(device, "Device details saved")}><Save size={13} />Save</Button>
              </div>
              <datalist id="drawer-models">{meta?.phone_models.map((m) => <option key={m} value={m} />)}</datalist>
              <datalist id="drawer-services">{meta?.service_types.map((m) => <option key={m} value={m} />)}</datalist>
            </div>

            {(openFollowups.length > 0 || (data?.appointments.length ?? 0) > 0) && (
              <div className="px-5 py-4 border-b border-[var(--border-subtle)] space-y-2">
                {openFollowups.map((f) => {
                  const d = fmtDue(f.due_at);
                  return (
                    <div key={f.id} className="flex items-center justify-between text-xs">
                      <span className="text-[var(--text-secondary)]">{FOLLOWUP_KIND_LABELS[f.kind] || f.kind} · {f.owner_name || "—"}</span>
                      <span className={d.overdue ? "text-rose-400 font-semibold" : "text-white"}>{d.text}</span>
                    </div>
                  );
                })}
                {data?.appointments.map((a) => {
                  const att = ATTENDANCE.find((x) => x.key === a.attendance);
                  return (
                    <div key={a.id} className="flex items-center justify-between text-xs">
                      <span className="text-[var(--text-secondary)]">Appointment · {a.purpose}</span>
                      <span className="flex items-center gap-2 text-white">{fmtDateTime(a.scheduled_at)}
                        {att && <Pill label={att.label} color={att.color} />}</span>
                    </div>
                  );
                })}
              </div>
            )}

            <div className="px-5 py-4">
              <p className="text-xs font-semibold text-white flex items-center gap-1.5 mb-3"><History size={14} />Timeline</p>
              <ol className="relative border-l border-[var(--border-subtle)] ml-1.5 space-y-3">
                {data!.timeline.map((t, i) => (
                  <li key={t.id ?? `m${i}`} className="ml-4">
                    <span className={`absolute -left-[5px] mt-1.5 w-2.5 h-2.5 rounded-full ${t.type === "milestone" ? "bg-slate-500" : t.user === "System" ? "bg-amber-500" : "bg-blue-500"}`} />
                    <p className="text-xs text-white">{timelineText(t)}</p>
                    {t.notes && t.type !== "system" && t.type !== "note" && <p className="text-[11px] text-[var(--text-secondary)] mt-0.5">{t.notes}</p>}
                    {t.type === "note" && t.notes && !t.new_value && <p className="text-[11px] text-[var(--text-secondary)] mt-0.5">{t.notes}</p>}
                    <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{fmtDateTime(t.at, { withYear: true })}{t.user ? ` · ${t.user}` : ""}</p>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        )}

        {lead && dialog === "log" && <LogActivityDialog lead={lead} open onClose={() => setDialog("")} />}
        {lead && dialog === "assign" && <AssignDialog leads={[lead]} open onClose={() => setDialog("")} />}
        {lead && dialog === "appt" && <BookAppointmentDialog lead={lead} open onClose={() => setDialog("")} />}
        {lead && dialog === "followup" && <ScheduleFollowupDialog lead={lead} open onClose={() => setDialog("")} />}
      </aside>
    </div>
  );
}
