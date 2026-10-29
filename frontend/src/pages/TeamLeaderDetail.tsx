import { useMemo, useState } from "react";
import { useParams, Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, CalendarDays, Clock, TrendingUp, TrendingDown, Store as StoreIcon } from "lucide-react";
import {
  Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { api } from "@/lib/apiClient";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { localDateStr } from "@/lib/utils";

// Week colours follow the client's design: W1 blue, W2 purple, W3 teal, W4 amber.
const WEEK_COLORS = ["#3b82f6", "#a855f7", "#14b8a6", "#f59e0b"];

interface WeekRow {
  week: number; start: string; end: string; days: number; weight_pct: number; target: number;
  per_day: number; sales: number; state: "done" | "current" | "upcoming";
  achievement_pct: number | null; target_till_today: number; vs_plan_pct: number | null;
}
interface Perf {
  team_leader: { id: number; name: string };
  month: string; as_of: string; is_current_month: boolean;
  stores: {
    store_id: number; name: string; target: number; sales_to_date: number; achievement_pct: number | null;
    target_till_today: number; ahead_of_plan: number; projected_sales: number | null; projected_pct: number | null;
    today_sales: number; today_target: number; week_sales: number | null;
  }[];
  store_count: number;
  target: number; sales_to_date: number; achievement_pct: number | null;
  target_till_today: number; target_till_today_pct: number | null; ahead_of_plan: number;
  projected_sales: number | null; projected_pct: number | null;
  today: { date: string; sales: number; target: number; achievement_pct: number | null; shortfall: number };
  week: WeekRow | null;
  weeks: WeekRow[];
  days: { date: string; plan: number; sales: number | null }[];
  last_month_same_period: { until: string; sales: number; change_pct: number | null };
  last_synced_at: string | null;
  week_plan: { week: number; weight_pct: number }[];
}

function inr(n: number | null | undefined, short = false): string {
  if (n === null || n === undefined) return "—";
  const v = Math.round(n);
  if (short) {
    if (Math.abs(v) >= 10000000) return `₹${(v / 10000000).toFixed(2)}Cr`;
    if (Math.abs(v) >= 100000) return `₹${(v / 100000).toFixed(2)}L`;
    if (Math.abs(v) >= 1000) return `₹${(v / 1000).toFixed(1)}K`;
  }
  return `${v < 0 ? "-" : ""}₹${Math.abs(v).toLocaleString("en-IN")}`;
}
const pct = (p: number | null | undefined) => (p === null || p === undefined ? "—" : `${p.toFixed(1)}%`);
const dayLabel = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 ${className}`}>{children}</div>;
}
function Label({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">{children}</p>;
}
function Bar100({ value, color }: { value: number | null; color: string }) {
  return (
    <div className="h-2 rounded-full bg-[var(--bg-primary)] overflow-hidden">
      <div className="h-full rounded-full" style={{ width: `${Math.min(100, Math.max(0, value || 0))}%`, backgroundColor: color }} />
    </div>
  );
}

export default function TeamLeaderDetail() {
  const { id } = useParams();
  const now = new Date();
  const [sp] = useSearchParams();  // ?month=YYYY-MM&as_of=YYYY-MM-DD opens a specific view
  const [month, setMonth] = useState(sp.get("month") || `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`);
  const [asOf, setAsOf] = useState(sp.get("as_of") || "");

  const qs = new URLSearchParams({ month, ...(asOf ? { as_of: asOf } : {}) }).toString();
  const { data, isLoading, error } = useQuery({
    queryKey: ["tl-performance", id, month, asOf],
    queryFn: () => api.get<Perf>(`/sales-reports/team-leader/${id}/performance?${qs}`),
    placeholderData: (prev) => prev,
  });

  const monthOptions = useMemo(() => {
    const out: { value: string; label: string }[] = [];
    for (let i = 0; i < 12; i++) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      out.push({
        value: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`,
        label: d.toLocaleDateString("en-IN", { month: "long", year: "numeric" }),
      });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const [y, m] = month.split("-").map(Number);
  const monthFirst = localDateStr(new Date(y, m - 1, 1));
  const monthLast = localDateStr(new Date(y, m, 0));

  if (isLoading && !data) return <div className="p-6"><TableSkeleton /></div>;
  if (error || !data) {
    return <div className="p-6 text-sm text-rose-400">{error instanceof Error ? error.message : "Could not load this team leader"}</div>;
  }

  const ahead = data.ahead_of_plan >= 0;
  const onPace = (data.projected_pct ?? 0) >= 100;
  const hasTarget = data.target > 0;
  const lm = data.last_month_same_period;

  return (
    <ErrorBoundary>
      <div className="space-y-5">
        {/* Header */}
        <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4">
          <div className="flex items-start gap-3">
            <Link to="/team-leaders" className="p-2 rounded-xl bg-[var(--bg-card)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-white">
              <ArrowLeft size={18} />
            </Link>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">Sales performance</p>
              <h1 className="text-2xl font-bold text-white tracking-tight">{data.team_leader.name}</h1>
              <p className="text-xs text-[var(--text-muted)]">
                {data.stores.map((s) => s.name).join(", ") || "No stores assigned"} · as of {dayLabel(data.as_of)}
                {data.last_synced_at && <> · sales synced {new Date(data.last_synced_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</>}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <label className="flex items-center gap-2 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-card)] px-3 py-2 text-sm">
              <CalendarDays size={15} className="text-[var(--text-muted)]" />
              <select value={month} onChange={(e) => { setMonth(e.target.value); setAsOf(""); }}
                className="bg-transparent text-[var(--text-primary)] outline-none cursor-pointer">
                {monthOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </label>
            <label className="flex items-center gap-2 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-card)] px-3 py-2 text-sm">
              <Clock size={15} className="text-[var(--text-muted)]" />
              <span className="text-[var(--text-muted)]">As of</span>
              <input type="date" value={asOf || data.as_of} min={monthFirst} max={monthLast}
                onChange={(e) => setAsOf(e.target.value)}
                className="bg-transparent text-[var(--text-primary)] outline-none" />
            </label>
          </div>
        </div>

        {/* Weekly plan bar */}
        <div className="grid gap-1.5" style={{ gridTemplateColumns: data.weeks.map((w) => `${w.days}fr`).join(" ") }}>
          {data.weeks.map((w, i) => (
            <div key={w.week} className="min-w-0">
              <div className="h-3 rounded-full" style={{ backgroundColor: WEEK_COLORS[i], opacity: w.state === "upcoming" ? 0.45 : 1 }} />
              <p className="text-[11px] font-semibold mt-1 truncate" style={{ color: WEEK_COLORS[i] }}
                title={`Week ${w.week} · Days ${Number(w.start.slice(8))}–${Number(w.end.slice(8))} · ${w.weight_pct}% of the month`}>
                {/* Short label until there's room for the full one (it's cut off below xl). */}
                <span className="xl:hidden">W{w.week} · {w.weight_pct}%</span>
                <span className="hidden xl:inline">W{w.week} · Days {Number(w.start.slice(8))}–{Number(w.end.slice(8))} · {w.weight_pct}%</span>
              </p>
            </div>
          ))}
        </div>

        {!hasTarget && (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
            No sales target is set in MCP for these stores this month, so achievement and plan figures can't be calculated. Sales are still shown.
          </div>
        )}

        {/* Headline */}
        <Card>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 md:divide-x divide-[var(--border-subtle)]">
            <div>
              <Label>Monthly achievement</Label>
              <p className="text-4xl font-extrabold mt-1 text-blue-400">{pct(data.achievement_pct)}</p>
              <p className="text-sm text-[var(--text-secondary)] mt-1">{inr(data.sales_to_date, true)} sales / {inr(data.target, true)} target</p>
            </div>
            <div className="md:pl-6">
              <Label>Sales target till {dayLabel(data.as_of)}</Label>
              <p className="text-4xl font-extrabold mt-1 text-purple-400">{inr(data.target_till_today, true)}</p>
              <p className="text-sm text-[var(--text-secondary)] mt-1">{pct(data.target_till_today_pct)} of monthly target</p>
              {hasTarget && (
                <span className={`inline-flex items-center gap-1 mt-2 text-xs font-semibold px-2.5 py-1 rounded-lg border ${ahead ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400" : "border-rose-500/40 bg-rose-500/10 text-rose-400"}`}>
                  {ahead ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
                  {inr(Math.abs(data.ahead_of_plan))} {ahead ? "ahead of" : "behind"} plan
                </span>
              )}
            </div>
            <div className="md:pl-6">
              <Label>Projected month-end</Label>
              <p className={`text-4xl font-extrabold mt-1 ${onPace ? "text-emerald-400" : "text-amber-400"}`}>{pct(data.projected_pct)}</p>
              <p className="text-sm text-[var(--text-secondary)] mt-1">{inr(data.projected_sales, true)} forecast / {inr(data.target, true)} target</p>
              {data.projected_pct !== null && (
                <span className={`inline-flex mt-2 text-xs font-semibold px-2.5 py-1 rounded-lg border ${onPace ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400" : "border-amber-500/40 bg-amber-500/10 text-amber-400"}`}>
                  {onPace ? "On pace to exceed target" : "Below pace for target"}
                </span>
              )}
            </div>
          </div>
          {hasTarget && (
            <div className="mt-6">
              <div className="relative h-3 rounded-full bg-[var(--bg-primary)]">
                <div className="absolute inset-y-0 left-0 rounded-full bg-blue-500" style={{ width: `${Math.min(100, data.achievement_pct || 0)}%` }} />
                <div className="absolute -top-1 h-5 w-0.5 bg-purple-400" style={{ left: `${Math.min(100, data.target_till_today_pct || 0)}%` }} />
              </div>
              {/* Two label rows — "sold" above, "target till date" below — so
                  the two markers never collide however close they are. */}
              <div className="relative h-10 text-[11px] mt-1 whitespace-nowrap">
                {(data.achievement_pct || 0) > 12 && <span className="absolute left-0 top-0 text-[var(--text-muted)]">0%</span>}
                <span className="absolute top-0 -translate-x-1/2 font-semibold text-blue-400" style={{ left: `${Math.min(88, Math.max(12, data.achievement_pct || 0))}%` }}>{pct(data.achievement_pct)} sold</span>
                {(data.achievement_pct || 0) < 80 && <span className="absolute right-0 top-0 text-[var(--text-muted)]">100% target</span>}
                <span className="absolute top-5 -translate-x-1/2 text-purple-400" style={{ left: `${Math.min(80, Math.max(20, data.target_till_today_pct || 0))}%` }}>{pct(data.target_till_today_pct)} target till date</span>
              </div>
            </div>
          )}
        </Card>

        {/* Today + this week */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card>
            <Label>Today · {dayLabel(data.today.date)}</Label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-2">
              <div>
                <p className="text-4xl font-extrabold text-amber-400">{pct(data.today.achievement_pct)}</p>
                <p className="text-sm text-[var(--text-secondary)]">Daily target achieved</p>
              </div>
              <dl className="text-sm space-y-1.5">
                <div className="flex justify-between"><dt className="text-[var(--text-muted)]">Sales today</dt><dd className="text-white font-semibold">{inr(data.today.sales)}</dd></div>
                <div className="flex justify-between"><dt className="text-[var(--text-muted)]">Daily target</dt><dd className="text-white font-semibold">{inr(data.today.target)}</dd></div>
                <div className="flex justify-between"><dt className="text-[var(--text-muted)]">Shortfall</dt><dd className={data.today.shortfall ? "text-amber-400 font-semibold" : "text-emerald-400 font-semibold"}>{inr(data.today.shortfall)}</dd></div>
              </dl>
            </div>
            <div className="mt-4"><Bar100 value={data.today.achievement_pct} color="#f59e0b" /></div>
          </Card>
          <Card>
            <Label>This week{data.week ? ` · Week ${data.week.week}` : ""}</Label>
            {data.week ? (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-2">
                  <div>
                    <p className="text-4xl font-extrabold text-amber-400">{pct(data.week.achievement_pct)}</p>
                    <p className="text-sm text-[var(--text-secondary)]">Full weekly target achieved</p>
                  </div>
                  <dl className="text-sm space-y-1.5">
                    <div className="flex justify-between"><dt className="text-[var(--text-muted)]">Sales this week</dt><dd className="text-white font-semibold">{inr(data.week.sales)}</dd></div>
                    <div className="flex justify-between"><dt className="text-[var(--text-muted)]">Weekly target</dt><dd className="text-white font-semibold">{inr(data.week.target)}</dd></div>
                    <div className="flex justify-between"><dt className="text-[var(--text-muted)]">Target till today</dt><dd className="text-white font-semibold">{inr(data.week.target_till_today)}</dd></div>
                  </dl>
                </div>
                <div className="mt-4 flex items-center gap-3">
                  <div className="flex-1"><Bar100 value={data.week.vs_plan_pct} color="#f59e0b" /></div>
                  <span className="text-xs text-amber-400 whitespace-nowrap">{pct(data.week.vs_plan_pct)} of week-to-date plan</span>
                </div>
              </>
            ) : <p className="text-sm text-[var(--text-muted)] mt-2">The selected date is outside this month's weeks.</p>}
          </Card>
        </div>

        {/* Weekly allocation */}
        <Card>
          <p className="text-sm font-semibold text-white mb-3">Monthly target allocation</p>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            {data.weeks.map((w, i) => (
              <div key={w.week} className={`rounded-xl border p-4 text-center ${w.state === "current" ? "border-purple-500/60 bg-purple-500/5" : "border-[var(--border-subtle)]"}`}>
                <p className="text-sm font-semibold text-white">Week {w.week}{w.state === "current" && <span className="text-purple-400"> · Current</span>}</p>
                <p className="text-2xl font-extrabold mt-1" style={{ color: WEEK_COLORS[i] }}>{w.weight_pct}%</p>
                <p className="text-sm text-white">{inr(w.target)}</p>
                <p className="text-xs text-[var(--text-muted)]">{inr(w.per_day)} per day</p>
                <div className="mt-3 pt-3 border-t border-[var(--border-subtle)] text-xs">
                  {w.state === "upcoming" ? <span className="text-[var(--text-muted)]">Upcoming</span> : (
                    <>
                      <span className="text-[var(--text-secondary)]">Sold {inr(w.sales)}</span>
                      <span className="block font-semibold" style={{ color: (w.achievement_pct ?? 0) >= 100 ? "#10b981" : WEEK_COLORS[i] }}>
                        {pct(w.achievement_pct)} of week{w.state === "done" ? " · closed" : ""}
                      </span>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Daily chart */}
        <Card>
          <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
            <p className="text-sm font-semibold text-white">Daily sales vs daily plan</p>
            <p className="text-xs text-[var(--text-muted)]">Bars: sales · line: plan for that day (steps down each week)</p>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={data.days} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.12)" />
                <XAxis dataKey="date" tickFormatter={(d) => String(Number(String(d).slice(8)))} tick={{ fontSize: 11, fill: "var(--text-secondary)" }} />
                <YAxis tickFormatter={(v) => inr(v, true)} width={60} tick={{ fontSize: 11, fill: "var(--text-secondary)" }} />
                <Tooltip
                  contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 12, fontSize: 12 }}
                  labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }}
                  labelFormatter={(d) => dayLabel(String(d))}
                  formatter={(v: any, name: any) => [v == null ? "—" : inr(Number(v)), name]}
                />
                <Bar dataKey="sales" name="Sales" fill="#3b82f6" radius={[3, 3, 0, 0]} isAnimationActive={false} />
                <Line dataKey="plan" name="Plan" type="stepAfter" stroke="#a855f7" strokeWidth={2} dot={false} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Card>

        {/* Stores + comparison */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          <Card className="xl:col-span-2">
            <p className="text-sm font-semibold text-white mb-3 flex items-center gap-2"><StoreIcon size={15} />Store breakdown</p>
            {data.stores.length === 0 ? <p className="text-sm text-[var(--text-muted)]">No stores assigned.</p> : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-[var(--text-muted)] border-b border-[var(--border-subtle)] text-left">
                      <th className="py-2 pr-3 font-semibold">Store</th>
                      <th className="py-2 pr-3 font-semibold text-right">Target</th>
                      <th className="py-2 pr-3 font-semibold text-right">Sold</th>
                      <th className="py-2 pr-3 font-semibold">Achievement</th>
                      <th className="py-2 pr-3 font-semibold text-right">vs plan</th>
                      <th className="py-2 pr-3 font-semibold text-right">Projected</th>
                      <th className="py-2 font-semibold text-right">Today</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border-subtle)]">
                    {data.stores.map((s) => (
                      <tr key={s.store_id}>
                        <td className="py-2.5 pr-3 text-white font-medium">{s.name}</td>
                        <td className="py-2.5 pr-3 text-right text-[var(--text-secondary)]">{s.target ? inr(s.target, true) : "No target"}</td>
                        <td className="py-2.5 pr-3 text-right text-white">{inr(s.sales_to_date, true)}</td>
                        <td className="py-2.5 pr-3 min-w-[120px]">
                          <div className="flex items-center gap-2"><div className="flex-1"><Bar100 value={s.achievement_pct} color="#3b82f6" /></div><span className="w-12 text-right">{pct(s.achievement_pct)}</span></div>
                        </td>
                        <td className={`py-2.5 pr-3 text-right ${s.target ? (s.ahead_of_plan >= 0 ? "text-emerald-400" : "text-rose-400") : "text-[var(--text-muted)]"}`}>
                          {s.target ? `${s.ahead_of_plan >= 0 ? "+" : "-"}${inr(Math.abs(s.ahead_of_plan), true)}` : "—"}
                        </td>
                        <td className="py-2.5 pr-3 text-right">{pct(s.projected_pct)}</td>
                        <td className="py-2.5 text-right text-[var(--text-secondary)]">{inr(s.today_sales, true)}{s.today_target ? ` / ${inr(s.today_target, true)}` : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
          <Card>
            <p className="text-sm font-semibold text-white mb-3">Compared with last month</p>
            <p className="text-xs text-[var(--text-muted)]">Same days: 1st to {dayLabel(lm.until)}</p>
            <div className="mt-3 space-y-2 text-sm">
              <div className="flex justify-between"><span className="text-[var(--text-muted)]">This month</span><span className="text-white font-semibold">{inr(data.sales_to_date)}</span></div>
              <div className="flex justify-between"><span className="text-[var(--text-muted)]">Last month</span><span className="text-white font-semibold">{inr(lm.sales)}</span></div>
              <div className="flex justify-between pt-2 border-t border-[var(--border-subtle)]">
                <span className="text-[var(--text-muted)]">Change</span>
                <span className={`font-semibold ${(lm.change_pct ?? 0) >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                  {lm.change_pct === null ? "—" : `${lm.change_pct >= 0 ? "+" : ""}${lm.change_pct.toFixed(1)}%`}
                </span>
              </div>
            </div>
            <p className="text-[11px] text-[var(--text-muted)] mt-4">
              Plan: {data.week_plan.map((w) => `W${w.week} ${w.weight_pct}%`).join(" · ")} of the monthly target, spread evenly over each week's days. Projection assumes the same pace against this plan.
            </p>
          </Card>
        </div>

        {id && <TelecallingPerformance tlId={id} />}
      </div>
    </ErrorBoundary>
  );
}

// ── Telecalling performance ─────────────────────────────────────────

interface SourceCount { leads: number; attended: number; not_attended: number; calls: number }
interface TcRow {
  user_id: number | null; name: string; role: string; store: string | null; available: boolean | null;
  leads: number; attended: number; not_attended: number; attended_pct: number | null; calls: number; converted: number;
  by_source: Record<string, SourceCount>;
}
interface Telecalling {
  start: string; end: string; stores: string[];
  sources: { key: string; label: string }[];
  telecallers: TcRow[];
  total: Omit<TcRow, "user_id" | "name" | "role" | "store" | "available">;
}

const PERIODS = ["today", "yesterday", "7d", "month", "last_month", "custom"] as const;
type Period = typeof PERIODS[number];
const PERIOD_LABEL: Record<Period, string> = {
  today: "Today", yesterday: "Yesterday", "7d": "Last 7 days", month: "This month", last_month: "Last month", custom: "Custom",
};
const SOURCE_COLOR: Record<string, string> = { website: "#10b981", facebook: "#3b82f6", instagram: "#ec4899", meta_sheet: "#a855f7" };
const attColor = (p: number | null) => (p == null ? "var(--text-muted)" : p >= 60 ? "#10b981" : p >= 30 ? "#f59e0b" : "#ef4444");

function periodRange(p: Period, custom: { start: string; end: string }): { start: string; end: string } {
  const today = new Date();
  const d = (offset: number) => localDateStr(new Date(today.getFullYear(), today.getMonth(), today.getDate() - offset));
  switch (p) {
    case "today": return { start: d(0), end: d(0) };
    case "yesterday": return { start: d(1), end: d(1) };
    case "7d": return { start: d(6), end: d(0) };
    case "month": return { start: localDateStr(new Date(today.getFullYear(), today.getMonth(), 1)), end: d(0) };
    case "last_month": return {
      start: localDateStr(new Date(today.getFullYear(), today.getMonth() - 1, 1)),
      end: localDateStr(new Date(today.getFullYear(), today.getMonth(), 0)),
    };
    default: return custom;
  }
}

/** The team leader's telecallers for a period: leads that came in, how many
 * were attended, calls made, and the same per lead source. */
function TelecallingPerformance({ tlId }: { tlId: string }) {
  const [period, setPeriod] = useState<Period>("month");
  const [custom, setCustom] = useState(() => periodRange("7d", { start: "", end: "" }));
  const range = periodRange(period, custom);
  const ready = !!range.start && !!range.end && range.start <= range.end;
  const { data, isLoading, error, isFetching } = useQuery({
    queryKey: ["tl-telecalling", tlId, range.start, range.end],
    queryFn: () => api.get<Telecalling>(`/sales-reports/team-leader/${tlId}/telecalling?start=${range.start}&end=${range.end}`),
    enabled: ready,
    placeholderData: (prev) => prev,
  });
  const fmt = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  const inputCls = "rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-primary)] px-2.5 py-1.5 text-xs text-[var(--text-primary)]";

  return (
    <Card>
      <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-3 mb-4">
        <div>
          <p className="text-sm font-semibold text-white">Telecalling performance</p>
          <p className="text-xs text-[var(--text-muted)]">
            Leads that came in for this team, how many were attended, and calls made
            {ready && <> · {fmt(range.start)}{range.end !== range.start ? ` – ${fmt(range.end)}` : ""}</>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {PERIODS.map((p) => (
            <button key={p} type="button" onClick={() => setPeriod(p)} aria-pressed={period === p}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold border cursor-pointer ${period === p
                ? "bg-[var(--accent-blue)] border-[var(--accent-blue)] text-white"
                : "border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-white"}`}>
              {PERIOD_LABEL[p]}
            </button>
          ))}
          {period === "custom" && (
            <span className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
              <input id="tc-start" type="date" aria-label="From" className={inputCls} value={custom.start} max={custom.end || undefined}
                onChange={(e) => setCustom((c) => ({ ...c, start: e.target.value }))} />
              to
              <input id="tc-end" type="date" aria-label="To" className={inputCls} value={custom.end} min={custom.start || undefined}
                onChange={(e) => setCustom((c) => ({ ...c, end: e.target.value }))} />
            </span>
          )}
        </div>
      </div>

      {!ready ? <p className="text-sm text-[var(--text-muted)]">Pick a start and end date.</p>
        : isLoading && !data ? <TableSkeleton />
        : error || !data ? <p className="text-sm text-rose-400">{error instanceof Error ? error.message : "Could not load telecalling"}</p>
        : (
          <div className={`space-y-5 ${isFetching ? "opacity-70 transition-opacity" : ""}`}>
            {/* Team totals */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
              {([
                ["Leads came", data.total.leads, "var(--text-primary)"],
                ["Attended", data.total.attended, "#10b981"],
                ["Not attended", data.total.not_attended, data.total.not_attended ? "#ef4444" : "var(--text-primary)"],
                ["Attended %", data.total.attended_pct == null ? "—" : `${data.total.attended_pct}%`, attColor(data.total.attended_pct)],
                ["Calls made", data.total.calls, "#3b82f6"],
                ["Sales", data.total.converted, "#a855f7"],
              ] as [string, string | number, string][]).map(([l, v, c]) => (
                <div key={l} className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-3">
                  <Label>{l}</Label>
                  <p className="text-2xl font-extrabold mt-1 tabular-nums" style={{ color: c }}>{v}</p>
                </div>
              ))}
            </div>

            {/* By source */}
            {data.sources.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
                {data.sources.map((s) => {
                  const b = data.total.by_source[s.key] || { leads: 0, attended: 0, not_attended: 0, calls: 0 };
                  const p = b.leads ? Math.round((b.attended / b.leads) * 100) : null;
                  return (
                    <div key={s.key} className="rounded-xl border border-[var(--border-subtle)] p-3">
                      <p className="text-xs font-bold" style={{ color: SOURCE_COLOR[s.key] || "var(--text-secondary)" }}>{s.label} leads</p>
                      <p className="text-xl font-extrabold text-white mt-0.5 tabular-nums">{b.leads}</p>
                      <div className="mt-2"><Bar100 value={p} color={SOURCE_COLOR[s.key] || "#64748b"} /></div>
                      <p className="text-[11px] text-[var(--text-secondary)] mt-1.5 tabular-nums">
                        <span className="text-emerald-400 font-semibold">{b.attended} attended</span>
                        {" · "}<span className={b.not_attended ? "text-rose-400" : ""}>{b.not_attended} not</span>{" · "}{b.calls} calls
                      </p>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Per telecaller */}
            {data.telecallers.length === 0 ? <p className="text-sm text-[var(--text-muted)]">No telecallers on this team.</p> : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-[var(--text-muted)] border-b border-[var(--border-subtle)] text-left">
                      <th className="py-2 pr-3 font-semibold">Telecaller</th>
                      <th className="py-2 pr-3 font-semibold text-right">Leads</th>
                      <th className="py-2 pr-3 font-semibold text-right">Attended</th>
                      <th className="py-2 pr-3 font-semibold text-right">Not attended</th>
                      <th className="py-2 pr-3 font-semibold min-w-[130px]">Attended %</th>
                      <th className="py-2 pr-3 font-semibold text-right">Calls made</th>
                      <th className="py-2 pr-3 font-semibold text-right">Sales</th>
                      {data.sources.map((s) => (
                        <th key={s.key} className="py-2 pr-3 font-semibold text-right whitespace-nowrap" title="Leads · attended · calls">
                          <span style={{ color: SOURCE_COLOR[s.key] }}>{s.label}</span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border-subtle)]">
                    {data.telecallers.map((r) => (
                      <tr key={r.user_id ?? "none"} className={r.role !== "Telecaller" ? "text-[var(--text-secondary)]" : ""}>
                        <td className="py-2.5 pr-3">
                          <p className="text-white font-medium">{r.name}
                            {r.available === false && <span className="ml-1.5 text-[10px] text-amber-400">Away</span>}</p>
                          <p className="text-[11px] text-[var(--text-muted)]">
                            {r.role === "Telecaller" ? r.store || "No store set" : r.role === "Team leader" ? "Team leader (own leads)" : "Not given to anyone"}
                          </p>
                        </td>
                        <td className="py-2.5 pr-3 text-right tabular-nums text-white">{r.leads}</td>
                        <td className="py-2.5 pr-3 text-right tabular-nums text-emerald-400">{r.attended}</td>
                        <td className={`py-2.5 pr-3 text-right tabular-nums ${r.not_attended ? "text-rose-400 font-semibold" : ""}`}>{r.not_attended}</td>
                        <td className="py-2.5 pr-3">
                          <div className="flex items-center gap-2">
                            <div className="flex-1"><Bar100 value={r.attended_pct} color={attColor(r.attended_pct)} /></div>
                            <span className="w-10 text-right tabular-nums" style={{ color: attColor(r.attended_pct) }}>
                              {r.attended_pct == null ? "—" : `${r.attended_pct}%`}
                            </span>
                          </div>
                        </td>
                        <td className="py-2.5 pr-3 text-right tabular-nums text-blue-400">{r.calls}</td>
                        <td className="py-2.5 pr-3 text-right tabular-nums text-purple-400">{r.converted}</td>
                        {data.sources.map((s) => {
                          const b = r.by_source[s.key];
                          return (
                            <td key={s.key} className="py-2.5 pr-3 text-right tabular-nums whitespace-nowrap"
                              title={b ? `${b.leads} leads · ${b.attended} attended · ${b.not_attended} not · ${b.calls} calls` : ""}>
                              {b && (b.leads || b.calls) ? (
                                <>
                                  <span className="text-white">{b.leads}</span>
                                  <span className="block text-[10px] text-[var(--text-muted)]">{b.attended} att · {b.calls} calls</span>
                                </>
                              ) : <span className="text-[var(--text-muted)]">—</span>}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="text-[11px] text-[var(--text-muted)]">
              A lead counts in the period it came in. Attended = called or given a status (in the app or the Google Sheet).
              Calls made = leads called or updated in the period, including follow-ups of older leads. Green 60%+, amber 30–59%, red below 30%.
            </p>
          </div>
        )}
    </Card>
  );
}
