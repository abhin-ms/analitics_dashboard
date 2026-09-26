/** Telecalling sections added to the existing Telecaller and Team Leader
 * dashboards (the original dashboard sections stay exactly as they were). */
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, Coffee, ShieldCheck, Users, Activity } from "lucide-react";
import { useToast } from "@/components/shared/Toast";
import { useSetAvailability } from "../api";
import type { AgentRow, QueueTiles, Targets } from "../types";
import { fmtINR } from "../format";
import { statusColor, NO_STATUS } from "../statusConfig";
import { AgentTable } from "../pages/ReportsPage";
import { PeriodFilter, PeriodKey, StatusBar, StatusChips } from "./shared";
import { Button, Card, CardHeader, Tile } from "./ui";

export interface PeriodState {
  key: PeriodKey;
  custom: { start: string; end: string };
  setKey: (k: PeriodKey) => void;
  setCustom: (c: { start: string; end: string }) => void;
}

function Delta({ cur, prev, suffix = "", invert }: { cur: number | null | undefined; prev: number | null | undefined; suffix?: string; invert?: boolean }) {
  if (cur == null || prev == null) return null;
  const diff = Math.round((cur - prev) * 10) / 10;
  if (diff === 0) return <span className="text-[10px] text-[var(--text-muted)]">same as before</span>;
  const good = invert ? diff < 0 : diff > 0;
  return <span className={`text-[10px] ${good ? "text-emerald-400" : "text-rose-400"}`}>{diff > 0 ? "▲" : "▼"} {Math.abs(diff)}{suffix} vs previous</span>;
}

function TodayTiles({ today, mine }: { today: QueueTiles; mine: boolean }) {
  const navigate = useNavigate();
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <Tile label="First contact" value={today.first_contact_pending} hint="Awaiting a first call ↗" onClick={() => navigate("/crm/leads?tab=new")} />
      <Tile label="Due today" value={today.due_today} hint={mine ? "Your next actions ↗" : "Team's next actions ↗"} onClick={() => navigate("/crm/tasks")} />
      <Tile label="Overdue" value={today.overdue} hint="Needs attention ↗" color={today.overdue ? "#ef4444" : undefined} onClick={() => navigate("/crm/leads?tab=overdue")} />
      <Tile label="Unassigned" value={today.unassigned} hint={mine ? "In your city ↗" : "Assign an owner ↗"} color={today.unassigned ? "#f59e0b" : undefined}
        onClick={() => navigate("/crm/leads?tab=unassigned")} />
    </div>
  );
}

