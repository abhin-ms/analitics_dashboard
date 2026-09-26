import { Fragment, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Download, MessageSquare, ChevronDown, ChevronRight } from "lucide-react";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useToast } from "@/components/shared/Toast";
import { downloadExport, useAgentReport, useCoach, useCrmMeta } from "../api";
import type { AgentRow, Targets } from "../types";
import { addDaysKey, fmtDateTime, fmtINR, todayIST } from "../format";
import { StatusBar, StatusChips } from "../components/shared";
import { Button, Card, CardHeader, Empty, Field, InfoNote, Modal, PageHeader, inputCls, inlineInputCls } from "../components/ui";

function mondayOf(key: string): string {
  const [y, m, d] = key.split("-").map(Number);
  const dow = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7; // Mon=0
  return addDaysKey(key, -dow);
}

function Metric({ pct, num, den, prev, target, suffix }: {
  pct: number | null | undefined; num?: number; den?: number; prev?: number | null; target?: number; suffix?: string;
}) {
  if (pct === null || pct === undefined) return <span className="text-[var(--text-muted)]">—</span>;
  const color = target === undefined ? "var(--text-primary)" : pct >= target ? "#10b981" : "#ef4444";
  return (
    <div>
      <span className="font-semibold" style={{ color }}>{pct}%</span>
      <p className="text-[11px] text-[var(--text-muted)]">
        {num !== undefined && den !== undefined ? `${num}/${den}` : ""}{suffix ? ` ${suffix}` : ""}
        {prev !== undefined && prev !== null ? ` · previous ${prev}%` : ""}
      </p>
    </div>
  );
}

function CoachDialog({ agent, onClose }: { agent: AgentRow; onClose: () => void }) {
  const toast = useToast();
  const coach = useCoach();
  const [note, setNote] = useState("");
  return (
    <Modal open onClose={onClose} title={`Coach · ${agent.name}`}
      footer={<><Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!note.trim()} loading={coach.isPending} onClick={async () => {
          try {
            await coach.mutateAsync({ user_id: agent.user_id, note });
            toast.success(`Coaching note sent to ${agent.name}`);
            onClose();
          } catch (e) { toast.error(e instanceof Error ? e.message : "Could not send"); }
        }}>Send note</Button></>}>
      <div className="space-y-3">
        <Field label="Note to the agent" hint="Arrives in their Alerts inbox. It also closes the weekly review about them in yours.">
          <textarea className={inputCls} rows={4} value={note} onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. First calls are slipping after lunch — block 2–3 PM for new leads." />
        </Field>
      </div>
    </Modal>
  );
}

