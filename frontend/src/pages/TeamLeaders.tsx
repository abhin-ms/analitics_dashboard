import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "@/lib/apiClient";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { AISummary } from "@/components/dashboard/AISummary";
import { ArrowRight, Filter, Store, TrendingUp } from "lucide-react";
import { TableSkeleton } from "@/components/shared/Skeleton";

import { useSocketRefresh } from "../hooks/useSocketRefresh";

function fmtINR(n: number) {
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(2)} Cr`;
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`;
  if (n >= 1000) return `₹${(n / 1000).toFixed(1)}K`;
  return `₹${n.toLocaleString("en-IN")}`;
}

function localDateStr(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function TeamLeaders() {
  const [searchParams] = useSearchParams();
  const tab = searchParams.get("tab") || "main";
  useSocketRefresh(["team-leaders"]);

  const [users, setUsers] = useState<any[]>([]);
  const [stores, setStores] = useState<any[]>([]);
  const [report, setReport] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const [period, setPeriod] = useState<"1day" | "7day" | "month" | "custom">("month");
  const [customRange, setCustomRange] = useState<{ from: string; to: string } | null>(null);
  const [showRangeFilter, setShowRangeFilter] = useState(false);
  const [draftRange, setDraftRange] = useState({ from: "", to: "" });
  const rangeFilterRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!showRangeFilter) return;
    function handleClickOutside(e: MouseEvent) {
      if (rangeFilterRef.current && !rangeFilterRef.current.contains(e.target as Node)) {
        setShowRangeFilter(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showRangeFilter]);

  const effectiveRange = useMemo(() => {
    const now = new Date();
    const to = localDateStr(now);
    if (period === "custom" && customRange) return customRange;
    if (period === "1day") return { from: to, to };
    if (period === "7day") {
      const from = new Date(now);
      from.setDate(from.getDate() - 6);
      return { from: localDateStr(from), to };
    }
    // "month": calendar month to date (1st of the current month through
    // today), not a rolling 30 days — matches how "monthly" is understood
    // everywhere else (MCP's own target sheets, International Sales).
    const from = new Date(now.getFullYear(), now.getMonth(), 1);
    return { from: localDateStr(from), to };
  }, [period, customRange]);

  const fetchRoster = useCallback(async () => {
    try {
      const [usersRes, storesRes] = await Promise.all([
        api.fetchRaw("/users/"),
        api.fetchRaw("/stores/"),
      ]);
      if (usersRes.ok) setUsers(await usersRes.json());
      if (storesRes.ok) setStores(await storesRes.json());
    } catch {}
  }, []);

  const fetchReport = useCallback(async () => {
    setLoading(true);
    try {
      // Team leader management (walk-ins, leads, calls) is an India-only
      // process in this system — MCP-tracked countries don't have Team
      // Leader accounts or Sheets-based funnel data, so this page (like
      // Operations/Performance) is scoped to India rather than blending
      // currencies across countries.
      const params = `group_by=team_leader&granularity=day&country=India&start=${effectiveRange.from}&end=${effectiveRange.to}`;
      const res = await api.fetchRaw(`/sales-reports?${params}`);
      if (res.ok) setReport(await res.json());
    } catch {}
    setLoading(false);
  }, [effectiveRange]);

  useEffect(() => { fetchRoster(); }, [fetchRoster]);
  useEffect(() => { fetchReport(); }, [fetchReport]);

  // The actual roster of Team Leader accounts (from Users, filtered by
  // role) joined with their currently assigned stores (Store.team_leader_id)
  // and this period's real performance (from the MCP-backed sales report) —
  // NOT derived from historical Sheets submissions. A Team Leader who was
  // just created and assigned stores that haven't logged a manual Sheets
  // submission yet (increasingly common now that MCP drives most revenue)
  // used to never appear here at all, because the old version of this page
  // built its entire list by scanning past submission rows instead of the
  // real Users/Stores tables.
  const tls = useMemo(() => {
    const perfByName = new Map<string, any>();
    for (const r of report?.breakdown || []) perfByName.set(r.key, r);

    const indiaStores = stores.filter((s: any) => s.country === "India" && s.is_active);
    const storesByTl = new Map<number, any[]>();
    for (const s of indiaStores) {
      if (!s.team_leader_id) continue;
      if (!storesByTl.has(s.team_leader_id)) storesByTl.set(s.team_leader_id, []);
      storesByTl.get(s.team_leader_id)!.push(s);
    }

    // People without access to the user list (e.g. a team leader or regional
    // manager) get the leaders of the stores they can see instead.
    const roster = users.length
      ? users.filter((u: any) => u.role_name === "Team Leader" && u.is_active)
      : [...storesByTl.entries()].map(([id, ss]) => ({ id, name: ss[0].team_leader_name || "Team leader" }))
          .filter((u) => u.name && u.name !== "Unassigned");
    return roster
      .map((u: any) => {
        const perf = perfByName.get(u.name);
        const myStores = storesByTl.get(u.id) || [];
        return {
          id: u.id,
          name: u.name,
          revenue: perf?.revenue || 0,
          target: perf?.target || 0,
          walkins: perf?.walkins || 0,
          conv: perf?.conversions || 0,
          achPct: perf?.achievement_pct || 0,
          convPct: perf?.walkins > 0 ? Math.round((perf.conversions / perf.walkins) * 100) : 0,
          stores: myStores.map((s: any) => s.name),
        };
      })
      .sort((a, b) => b.achPct - a.achPct);
  }, [users, stores, report]);

  const totalRevenue = tls.reduce((s, t) => s + t.revenue, 0);
  const totalTarget = tls.reduce((s, t) => s + t.target, 0);

  return (
    <ErrorBoundary>
      {tab === "analytics" ? (
        <AISummary section="team_leaders" title="Team Leaders AI Summary" />
      ) : (
        <div className="space-y-6">

        {/* Period filter */}
        <div className="flex flex-wrap items-center justify-between gap-3 bg-[var(--bg-card)] border border-[var(--border-subtle)] p-3 rounded-2xl">
          <div className="text-xs text-[var(--text-muted)]">
            Showing {effectiveRange.from} to {effectiveRange.to}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center rounded-xl border border-[var(--border-subtle)] bg-white/5 p-0.5">
              {([
                { key: "1day", label: "Today" },
                { key: "7day", label: "7 Days" },
                { key: "month", label: "Monthly" },
              ] as const).map((opt) => (
                <button
                  key={opt.key}
                  onClick={() => setPeriod(opt.key)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition ${
                    period === opt.key
                      ? "bg-[var(--accent-blue)] text-white"
                      : "text-[var(--text-secondary)] hover:text-white"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <div className="relative" ref={rangeFilterRef}>
              <button
                onClick={() => {
                  setDraftRange(period === "custom" && customRange ? customRange : effectiveRange);
                  setShowRangeFilter((v) => !v);
                }}
                className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-sm font-medium border transition ${
                  period === "custom"
                    ? "bg-blue-500/20 border-blue-500/40 text-blue-300"
                    : "bg-white/5 border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-white/10"
                }`}
              >
                <Filter size={14} />
                Custom
              </button>
              {showRangeFilter && (
                <div className="absolute right-0 mt-2 w-72 rounded-xl bg-[var(--bg-card)] border border-[var(--border-subtle)] shadow-2xl p-4 z-50 text-xs space-y-3">
                  <p className="font-semibold text-white">Custom date range</p>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <span className="text-[10px] text-[var(--text-muted)] block mb-0.5">From</span>
                      <input
                        type="date"
                        value={draftRange.from}
                        onChange={(e) => setDraftRange((p) => ({ ...p, from: e.target.value }))}
                        className="w-full bg-[var(--bg-primary)] border border-white/10 rounded-lg px-2 py-1.5 text-white text-xs focus:outline-none focus:border-blue-500"
                      />
                    </div>
                    <div>
                      <span className="text-[10px] text-[var(--text-muted)] block mb-0.5">To</span>
                      <input
                        type="date"
                        value={draftRange.to}
                        onChange={(e) => setDraftRange((p) => ({ ...p, to: e.target.value }))}
                        className="w-full bg-[var(--bg-primary)] border border-white/10 rounded-lg px-2 py-1.5 text-white text-xs focus:outline-none focus:border-blue-500"
                      />
                    </div>
                  </div>
                  <div className="flex items-center justify-between pt-1">
                    <button
                      onClick={() => { setPeriod("month"); setCustomRange(null); setShowRangeFilter(false); }}
                      className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-[var(--text-secondary)]"
                    >
                      Reset
                    </button>
                    <button
                      onClick={() => {
                        if (draftRange.from && draftRange.to) {
                          setCustomRange(draftRange);
                          setPeriod("custom");
                        }
                        setShowRangeFilter(false);
                      }}
                      disabled={!draftRange.from || !draftRange.to}
                      className="px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold disabled:opacity-50"
                    >
                      Apply
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Summary */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            { label: "Total TLs", value: String(tls.length), color: "#3b82f6" },
            { label: "Total Revenue", value: fmtINR(totalRevenue), color: "#10b981" },
            { label: "Total Target", value: fmtINR(totalTarget), color: "#a855f7" },
            { label: "Overall Achievement", value: `${totalTarget > 0 ? Math.round(totalRevenue / totalTarget * 100) : 0}%`, color: "#f59e0b" },
          ].map((k, i) => (
            <div key={i} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 relative overflow-hidden">
              <div className="absolute top-0 left-0 right-0 h-0.5" style={{ background: k.color }} />
              <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] mb-1">{k.label}</p>
              <p className="text-xl font-extrabold text-white">{k.value}</p>
            </div>
          ))}
        </div>

        {loading ? (
          <TableSkeleton rows={4} cols={4} />
        ) : tls.length === 0 ? (
          <div className="text-center py-12 text-[var(--text-muted)] rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)]">
            No Team Leader accounts found. Create one under Settings → Users with the "Team Leader" role.
          </div>
        ) : (
        <>
        {/* TL Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {tls.map((tl, i) => (
            <div key={i} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 relative overflow-hidden">
              <div className="absolute top-0 left-0 right-0 h-0.5" style={{ background: tl.achPct >= 65 ? "#10b981" : tl.achPct >= 35 ? "#f59e0b" : "#ef4444" }} />
              <div className="flex items-center justify-between mb-3">
                <span className="text-sm font-bold text-white">{tl.name}</span>
                <span className="text-xl font-extrabold" style={{ color: tl.achPct >= 65 ? "#10b981" : tl.achPct >= 35 ? "#f59e0b" : "#ef4444" }}>{tl.achPct.toFixed(0)}%</span>
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[var(--text-muted)] mb-3">
                <span className="flex items-center gap-1"><TrendingUp size={12} /> {fmtINR(tl.revenue)} / {fmtINR(tl.target)}</span>
                <span className="flex items-center gap-1"><Store size={12} /> {tl.stores.length} stores</span>
                <span>{tl.walkins} walkins</span>
                <span>{tl.conv} conv ({tl.convPct}%)</span>
              </div>
              <div className="w-full bg-[var(--border-subtle)] rounded-full h-2 overflow-hidden mb-2">
                <div className="h-full rounded-full" style={{ width: `${Math.min(tl.achPct, 100)}%`, background: tl.achPct >= 65 ? "#10b981" : tl.achPct >= 35 ? "#f59e0b" : "#ef4444" }} />
              </div>
              <p className="text-[11px] text-[var(--text-muted)]">
                Stores: <span className="text-[var(--text-secondary)]">{tl.stores.length ? tl.stores.join(", ") : "None assigned yet"}</span>
              </p>
              <div className="flex justify-end mt-3">
                <Link to={`/team-leaders/${tl.id}`}
                  className="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg border border-[var(--border-subtle)] text-blue-400 hover:bg-blue-500/10 transition-colors">
                  View performance <ArrowRight size={13} />
                </Link>
              </div>
            </div>
          ))}
        </div>

        {/* TL Table */}
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 sm:p-6 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left border-collapse">
              <thead>
                <tr className="text-[var(--text-muted)] text-xs uppercase tracking-wider border-b border-[var(--border-subtle)]">
                  <th className="py-3 px-4 font-semibold">Team Leader</th>
                  <th className="py-3 px-4 font-semibold text-right">Revenue</th>
                  <th className="py-3 px-4 font-semibold text-right">Target</th>
                  <th className="py-3 px-4 font-semibold text-right">Achievement</th>
                  <th className="py-3 px-4 font-semibold text-right">Walk-ins</th>
                  <th className="py-3 px-4 font-semibold text-right">Stores</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-subtle)]">
                {tls.map((tl, i) => (
                  <tr key={i} className="hover:bg-[var(--bg-card-hover)] transition-colors">
                    <td className="py-3.5 px-4 font-medium text-white flex items-center gap-3">
                      <div className="h-8 w-8 rounded-full bg-[var(--accent-blue)]/15 border border-[var(--accent-blue)]/30 flex items-center justify-center text-[var(--accent-blue)] font-bold text-xs shrink-0">
                        {tl.name.charAt(0)}
                      </div>
                      <span className="font-semibold">{tl.name}</span>
                    </td>
                    <td className="py-3.5 px-4 text-right font-semibold text-white">{fmtINR(tl.revenue)}</td>
                    <td className="py-3.5 px-4 text-right text-[var(--text-secondary)]">{fmtINR(tl.target)}</td>
                    <td className="py-3.5 px-4 text-right">
                      <div className="flex items-center justify-end gap-2.5">
                        <div className="w-24 h-2 bg-[var(--border-subtle)] rounded-full overflow-hidden shrink-0">
                          <div className="h-full rounded-full" style={{ width: `${Math.min(tl.achPct, 100)}%`, background: tl.achPct >= 65 ? "#10b981" : tl.achPct >= 35 ? "#f59e0b" : "#ef4444" }} />
                        </div>
                        <span className="text-xs font-semibold text-[var(--text-primary)] min-w-[42px] text-right">{tl.achPct.toFixed(1)}%</span>
                      </div>
                    </td>
                    <td className="py-3.5 px-4 text-right text-[var(--text-secondary)]">{tl.walkins}</td>
                    <td className="py-3.5 px-4 text-right">
                      <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-white">
                        {tl.stores.length}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        </>
        )}
      </div>

      )}
    </ErrorBoundary>
  );
}