export function TelecallerCrmPanel({ data, period }: { data: any; period: PeriodState }) {
  const navigate = useNavigate();
  const toast = useToast();
  const setAvail = useSetAvailability();
  const [scope, setScope] = useState<"my" | "city">("my");
  if (!data?.my) return null;
  const my: AgentRow = data.my;
  const targets: Targets = data.targets;
  const counts: Record<string, number> = scope === "my" ? my.status_counts : data.city.status_counts;
  const p = my.previous;

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <PeriodFilter allowAll value={period.key} onChange={period.setKey} custom={period.custom} onCustom={period.setCustom} />
        <div className="flex items-center gap-2">
          <Button size="sm" loading={setAvail.isPending} onClick={async () => {
            await setAvail.mutateAsync({ available: !data.available });
            toast.success(data.available ? "You are Away — new leads won't be auto-assigned to you" : "You are Available");
          }}>
            {data.available ? <><ShieldCheck size={14} className="text-emerald-400" />Available</> : <><Coffee size={14} className="text-amber-400" />Away</>}
          </Button>
          <Link to="/crm" className="text-xs text-blue-400 hover:underline inline-flex items-center gap-1">Open my day <ArrowRight size={12} /></Link>
        </div>
      </div>

      {data.today && <TodayTiles today={data.today} mine />}

      <Card>
        <CardHeader title="Lead status" icon={<Activity size={15} className="text-blue-400" />}
          subtitle={scope === "my" ? "Leads you own — click a status to open them" : `Every lead on ${data.city.sheets.join(", ") || "your city"} sheet`}
          action={
            <div className="inline-flex rounded-xl border border-[var(--border-subtle)] p-0.5 text-xs">
              {(["my", "city"] as const).map((k) => (
                <button key={k} onClick={() => setScope(k)}
                  className={`px-2.5 py-1 rounded-lg cursor-pointer ${scope === k ? "bg-blue-500/15 text-blue-400 font-semibold" : "text-[var(--text-secondary)]"}`}>
                  {k === "my" ? "My leads" : "Whole city"}
                </button>
              ))}
            </div>
          } />
        <div className="px-5 py-4 space-y-3">
          <StatusBar counts={counts} />
          {Object.keys(counts).length === 0
            ? <p className="text-xs text-[var(--text-muted)]">No leads in this period{scope === "my" ? " assigned to you" : ""}.</p>
            : <StatusChips counts={counts} onChange={(s) => navigate(`/crm/leads?tab=${scope === "my" ? "mine" : "all"}${s ? `&status=${encodeURIComponent(s)}` : ""}`)} />}
        </div>
      </Card>

      <Card>
        <CardHeader title="My numbers" subtitle={`${data.period.start} to ${data.period.end} · compared with the period before`}
          action={<Link to="/crm/reports" className="text-xs text-blue-400 hover:underline">Full report →</Link>} />
        <div className="px-5 py-4 grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            ["Leads owned", my.total_leads, <Delta key="d" cur={my.total_leads} prev={p.total_leads} />],
            ["Calls logged", my.calls_logged ?? 0, <Delta key="d" cur={my.calls_logged ?? 0} prev={p.calls_logged} />],
            ["Connected", `${my.connected_pct}%`, <Delta key="d" cur={my.connected_pct} prev={p.connected_pct} suffix="%" />],
            ["Converted", `${my.converted} · ${my.conversion_pct}%`, <Delta key="d" cur={my.conversion_pct} prev={p.conversion_pct} suffix="%" />],
            ["Will Visit", my.will_visit, null],
            ["Appointments", my.appointments, null],
            ["First calls on time", my.first_call_pct != null ? `${my.first_call_pct}%` : "—",
              my.first_call_pct != null ? <span key="t" className={`text-[10px] ${my.first_call_pct >= targets.first_call_pct ? "text-emerald-400" : "text-rose-400"}`}>target {targets.first_call_pct}% · {my.first_calls_on_time}/{my.first_calls_total}</span> : <span key="t" className="text-[10px] text-[var(--text-muted)]">no first calls yet</span>],
            ["Follow-ups on time", my.followups_on_time_pct != null ? `${my.followups_on_time_pct}%` : "—",
              my.followups_on_time_pct != null ? <span key="t" className={`text-[10px] ${my.followups_on_time_pct >= targets.followup_on_time_pct ? "text-emerald-400" : "text-rose-400"}`}>target {targets.followup_on_time_pct}% · {my.followups_on_time}/{my.followups_total}</span> : <span key="t" className="text-[10px] text-[var(--text-muted)]">none due yet</span>],
          ].map(([label, value, extra]) => (
            <div key={label as string}>
              <p className="text-[11px] text-[var(--text-muted)]">{label}</p>
              <p className="text-lg font-bold text-white">{value}</p>
              {extra}
            </div>
          ))}
        </div>
        <div className="px-5 pb-4 text-xs text-[var(--text-muted)]">
          Sale amount: <span className="text-emerald-400 font-semibold">{fmtINR(my.total_sale_amount)}</span>
          {my.avg_first_call_minutes != null && <> · average time to first call {my.avg_first_call_minutes} min</>}
          {my.low_sample && <> · low sample — numbers will steady as more leads come in</>}
        </div>
      </Card>
    </div>
  );
}

