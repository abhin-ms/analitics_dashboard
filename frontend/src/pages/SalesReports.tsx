import { useState, useCallback, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/apiClient";
import { localDateStr } from "@/lib/utils";
import { formatByCountry } from "@/lib/formatMoney";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { BarChart3, Calendar, CalendarDays, CalendarRange, AlertTriangle, Users, Store, MapPin, Layers, Trophy } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

type Granularity = "day" | "week" | "month";
type GroupBy = "none" | "team_leader" | "branch" | "region";
type RangePreset = "today" | "7day" | "month" | "custom";

const RANGE_OPTIONS: { key: RangePreset; label: string }[] = [
  { key: "today", label: "Today (1 Day)" },
  { key: "7day", label: "Last 7 Days" },
  { key: "month", label: "This Month" },
  { key: "custom", label: "Custom Range" },
];

// Resolves a range preset to explicit start/end dates. Custom range is
// handled by the caller once both date inputs are filled in.
function resolveRange(preset: RangePreset): { start: string; end: string } | null {
  const today = new Date();
  if (preset === "today") {
    const d = localDateStr(today);
    return { start: d, end: d };
  }
  if (preset === "7day") {
    const from = new Date(today);
    from.setDate(from.getDate() - 6);
    return { start: localDateStr(from), end: localDateStr(today) };
  }
  if (preset === "month") {
    const start = new Date(today.getFullYear(), today.getMonth(), 1);
    const end = new Date(today.getFullYear(), today.getMonth() + 1, 0);
    return { start: localDateStr(start), end: localDateStr(end) };
  }
  return null;
}

const GRANULARITY_OPTIONS: { key: Granularity; label: string; icon: any }[] = [
  { key: "day", label: "Daily", icon: Calendar },
  { key: "week", label: "Weekly", icon: CalendarDays },
  { key: "month", label: "Monthly", icon: CalendarRange },
];

const GROUP_BY_OPTIONS: { key: GroupBy; label: string; icon: any }[] = [
  { key: "none", label: "All Together", icon: Layers },
  { key: "team_leader", label: "Team Leader Wise", icon: Users },
  { key: "branch", label: "Branch Wise", icon: Store },
  { key: "region", label: "Region Wise", icon: MapPin },
];

export default function SalesReports() {
  const [rangePreset, setRangePreset] = useState<RangePreset>("month");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [granularity, setGranularity] = useState<Granularity>("month");
  const [groupBy, setGroupBy] = useState<GroupBy>("none");
  const [country, setCountry] = useState("");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const requestSeq = useRef(0);

  const selectRange = (preset: RangePreset) => {
    setRangePreset(preset);
    if (preset === "today") setGranularity("day");
    else if (preset === "7day") setGranularity("day");
    else if (preset === "month") setGranularity("month");
  };

  const effectiveRange = rangePreset === "custom"
    ? (customStart && customEnd ? { start: customStart, end: customEnd } : null)
    : resolveRange(rangePreset);

  const fetchReport = useCallback(async () => {
    if (rangePreset === "custom" && !effectiveRange) return;
    const seq = ++requestSeq.current;
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ granularity, group_by: groupBy });
      if (country) params.set("country", country);
      if (effectiveRange) {
        params.set("start", effectiveRange.start);
        params.set("end", effectiveRange.end);
      }
      const res = await api.fetchRaw(`/sales-reports?${params.toString()}`);
      if (seq !== requestSeq.current) return; // a newer request already superseded this one
      if (res.ok) {
        setData(await res.json());
      } else {
        setError("Failed to load sales report");
      }
    } catch {
      if (seq === requestSeq.current) setError("Failed to load sales report");
    }
    if (seq === requestSeq.current) setLoading(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [granularity, groupBy, country, rangePreset, customStart, customEnd]);

  useEffect(() => { fetchReport(); }, [fetchReport]);

  const breakdown = data?.breakdown || [];
  const trend = data?.trend || [];
  const needsReview = data?.needs_review || [];
  const topBranch = data?.top_branch || null;
  // When a specific country is filtered, every figure on this page belongs
  // to it — show that currency. With no filter (blended across countries)
  // fall back to the company's default reporting currency (INR) for the
  // combined totals/trend, same convention as the main Dashboard's KPIs.
  const displayCountry = country || "India";
  // Each branch/region row is genuinely single-country, so its own currency
  // is reliable — but a "none"/"team_leader" row can blend multiple
  // countries together, so its `country` field isn't trustworthy there.
  const rowCountry = (row: any) =>
    (groupBy === "branch" || groupBy === "region") && row.country ? row.country : displayCountry;

  return (
    <ErrorBoundary>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <BarChart3 size={24} />
            Sales Reports
          </h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            {data ? `${data.start} to ${data.end}` : "Combined MCP + Sheets sales, day / week / month, by team leader, branch, or region"}
          </p>
        </div>

        {/* Date range */}
        <div className="flex flex-wrap items-center gap-2">
          {RANGE_OPTIONS.map((opt) => {
            const active = rangePreset === opt.key;
            return (
              <button
                key={opt.key}
                onClick={() => selectRange(opt.key)}
                className={`text-xs px-3.5 py-2 rounded-xl border transition-colors ${
                  active
                    ? "bg-emerald-500/20 border-emerald-500/40 text-emerald-300"
                    : "bg-[var(--bg-card)] border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-white/5"
                }`}
              >
                {opt.label}
              </button>
            );
          })}
          {rangePreset === "custom" && (
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={customStart}
                onChange={(e) => setCustomStart(e.target.value)}
                className="px-3 py-2 rounded-xl bg-[var(--bg-card)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none"
              />
              <span className="text-xs text-[var(--text-muted)]">to</span>
              <input
                type="date"
                value={customEnd}
                onChange={(e) => setCustomEnd(e.target.value)}
                className="px-3 py-2 rounded-xl bg-[var(--bg-card)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none"
              />
            </div>
          )}
        </div>

        {/* Granularity toggle */}
        <div className="flex flex-wrap gap-2">
          {GRANULARITY_OPTIONS.map((opt) => {
            const Icon = opt.icon;
            const active = granularity === opt.key;
            return (
              <button
                key={opt.key}
                onClick={() => setGranularity(opt.key)}
                className={`inline-flex items-center gap-1.5 text-xs px-3.5 py-2 rounded-xl border transition-colors ${
                  active
                    ? "bg-[var(--accent-blue)] border-[var(--accent-blue)] text-white"
                    : "bg-[var(--bg-card)] border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-white/5"
                }`}
              >
                <Icon size={14} /> {opt.label}
              </button>
            );
          })}
        </div>

        {/* Group-by toggle */}
        <div className="flex flex-wrap gap-2">
          {GROUP_BY_OPTIONS.map((opt) => {
            const Icon = opt.icon;
            const active = groupBy === opt.key;
            return (
              <button
                key={opt.key}
                onClick={() => setGroupBy(opt.key)}
                className={`inline-flex items-center gap-1.5 text-xs px-3.5 py-2 rounded-xl border transition-colors ${
                  active
                    ? "bg-purple-500/20 border-purple-500/40 text-purple-300"
                    : "bg-[var(--bg-card)] border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-white/5"
                }`}
              >
                <Icon size={14} /> {opt.label}
              </button>
            );
          })}
          <select
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            className="px-3.5 py-2 rounded-xl bg-[var(--bg-card)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none"
          >
            <option value="">All Countries</option>
            {["India", "Oman", "Pakistan", "UAE", "Malaysia", "UK", "Bahrain", "Qatar"].map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>

        {error && (
          <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">{error}</div>
        )}

        {needsReview.length > 0 && (
          <div className="flex items-center justify-between gap-3 p-4 rounded-2xl bg-amber-500/10 border border-amber-500/25 text-amber-300 text-sm">
            <span className="flex items-center gap-2">
              <AlertTriangle size={16} />
              {needsReview.length} branch{needsReview.length > 1 ? "es" : ""} synced from MCP need a team leader assignment (excluded from totals below).
            </span>
            <Link
              to="/settings/branch-assignment"
              className="shrink-0 px-3 py-1.5 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-xs font-semibold"
            >
              Review Branches
            </Link>
          </div>
        )}

        {/* Top branch for the selected period */}
        {topBranch && (
          <div className="flex items-center gap-4 p-5 rounded-2xl border border-amber-500/30 bg-gradient-to-r from-amber-500/10 to-transparent">
            <div className="h-12 w-12 rounded-xl bg-amber-500/20 border border-amber-500/30 flex items-center justify-center shrink-0">
              <Trophy size={24} className="text-amber-400" />
            </div>
            <div className="flex-1">
              <p className="text-[10px] uppercase tracking-wider text-amber-300/80 font-semibold">
                Top Branch — {data.start === data.end ? data.start : `${data.start} to ${data.end}`}
              </p>
              <p className="text-lg font-extrabold text-white">{topBranch.name}</p>
            </div>
            <div className="text-right">
              <p className="text-xl font-extrabold text-white">{formatByCountry(topBranch.revenue, topBranch.country || displayCountry)}</p>
              <p className="text-xs text-[var(--text-muted)]">
                {topBranch.target > 0 ? `${topBranch.achievement_pct}% of target` : "revenue"}
              </p>
            </div>
          </div>
        )}

        {/* Summary KPIs */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
          {[
            { label: "Total Revenue", value: data ? formatByCountry(data.total_revenue, displayCountry) : "—", color: "#3b82f6" },
            { label: "Total Target", value: data ? formatByCountry(data.total_target, displayCountry) : "—", color: "#10b981" },
            { label: "Achievement", value: data ? `${data.achievement_pct}%` : "—", color: (data?.achievement_pct || 0) >= 50 ? "#10b981" : "#f59e0b" },
            { label: "Walk-ins", value: data ? data.total_walkins.toLocaleString() : "—", color: "#a855f7" },
            { label: "Conversions", value: data ? data.total_conversions.toLocaleString() : "—", color: "#ec4899" },
          ].map((k, i) => (
            <div key={i} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 relative overflow-hidden">
              <div className="absolute top-0 left-0 right-0 h-0.5" style={{ background: k.color }} />
              <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] mb-1">{k.label}</p>
              <p className="text-xl font-extrabold text-white">{k.value}</p>
            </div>
          ))}
        </div>

        {/* Trend chart */}
        {trend.length > 1 && (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5">
            <h3 className="text-sm font-bold text-white tracking-tight mb-3">Revenue Trend</h3>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={trend}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="period" tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
                <YAxis tick={{ fontSize: 10, fill: "var(--text-secondary)" }} tickFormatter={(v) => formatByCountry(v, displayCountry)} width={70} />
                <Tooltip
                  contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 8 }}
                  labelStyle={{ color: "var(--text-primary)" }}
                  itemStyle={{ color: "var(--text-primary)" }}
                  formatter={(v: any) => formatByCountry(Number(v), displayCountry)}
                />
                <Line type="monotone" dataKey="revenue" stroke="#3b82f6" strokeWidth={2.5} dot={{ r: 3, fill: "#3b82f6" }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Breakdown table */}
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 sm:p-6 overflow-hidden">
          <h3 className="text-sm font-bold text-white tracking-tight mb-4">
            {groupBy === "none" ? "All Together" : GROUP_BY_OPTIONS.find((o) => o.key === groupBy)?.label}
          </h3>
          {loading ? (
            <TableSkeleton rows={6} cols={6} />
          ) : breakdown.length === 0 ? (
            <div className="text-center py-12 text-[var(--text-muted)]">No data for this filter</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left border-collapse">
                <thead>
                  <tr className="text-[var(--text-muted)] text-xs uppercase tracking-wider border-b border-[var(--border-subtle)]">
                    <th className="py-3 px-4 font-semibold">{groupBy === "none" ? "Total" : groupBy === "team_leader" ? "Team Leader" : groupBy === "region" ? "Region" : "Branch"}</th>
                    <th className="py-3 px-4 font-semibold text-right">Branches</th>
                    <th className="py-3 px-4 font-semibold text-right">Revenue</th>
                    <th className="py-3 px-4 font-semibold text-right">Target</th>
                    <th className="py-3 px-4 font-semibold text-right">Achievement</th>
                    <th className="py-3 px-4 font-semibold text-right">Walk-ins</th>
                    <th className="py-3 px-4 font-semibold text-right">Conversions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border-subtle)]">
                  {breakdown.map((row: any, i: number) => (
                    <tr key={i} className="hover:bg-[var(--bg-card-hover)] transition-colors">
                      <td className="py-3.5 px-4 font-semibold text-white">
                        <span className="inline-flex items-center gap-1.5">
                          {groupBy === "branch" && i === 0 && <Trophy size={13} className="text-amber-400" />}
                          {row.key}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-right text-[var(--text-secondary)]">{row.store_count}</td>
                      <td className="py-3.5 px-4 text-right font-semibold text-white">{formatByCountry(row.revenue, rowCountry(row))}</td>
                      <td className="py-3.5 px-4 text-right text-[var(--text-secondary)]">{formatByCountry(row.target, rowCountry(row))}</td>
                      <td className="py-3.5 px-4 text-right">
                        <span className={`font-bold ${row.achievement_pct >= 65 ? "text-emerald-400" : row.achievement_pct >= 35 ? "text-amber-400" : "text-rose-400"}`}>
                          {row.achievement_pct}%
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-right text-[var(--text-secondary)]">{row.walkins}</td>
                      <td className="py-3.5 px-4 text-right text-[var(--text-secondary)]">{row.conversions}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </ErrorBoundary>
  );
}
