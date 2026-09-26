import { useEffect, useState } from "react";
import { Zap, Save } from "lucide-react";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useToast } from "@/components/shared/Toast";
import { AutomationSettings, useAutomationLog, useAutomationSettings, useSaveAutomation } from "../api";
import type { Targets } from "../types";
import { fmtDateTime } from "../format";
import { openLead } from "../components/LeadDrawer";
import { Button, Card, CardHeader, Empty, Field, InfoNote, PageHeader, Pill, inputCls } from "../components/ui";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function hours(min: number) {
  return min % 60 === 0 ? `${min / 60} h` : min > 60 ? `${Math.floor(min / 60)} h ${min % 60} min` : `${min} min`;
}

export default function AutomationPage() {
  const toast = useToast();
  const { data, isLoading, error } = useAutomationSettings();
  const { data: log } = useAutomationLog();
  const save = useSaveAutomation();
  const [a, setA] = useState<AutomationSettings | null>(null);
  const [t, setT] = useState<Targets | null>(null);

  useEffect(() => {
    if (data) { setA(data.automation); setT(data.targets); }
  }, [data]);

  if (isLoading || !a || !t) return <div className="p-6"><TableSkeleton /></div>;
  if (error) return <p className="p-6 text-sm text-rose-400">{error instanceof Error ? error.message : "Could not load"}</p>;
  const canEdit = !!data?.can_edit;
  const num = (k: keyof AutomationSettings) => (
    <input type="number" min={1} className={inputCls} disabled={!canEdit} value={a[k] as number}
      onChange={(e) => setA({ ...a, [k]: Number(e.target.value) })} />
  );

  const sla = [
    ["Immediately", "Assign an available telecaller of the city (the sheet's Person Calling wins if it names a user); create a first-call task due in " + a.first_call_minutes + " minutes."],
    [`${a.first_call_minutes} minutes · no attempt`, "Alert the owner and move the lead to the urgent queue."],
    [`${a.reassign_minutes} minutes · no attempt`, "Reassign once to another available telecaller of the city. If none, alert the team leader."],
    [`${a.escalate_minutes} minutes · no attempt`, "Escalate to the team leader. Keep one accountable owner."],
  ];

  return (
    <ErrorBoundary>
      <div className="space-y-4 p-4 sm:p-6">
        <PageHeader title="Default contact workflow" subtitle="Agents record outcomes. The system assigns owners and schedules the next step." />
        <InfoNote>
          Working hours {a.working_hours.start}–{a.working_hours.end} IST, {a.working_hours.days.map((d) => DAYS[d]).join(", ")}. Timers only count working
          minutes. Leads come from the Google Sheets every minute (read-only).
          {data?.go_live && <> Automation covers leads received since {fmtDateTime(data.go_live, { withYear: true })}.</>}
          {!a.enabled && <strong className="text-amber-400"> Automation is switched off.</strong>}
        </InfoNote>

        <Card>
          <CardHeader title="Meta leads · enabled by default" icon={<Zap size={15} className="text-amber-400" />}
            action={<Pill label="Standard procedure" color="#3b82f6" />} />
          <table className="w-full text-sm">
            <thead><tr className="text-[11px] text-[var(--text-muted)] border-b border-[var(--border-subtle)]">
              <th className="py-2.5 px-5 text-left font-semibold w-1/3">From CRM receipt</th>
              <th className="py-2.5 pr-5 text-left font-semibold">Automatic action</th></tr></thead>
            <tbody className="divide-y divide-[var(--border-subtle)]">
              {sla.map(([when, what]) => (
                <tr key={when}><td className="py-3 px-5 text-white">{when}</td><td className="py-3 pr-5 text-[var(--text-secondary)]">{what}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card>
          <CardHeader title="After the first attempt" />
          <div className="px-5 py-4 text-sm space-y-1.5 text-[var(--text-secondary)]">
            <p><span className="text-white">No answer</span> → retry in {hours(a.no_answer_retry_minutes)}.</p>
            <p><span className="text-white">Switched off</span> → retry next working day.</p>
            <p><span className="text-white">Busy</span> → retry in {hours(a.busy_retry_minutes)}. Never more than {a.max_calls_per_day} calls a day.</p>
            <p><span className="text-white">Requested callback</span> → at the customer's time.</p>
            <p><span className="text-white">Not interested / Converted / Wrong number</span> → stop the sequence.</p>
            <p><span className="text-white">Overdue follow-up</span> → owner alerted; team leader after {hours(a.overdue_tl_minutes)}; admin after {hours(a.overdue_admin_minutes)}.</p>
            <p className="text-xs text-[var(--text-muted)] pt-2">
              WhatsApp "message due in 5 minutes" steps start when WhatsApp messaging is added. After-hours arrivals wait for opening time; the original submission time is kept.
            </p>
          </div>
        </Card>

        <Card>
          <CardHeader title="Settings" subtitle={canEdit ? "Admin can change these. Changes apply from the next minute." : "Read-only — only Admin can change these."}
            action={canEdit && (
              <Button variant="primary" size="sm" loading={save.isPending} onClick={async () => {
                try {
                  await save.mutateAsync({ automation: a, targets: t });
                  toast.success("Automation settings saved");
                } catch (e) { toast.error(e instanceof Error ? e.message : "Could not save"); }
              }}><Save size={13} />Save</Button>
            )} />
          <div className="px-5 py-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <Field label="Automation"><select className={inputCls} disabled={!canEdit} value={a.enabled ? "on" : "off"}
              onChange={(e) => setA({ ...a, enabled: e.target.value === "on" })}><option value="on">On</option><option value="off">Off</option></select></Field>
            <Field label="Auto-assign new leads"><select className={inputCls} disabled={!canEdit} value={a.auto_assign ? "on" : "off"}
              onChange={(e) => setA({ ...a, auto_assign: e.target.value === "on" })}><option value="on">Round-robin</option><option value="off">Team leader assigns</option></select></Field>
            <Field label="Opens (IST)"><input type="time" className={inputCls} disabled={!canEdit} value={a.working_hours.start}
              onChange={(e) => setA({ ...a, working_hours: { ...a.working_hours, start: e.target.value } })} /></Field>
            <Field label="Closes (IST)"><input type="time" className={inputCls} disabled={!canEdit} value={a.working_hours.end}
              onChange={(e) => setA({ ...a, working_hours: { ...a.working_hours, end: e.target.value } })} /></Field>
            <div className="sm:col-span-2 lg:col-span-4">
              <span className="block text-[11px] font-medium text-[var(--text-secondary)] mb-1">Working days</span>
              <div className="flex flex-wrap gap-2">
                {DAYS.map((d, i) => (
                  <label key={d} className="flex items-center gap-1 text-xs text-[var(--text-secondary)]">
                    <input type="checkbox" disabled={!canEdit} checked={a.working_hours.days.includes(i)}
                      onChange={(e) => setA({ ...a, working_hours: { ...a.working_hours,
                        days: e.target.checked ? [...a.working_hours.days, i].sort() : a.working_hours.days.filter((x) => x !== i) } })} />{d}
                  </label>
                ))}
              </div>
            </div>
            <Field label="First call due (min)">{num("first_call_minutes")}</Field>
            <Field label="Reassign after (min)">{num("reassign_minutes")}</Field>
            <Field label="Escalate after (min)">{num("escalate_minutes")}</Field>
            <Field label="No-answer retry (min)">{num("no_answer_retry_minutes")}</Field>
            <Field label="Busy retry (min)">{num("busy_retry_minutes")}</Field>
            <Field label="Max calls a day">{num("max_calls_per_day")}</Field>
            <Field label="Overdue → team leader (min)">{num("overdue_tl_minutes")}</Field>
            <Field label="Overdue → admin (min)">{num("overdue_admin_minutes")}</Field>
            <Field label="Target: first calls on time (%)"><input type="number" className={inputCls} disabled={!canEdit} value={t.first_call_pct}
              onChange={(e) => setT({ ...t, first_call_pct: Number(e.target.value) })} /></Field>
            <Field label="Target: follow-ups on time (%)"><input type="number" className={inputCls} disabled={!canEdit} value={t.followup_on_time_pct}
              onChange={(e) => setT({ ...t, followup_on_time_pct: Number(e.target.value) })} /></Field>
            <Field label="Follow-up grace (min)"><input type="number" className={inputCls} disabled={!canEdit} value={t.followup_grace_minutes}
              onChange={(e) => setT({ ...t, followup_grace_minutes: Number(e.target.value) })} /></Field>
            <Field label="Low-sample below (leads)"><input type="number" className={inputCls} disabled={!canEdit} value={t.low_sample_leads}
              onChange={(e) => setT({ ...t, low_sample_leads: Number(e.target.value) })} /></Field>
          </div>
        </Card>

        <Card>
          <CardHeader title="Recent automatic actions"
            subtitle={log ? `${log.stats.open_first_calls} first calls pending · ${log.stats.urgent} urgent` : undefined} />
          {!log || log.items.length === 0 ? <Empty>No automatic actions yet.</Empty> : (
            <div className="divide-y divide-[var(--border-subtle)]">
              {log.items.map((it, i) => (
                <div key={i} className="px-5 py-3 text-xs flex flex-col sm:flex-row sm:items-center gap-1 sm:gap-3">
                  <span className="text-[var(--text-muted)] w-32 shrink-0">{fmtDateTime(it.at)}</span>
                  <button onClick={() => openLead(it.lead_id)} className="text-blue-400 hover:underline cursor-pointer text-left">{it.lead_name}</button>
                  <span className="text-[var(--text-secondary)] flex-1">
                    {it.type === "assignment" ? `Owner ${it.from || "Unassigned"} → ${it.to || "Unassigned"}` : it.notes}
                    {it.type === "assignment" && it.notes ? ` · ${it.notes}` : ""}
                  </span>
                  <span className="text-[var(--text-muted)]">{it.city}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </ErrorBoundary>
  );
}