export function TeamCrmPanel({ data, period }: { data: any; period: PeriodState }) {
  const navigate = useNavigate();
  if (!data?.team_status_matrix) return null;
  const statuses: string[] = data.team_status_matrix.statuses;
  const rows: { user_id: number | null; name: string; total: number; counts: Record<string, number> }[] = data.team_status_matrix.rows;
  const agents: AgentRow[] = data.agents || [];
  const leadsLink = (owner: number | null, status?: string) => {
    const qs = new URLSearchParams({ tab: owner ? "all" : "unassigned" });
    if (owner) qs.set("owner", String(owner));
    if (status) qs.set("status", status);
    return `/crm/leads?${qs.toString()}`;
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <PeriodFilter allowAll value={period.key} onChange={period.setKey} custom={period.custom} onCustom={period.setCustom} />
        <Link to="/crm" className="text-xs text-blue-400 hover:underline inline-flex items-center gap-1">Open team overview <ArrowRight size={12} /></Link>
      </div>

      {data.today && <TodayTiles today={data.today} mine={false} />}
      {data.stale_no_status > 0 && (
        <p className="text-xs text-amber-400">
          {data.stale_no_status} lead{data.stale_no_status === 1 ? "" : "s"} still have no status after 24 hours.{" "}
          <Link to="/crm/leads?tab=new" className="underline">Review</Link>
        </p>
      )}

      <Card>
        <CardHeader title="Team lead status" icon={<Activity size={15} className="text-blue-400" />} subtitle="Click a status to open those leads" />
        <div className="px-5 py-4 space-y-3">
          <StatusBar counts={data.team_status_counts} />
          <StatusChips counts={data.team_status_counts}
            onChange={(s) => navigate(`/crm/leads?tab=all${s ? `&status=${encodeURIComponent(s)}` : ""}`)} />
        </div>
      </Card>

      <Card>
        <CardHeader title="Status by telecaller" icon={<Users size={15} className="text-blue-400" />}
          subtitle="Each cell opens that telecaller's leads in that status" />
        {rows.length === 0 ? <p className="px-5 py-8 text-center text-sm text-[var(--text-muted)]">No leads in this period.</p> : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[var(--text-muted)] border-b border-[var(--border-subtle)]">
                  <th className="py-2.5 pl-5 pr-3 text-left font-semibold">Telecaller</th>
                  <th className="py-2.5 pr-3 text-right font-semibold">Total</th>
                  {statuses.map((s) => (
                    <th key={s} className="py-2.5 pr-3 text-right font-semibold whitespace-nowrap">
                      <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ backgroundColor: statusColor(s) }} />{s}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-subtle)]">
                {rows.map((r) => (
                  <tr key={`${r.user_id ?? r.name}`} className="hover:bg-[var(--bg-card-hover)]">
                    <td className="py-2.5 pl-5 pr-3 font-medium text-white whitespace-nowrap">
                      {r.user_id ? <Link to={`/crm/reports?agent=${r.user_id}`} className="hover:underline">{r.name}</Link> : <span className="text-amber-400">{r.name}</span>}
                    </td>
                    <td className="py-2.5 pr-3 text-right text-white font-semibold">
                      <Link to={leadsLink(r.user_id)} className="hover:underline">{r.total}</Link>
                    </td>
                    {statuses.map((s) => {
                      const n = r.counts[s] || 0;
                      return (
                        <td key={s} className="py-2.5 pr-3 text-right">
                          {n ? (
                            <Link to={leadsLink(r.user_id, s === NO_STATUS ? NO_STATUS : s)} className="font-semibold hover:underline" style={{ color: statusColor(s) }}>{n}</Link>
                          ) : <span className="text-[var(--text-muted)]">·</span>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <CardHeader title="Team performance" subtitle={`${data.period.start} to ${data.period.end} · click a name for the breakdown`}
          action={<Link to="/crm/reports" className="text-xs text-blue-400 hover:underline">Full report →</Link>} />
        <AgentTable rows={agents} targets={data.targets} firstCallMinutes={data.automation?.first_call_minutes ?? 5} canCoach />
      </Card>
    </div>
  );
}
