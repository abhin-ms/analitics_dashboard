import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/apiClient";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { AISummary } from "@/components/dashboard/AISummary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { Award, Filter } from "lucide-react";
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

function normalizeName(n: string) {
  return (n || "").trim().toLowerCase().replace(/\s+/g, " ");
}

export default function Performance() {
  const [searchParams] = useSearchParams();
  const tab = searchParams.get("tab") || "main";
  useSocketRefresh(["performance"]);

  const [report, setReport] = useState<any>(null);
  const [opsData, setOpsData] = useState<any[]>([]);
  const [stores, setStores] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [tlFilter, setTlFilter] = useState("");

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

  const fetchStores = useCallback(async () => {
    try {
      const res = await api.fetchRaw("/stores/");
      if (res.ok) setStores(await res.json());
    } catch {}
  }, []);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      // Revenue/target/achievement/walk-ins come from the MCP-backed sales
      // report — it covers every confirmed branch, not just ones with a
      // manual Sheets submission on file. Call-rate metrics (calls made/
      // connected) genuinely only exist in the Sheets submission log, so
      // that piece is merged in separately by store name below.
      const params = `group_by=branch&granularity=day&country=India&start=${effectiveRange.from}&end=${effectiveRange.to}`;
      const [reportRes, opsRes] = await Promise.all([
        api.fetchRaw(`/sales-reports?${params}`),
        api.fetchRaw(`/ceo-dashboard/sheets-data?tab=ops&start=${effectiveRange.from}&end=${effectiveRange.to}`),
      ]);
      if (reportRes.ok) setReport(await reportRes.json());
      if (opsRes.ok) {
        const d = await opsRes.json();
        setOpsData(d.ops_data || []);
      }
    } catch {}
    setLoading(false);
  }, [effectiveRange]);

  useEffect(() => { fetchStores(); }, [fetchStores]);
  useEffect(() => { fetchData(); }, [fetchData]);

  const tlByStoreName = useMemo(() => {
    const m = new Map<string, string>();
    for (const s of stores) {
      if (s.name && s.team_leader_name) m.set(normalizeName(s.name), s.team_leader_name);
    }
    return m;
  }, [stores]);

  const callsByStoreName = useMemo(() => {
    const m = new Map<string, { callsMade: number; callsConnected: number }>();
    for (const r of opsData) {
      if (!r.store) continue;
      const key = normalizeName(r.store);
      const cur = m.get(key) || { callsMade: 0, callsConnected: 0 };
      cur.callsMade += r.calls_made || 0;
      cur.callsConnected += r.calls_connected || 0;
      m.set(key, cur);
    }
    return m;
  }, [opsData]);

  const storeScores = useMemo(() => {
    return (report?.breakdown || [])
      .map((r: any) => {
        const tl = tlByStoreName.get(normalizeName(r.key)) || "Unassigned";
        const calls = callsByStoreName.get(normalizeName(r.key)) || { callsMade: 0, callsConnected: 0 };
        const revAch = r.target > 0 ? r.revenue / r.target : 0;
        const convRate = r.walkins > 0 ? r.conversions / r.walkins : 0;
        const callRate = calls.callsMade > 0 ? calls.callsConnected / calls.callsMade : 0;
        const totalScore = (revAch * 0.5 + convRate * 0.3 + callRate * 0.2);
        let band = "Below Target";
        if (totalScore >= 1.0) band = "Exceeds";
        else if (totalScore >= 0.8) band = "Meets";
        else if (totalScore >= 0.6) band = "Approaching";
        return {
          name: r.key, tl,
          revenue: r.revenue, target: r.target,
          walkins: r.walkins, conversions: r.conversions,
          revAch: revAch * 100, convRate: convRate * 100, callRate: callRate * 100,
          totalScore, band,
        };
      })
      .filter((s: any) => {
        if (tlFilter && s.tl !== tlFilter) return false;
        return true;
      })
      .sort((a: any, b: any) => b.totalScore - a.totalScore);
  }, [report, tlByStoreName, callsByStoreName, tlFilter]);

  const uniqueTLs = useMemo((): string[] => {
    const tls = new Set<string>((report?.breakdown || []).map((r: any) => tlByStoreName.get(normalizeName(r.key)) || "Unassigned"));
    return Array.from(tls).sort();
  }, [report, tlByStoreName]);

  return (
    <ErrorBoundary>
      {tab === "analytics" ? (
        <AISummary section="performance" title="Performance AI Summary" />
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

        {/* Incentive Bands */}
        <div className="flex items-center gap-3 flex-wrap bg-[var(--bg-card)] border border-[var(--border-subtle)] p-4 rounded-2xl">
          <Award size={18} className="text-[var(--accent-blue)] shrink-0" />
          {[
            { name: "Exceeds", label: "100%+ score", color: "#10b981" },
            { name: "Meets", label: "80-99%", color: "#3b82f6" },
            { name: "Approaching", label: "60-79%", color: "#f59e0b" },
            { name: "Below Target", label: "<60%", color: "#ef4444" },
          ].map((b) => (
            <div key={b.name} className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] px-3.5 py-1.5 text-xs flex items-center gap-2">
              <span className="font-semibold text-white">{b.name}:</span>
              <span className="text-[var(--text-secondary)]">{b.label}</span>
            </div>
          ))}
        </div>

        {/* Filter */}
        <div className="flex items-center gap-3 bg-[var(--bg-card)] border border-[var(--border-subtle)] p-3 rounded-2xl">
          <Filter size={16} className="text-[var(--text-muted)] ml-1 shrink-0" />
          <select
            value={tlFilter}
            onChange={(e) => setTlFilter(e.target.value)}
            className="px-3 py-2 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none max-w-[200px] w-full"
          >
            <option value="">All TLs</option>
            {uniqueTLs.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>

        {/* Table */}
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 sm:p-6 overflow-hidden">
          {loading ? (
            <TableSkeleton rows={6} cols={7} />
          ) : storeScores.length === 0 ? (
            <div className="text-center py-12 text-[var(--text-muted)]">No branch data for this period</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left border-collapse">
                <thead>
                  <tr className="text-[var(--text-muted)] text-xs uppercase tracking-wider border-b border-[var(--border-subtle)]">
                    <th className="py-3 px-4 font-semibold">Store</th>
                    <th className="py-3 px-4 font-semibold">TL</th>
                    <th className="py-3 px-4 font-semibold text-right">Total Score</th>
                    <th className="py-3 px-4 font-semibold">Band</th>
                    <th className="py-3 px-4 font-semibold text-right">Revenue vs Target</th>
                    <th className="py-3 px-4 font-semibold text-right">Conv Rate</th>
                    <th className="py-3 px-4 font-semibold text-right">Call Rate</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border-subtle)]">
                  {storeScores.map((s: any, i: number) => (
                    <tr key={i} className="hover:bg-[var(--bg-card-hover)] transition-colors">
                      <td className="py-3.5 px-4 font-semibold text-white">{s.name}</td>
                      <td className="py-3.5 px-4 text-xs text-[var(--text-secondary)]">{s.tl}</td>
                      <td className="py-3.5 px-4 text-right font-bold text-white">
                        {(s.totalScore * 100).toFixed(1)}%
                      </td>
                      <td className="py-3.5 px-4">
                        <span className={`px-2.5 py-1 rounded-full text-xs font-semibold border ${
                          s.band === "Exceeds" ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" :
                          s.band === "Meets" ? "bg-blue-500/10 text-blue-400 border-blue-500/20" :
                          s.band === "Approaching" ? "bg-amber-500/10 text-amber-400 border-amber-500/20" :
                          "bg-rose-500/10 text-rose-400 border-rose-500/20"
                        }`}>{s.band}</span>
                      </td>
                      <td className="py-3.5 px-4 text-right font-semibold text-[var(--text-secondary)]">
                        {s.revAch.toFixed(1)}% <span className="text-[10px] text-[var(--text-muted)]">({fmtINR(s.revenue)}/{fmtINR(s.target)})</span>
                      </td>
                      <td className="py-3.5 px-4 text-right font-semibold text-[var(--text-secondary)]">
                        {s.convRate.toFixed(1)}%
                      </td>
                      <td className="py-3.5 px-4 text-right font-semibold text-[var(--text-secondary)]">
                        {s.callRate.toFixed(1)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      )}
    </ErrorBoundary>
  );
}
