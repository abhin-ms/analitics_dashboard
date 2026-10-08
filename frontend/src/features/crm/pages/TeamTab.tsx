import { useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronRight, Users } from "lucide-react";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { TeamPerson, useTeamOverview } from "../api";
import { PeriodFilter, PeriodKey, StatusBar, periodRange } from "../components/shared";
import { Card, Empty, Pill } from "../components/ui";

const leadsOf = (id: number) => `/leads?view=leads&list=all&owner=${id}`;

function PersonRow({ p, indent, label }: { p: TeamPerson; indent?: boolean; label?: string }) {
  return (
    <tr className="hover:bg-[var(--bg-card-hover)] align-top">
      <td className={`py-2.5 pr-3 ${indent ? "pl-10" : "pl-5"}`}>
        <Link to={leadsOf(p.id)} className="text-white hover:underline">{p.name}</Link>
        {label && <span className="ml-1.5"><Pill label={label} color="#64748b" /></span>}
        {!p.available && <span className="ml-1.5"><Pill label="Away" color="#f59e0b" /></span>}
        <p className="text-[11px] text-[var(--text-muted)]">{p.sheets.join(", ") || "no city"}</p>
      </td>
      <td className="py-2.5 pr-3 w-40"><StatusBar counts={p.status_counts} /></td>
      <td className="py-2.5 pr-3 text-right text-white font-semibold">{p.total}</td>
      <td className="py-2.5 pr-3 text-right">{p.open_leads}</td>
      <td className="py-2.5 pr-3 text-right">{p.connected_pct}%</td>
      <td className="py-2.5 pr-3 text-right text-emerald-400">{p.converted} <span className="text-[var(--text-muted)]">· {p.conversion_pct}%</span></td>
      <td className={`py-2.5 pr-3 text-right ${p.overdue ? "text-rose-400 font-semibold" : ""}`}>{p.overdue}</td>
      <td className="py-2.5 pr-5 text-right">{p.upcoming_appointments}</td>
    </tr>
  );
}

const HEAD = ["", "Status mix", "Leads", "Open", "Connected", "Converted", "Overdue", "Appointments"];

export default function TeamTab() {
  const [periodKey, setPeriodKey] = useState<PeriodKey>("all");
  const [custom, setCustom] = useState(() => periodRange("month"));
  const range = periodRange(periodKey, custom);
  const { data, isLoading, error } = useTeamOverview(range.start, range.end);
  const [closed, setClosed] = useState<Set<number>>(new Set());

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <p className="text-xs text-[var(--text-muted)]">Team leaders with the telecallers assigned to them. Click a name to open their leads.</p>
        <PeriodFilter allowAll value={periodKey} onChange={setPeriodKey} custom={custom} onCustom={setCustom} />
      </div>
      {isLoading ? <TableSkeleton /> : error ? (
        <p className="text-sm text-rose-400">{error instanceof Error ? error.message : "Could not load"}</p>
      ) : !data || (data.teams.length === 0 && data.unattached_telecallers.length === 0) ? (
        <Card><Empty>No team leaders or telecallers are assigned to city sheets yet.</Empty></Card>
      ) : (
        <>
          {data.teams.map((t) => {
            const open = !closed.has(t.id);
            return (
              <Card key={t.id}>
                <button className="w-full flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-4 text-left cursor-pointer"
                  onClick={() => { const n = new Set(closed); if (open) n.add(t.id); else n.delete(t.id); setClosed(n); }}>
                  {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  <span className="text-sm font-semibold text-white flex items-center gap-2"><Users size={15} className="text-blue-400" />{t.name}</span>
                  <span className="text-xs text-[var(--text-muted)]">{t.sheets.join(", ") || "no city"} · {t.telecallers.length} telecaller{t.telecallers.length === 1 ? "" : "s"}</span>
                  <span className="ml-auto flex flex-wrap gap-3 text-xs text-[var(--text-secondary)]">
                    <span>{t.totals.total} leads</span>
                    <span className="text-emerald-400">{t.totals.converted} converted · {t.totals.conversion_pct}%</span>
                    {t.totals.overdue > 0 && <span className="text-rose-400">{t.totals.overdue} overdue</span>}
                    {t.totals.unassigned > 0 && <span className="text-amber-400">{t.totals.unassigned} unassigned</span>}
                  </span>
                </button>
                {open && (
                  <div className="overflow-x-auto border-t border-[var(--border-subtle)]">
                    <table className="w-full text-xs">
                      <thead><tr className="text-[var(--text-muted)] border-b border-[var(--border-subtle)]">
                        {HEAD.map((h, i) => <th key={i} className={`py-2 font-semibold ${i === 0 ? "pl-5 text-left" : i === 1 ? "pr-3 text-left" : "pr-3 text-right"} ${i === HEAD.length - 1 ? "pr-5" : ""}`}>{h}</th>)}
                      </tr></thead>
                      <tbody className="divide-y divide-[var(--border-subtle)] text-[var(--text-secondary)]">
                        {t.own.total > 0 && <PersonRow p={t.own} label="Team leader" />}
                        {t.telecallers.map((p) => <PersonRow key={p.id} p={p} indent />)}
                        {t.telecallers.length === 0 && (
                          <tr><td colSpan={HEAD.length} className="px-5 py-4 text-[var(--text-muted)]">No telecallers assigned yet — add them in Sheet Assignments or Add Telecaller.</td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            );
          })}
          {data.unattached_telecallers.length > 0 && (
            <Card>
              <p className="px-5 py-4 text-sm font-semibold text-white">Telecallers without a team leader</p>
              <div className="overflow-x-auto border-t border-[var(--border-subtle)]">
                <table className="w-full text-xs"><tbody className="divide-y divide-[var(--border-subtle)] text-[var(--text-secondary)]">
                  {data.unattached_telecallers.map((p) => <PersonRow key={p.id} p={p} />)}
                </tbody></table>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