export function AgentTable({ rows, targets, firstCallMinutes, canCoach }: {
  rows: AgentRow[]; targets: Targets; firstCallMinutes: number; canCoach: boolean;
}) {
  const [open, setOpen] = useState<number | null>(null);
  const [coaching, setCoaching] = useState<AgentRow | null>(null);
  if (!rows.length) return <Empty>No agents in this view.</Empty>;
  return (
    <>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[11px] text-[var(--text-muted)] border-b border-[var(--border-subtle)]">
              <th className="py-2.5 pl-5 pr-3 text-left font-semibold">Agent / branch</th>
              <th className="py-2.5 pr-3 text-left font-semibold">First call ≤{firstCallMinutes} min</th>
              <th className="py-2.5 pr-3 text-left font-semibold">Follow-ups on time</th>
              <th className="py-2.5 pr-3 text-left font-semibold">Calls logged</th>
              <th className="py-2.5 pr-3 text-left font-semibold">Connected (status)</th>
              <th className="py-2.5 pr-3 text-left font-semibold">Converted / leads</th>
              {canCoach && <th className="py-2.5 pr-5 text-right font-semibold">Review</th>}
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border-subtle)]">
            {rows.map((r) => (
              <Fragment key={r.user_id}>
                <tr className="hover:bg-[var(--bg-card-hover)] align-top">
                  <td className="py-3 pl-5 pr-3">
                    <button className="flex items-center gap-1 text-white font-medium cursor-pointer" onClick={() => setOpen(open === r.user_id ? null : r.user_id)}>
                      {open === r.user_id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}{r.name}
                    </button>
                    <p className="text-[11px] text-[var(--text-muted)] ml-5">{(r.sheets || []).join(", ") || "—"} · {r.total_leads} leads{r.available === false ? " · away" : ""}</p>
                  </td>
                  <td className="py-3 pr-3"><Metric pct={r.first_call_pct} num={r.first_calls_on_time} den={r.first_calls_total}
                    prev={r.previous.first_call_pct} target={targets.first_call_pct} /></td>
                  <td className="py-3 pr-3"><Metric pct={r.followups_on_time_pct} num={r.followups_on_time} den={r.followups_total}
                    prev={r.previous.followups_on_time_pct} target={targets.followup_on_time_pct} /></td>
                  <td className="py-3 pr-3">
                    <span className="text-white font-semibold">{r.calls_logged ?? 0}</span>
                    <p className="text-[11px] text-[var(--text-muted)]">{r.connected_logged_pct != null ? `${r.connected_logged_pct}% connected` : "—"} · previous {r.previous.calls_logged}</p>
                  </td>
                  <td className="py-3 pr-3"><Metric pct={r.total_leads - r.no_status > 0 ? r.connected_pct : null}
                    num={r.calls_connected} den={r.calls_connected + r.calls_not_connected} prev={r.previous.connected_pct} /></td>
                  <td className="py-3 pr-3">
                    <span className="font-semibold text-white">{r.conversion_pct}%</span>
                    <p className="text-[11px] text-[var(--text-muted)]">{r.converted}/{r.total_leads}{r.low_sample ? " · low sample" : ""} · previous {r.previous.conversion_pct}%</p>
                  </td>
                  {canCoach && (
                    <td className="py-3 pr-5 text-right">
                      <Button size="sm" onClick={() => setCoaching(r)}><MessageSquare size={13} />Coach</Button>
                    </td>
                  )}
                </tr>
                {open === r.user_id && (
                  <tr className="bg-[var(--bg-primary)]">
                    <td colSpan={canCoach ? 7 : 6} className="px-5 py-4 space-y-3">
                      <StatusBar counts={r.status_counts} />
                      <StatusChips counts={r.status_counts} showAll size="sm" />
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                        <div><p className="text-[var(--text-muted)]">Will Visit</p><p className="text-white font-semibold">{r.will_visit}</p></div>
                        <div><p className="text-[var(--text-muted)]">Appointments</p><p className="text-white font-semibold">{r.appointments}</p></div>
                        <div><p className="text-[var(--text-muted)]">Avg time to first call</p><p className="text-white font-semibold">{r.avg_first_call_minutes != null ? `${r.avg_first_call_minutes} min` : "—"}</p></div>
                        <div><p className="text-[var(--text-muted)]">Sale amount</p><p className="text-emerald-400 font-semibold">{fmtINR(r.total_sale_amount)}</p></div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {coaching && <CoachDialog agent={coaching} onClose={() => setCoaching(null)} />}
    </>
  );
}

export default function ReportsPage() {
  const toast = useToast();
  const { data: meta } = useCrmMeta();
  const [sp, setSp] = useSearchParams();
  const thisMonday = mondayOf(todayIST());
  const start = sp.get("start") || thisMonday;
  const end = sp.get("end") || todayIST();
  const sheet = sp.get("sheet") || "";
  const agent = sp.get("agent") || "";
  const { data, isLoading, error } = useAgentReport({ start, end, sheet, agent });
  const set = (patch: Record<string, string>) => {
    const next = new URLSearchParams(sp);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    setSp(next, { replace: true });
  };
  const preset = useMemo(() => {
    if (start === thisMonday && end === todayIST()) return "this";
    if (start === addDaysKey(thisMonday, -7) && end === addDaysKey(thisMonday, -1)) return "last";
    return "custom";
  }, [start, end, thisMonday]);
  const isAgent = meta?.role === "Telecaller" || meta?.role === "Salesperson";

  return (
    <ErrorBoundary>
      <div className="space-y-4 p-4 sm:p-6">
        <PageHeader
          title={isAgent ? "My performance" : "Agent performance"}
          subtitle={data ? `${data.period.start} to ${data.period.end} · compared with ${data.previous_period.start} to ${data.previous_period.end}` : ""}
          actions={meta?.can.export ? (
            <Button size="sm" onClick={async () => {
              try { await downloadExport({ start, end, sheet }); } catch (e) { toast.error(e instanceof Error ? e.message : "Export failed"); }
            }}><Download size={14} />Export leads</Button>
          ) : undefined}
        />
        <div className="flex flex-wrap items-center gap-2">
          <select className={`${inlineInputCls}`} value={preset} onChange={(e) => {
            if (e.target.value === "this") set({ start: thisMonday, end: todayIST() });
            if (e.target.value === "last") set({ start: addDaysKey(thisMonday, -7), end: addDaysKey(thisMonday, -1) });
          }}>
            <option value="this">This week</option>
            <option value="last">Last week</option>
            <option value="custom" disabled>Custom</option>
          </select>
          <input type="date" className={`${inlineInputCls}`} value={start} onChange={(e) => set({ start: e.target.value })} />
          <span className="text-xs text-[var(--text-muted)]">to</span>
          <input type="date" className={`${inlineInputCls}`} value={end} onChange={(e) => set({ end: e.target.value })} />
          {!isAgent && (
            <select className={`${inlineInputCls}`} value={agent} onChange={(e) => set({ agent: e.target.value })}>
              <option value="">All agents</option>
              {meta?.people.filter((p) => p.role !== "Team Leader").map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          )}
          {(data?.sheets.length ?? 0) > 1 && (
            <select className={`${inlineInputCls}`} value={sheet} onChange={(e) => set({ sheet: e.target.value })}>
              <option value="">All cities</option>
              {data?.sheets.map((s) => <option key={s}>{s}</option>)}
            </select>
          )}
        </div>

        {data && (
          <InfoNote>
            Targets: {data.targets.first_call_pct}% of first calls within {data.first_call_minutes} minutes; {data.targets.followup_on_time_pct}% of
            follow-ups handled on time. Green meets the target, red is below. Fewer than {data.targets.low_sample_leads} leads is marked "low sample".
            {data.go_live && <> First-call and follow-up figures are measured from {fmtDateTime(data.go_live, { withYear: true })}, when the CRM timeline started; status figures cover all sheet data.</>}
          </InfoNote>
        )}

        <Card>
          {isLoading ? <div className="p-5"><TableSkeleton /></div> : error ? (
            <p className="p-5 text-sm text-rose-400">{error instanceof Error ? error.message : "Could not load"}</p>
          ) : (
            <AgentTable rows={data!.rows} targets={data!.targets} firstCallMinutes={data!.first_call_minutes} canCoach={data!.can_coach} />
          )}
        </Card>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card>
            <CardHeader title="What to improve" />
            <div className="px-5 py-4 space-y-4 text-xs">
              <div><p className="text-sm font-semibold text-white">Slow first calls</p>
                <p className="text-[var(--text-muted)] mt-1">Check lead delivery delay, agent availability and workload before coaching response speed.</p></div>
              <div><p className="text-sm font-semibold text-white">Missed follow-ups</p>
                <p className="text-[var(--text-muted)] mt-1">Use the Tasks queue, complete overdue actions first and keep time for callbacks.</p></div>
              <div><p className="text-sm font-semibold text-white">Low conversion with good follow-up</p>
                <p className="text-[var(--text-muted)] mt-1">Review requirements, service fit, price explanations and objections. Compare similar sources, models and coverage.</p></div>
            </div>
          </Card>
          <Card>
            <CardHeader title="Fair measurement" />
            <div className="px-5 py-4 space-y-3 text-xs text-[var(--text-muted)]">
              <p>The first-call clock starts when the lead reaches the CRM and is assigned, not at Meta submission, so sheet delay is not the agent's fault. Only working hours count.</p>
              <p>Missed deadlines stay with the owner at that time. Reassignment never erases history or penalises the new owner.</p>
              <p>Moving a follow-up before it is due is not a miss; moving one that is already overdue still counts as missed.</p>
              <p>Sample sizes are shown. No automatic "poor performer" label from one missed call.</p>
            </div>
          </Card>
        </div>
      </div>
    </ErrorBoundary>
  );
}
