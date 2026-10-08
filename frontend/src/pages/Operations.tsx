import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/apiClient";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { AISummary } from "@/components/dashboard/AISummary";
import { Calendar, Filter, Loader2, Store } from "lucide-react";
import { TableSkeleton } from "@/components/shared/Skeleton";

import { useSocketRefresh } from "../hooks/useSocketRefresh";

function fmtINR(n: number) {
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`;
  if (n >= 1000) return `₹${(n / 1000).toFixed(1)}K`;
  return `₹${n.toLocaleString("en-IN")}`;
}

function localDateStr(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function Operations() {
  const [searchParams] = useSearchParams();
  const tab = searchParams.get("tab") || "main";
  useSocketRefresh(["operations"]);
  const [sheetsData, setSheetsData] = useState<any>(null);
  const [stores, setStores] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [storeFilter, setStoreFilter] = useState("");
  const [tlFilter, setTlFilter] = useState("");
  const [dateFilter, setDateFilter] = useState("");

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

  const fetchSheets = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api.fetchRaw(`/ceo-dashboard/sheets-data?tab=ops&start=${effectiveRange.from}&end=${effectiveRange.to}`);
      if (res.ok) {
        const d = await res.json();
        if (!d.error) setSheetsData(d);
      } else {
        setError("Failed to load operations data");
      }
    } catch {
      setError("Failed to load operations data");
    }
    setLoading(false);
  }, [effectiveRange]);

  useEffect(() => { fetchStores(); }, [fetchStores]);
  useEffect(() => { fetchSheets(); }, [fetchSheets]);

  const opsData = sheetsData?.ops_data || [];

  const filteredData = useMemo(() => {
    return opsData.filter((r: any) => {
      if (!r.store || r.store === "STORE NAME") return false;
      if (storeFilter && r.store !== storeFilter) return false;
      if (tlFilter && r.tl !== tlFilter) return false;
      if (dateFilter && r.date !== dateFilter) return false;
      return true;
    });
  }, [opsData, storeFilter, tlFilter, dateFilter]);

  // Store/TL dropdown options — and the "assigned but not reflecting" check
  // below — are sourced from the real roster (/stores/, which always
  // reflects the current Branch Assignment page state) rather than only
  // from opsData's own submission history. A store just (re)assigned to a
  // Team Leader has zero Sheets submissions logged for it yet in most
  // cases (nobody's filled in today's walk-ins for it), so it never showed
  // up anywhere on this page before — not because the assignment failed,
  // but because this page only ever looked at past submission rows to
  // decide what stores/TLs even exist.
  const indiaStores = useMemo(() => stores.filter((s: any) => s.country === "India" && s.is_active), [stores]);

  const uniqueStores = useMemo((): string[] => {
    const fromRoster = indiaStores.map((s: any) => s.name);
    const fromOps = opsData.map((r: any) => r.store).filter(Boolean);
    return Array.from(new Set([...fromRoster, ...fromOps])).sort();
  }, [indiaStores, opsData]);

  const uniqueTLs = useMemo((): string[] => {
    const fromRoster = indiaStores.map((s: any) => s.team_leader_name).filter(Boolean);
    const fromOps = opsData.map((r: any) => r.tl).filter(Boolean);
    return Array.from(new Set([...fromRoster, ...fromOps])).sort();
  }, [indiaStores, opsData]);

  const uniqueDates = useMemo((): string[] => {
    const ds = new Set<string>(opsData.map((r: any) => r.date).filter(Boolean));
    return Array.from(ds).sort().reverse();
  }, [opsData]);

  // Stores that ARE assigned to a Team Leader right now but have logged no
  // Sheets submission at all in the selected period — surfaced explicitly
  // so "the assignment isn't reflecting" is visibly "no data logged yet"
  // rather than the store just silently never appearing anywhere.
  const storesWithNoData = useMemo(() => {
    const storesWithData = new Set(opsData.map((r: any) => r.store));
    return indiaStores.filter((s: any) => s.team_leader_id && !storesWithData.has(s.name));
  }, [indiaStores, opsData]);

  const totalRevenue = filteredData.reduce((s: number, r: any) => s + (r.revenue || 0), 0);
  const totalUnits = filteredData.reduce((s: number, r: any) => s + (r.units_sold || 0), 0);
  const totalWalkins = filteredData.reduce((s: number, r: any) => s + (r.walk_ins || 0), 0);
  const totalConversions = filteredData.reduce((s: number, r: any) => s + (r.walk_in_conversions || 0), 0);

  return (
    <ErrorBoundary>
      {tab === "analytics" ? (
        <AISummary section="operations" title="Operations AI Summary" />
      ) : (
        <div className="space-y-6">
        {error && (
          <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
            {error}
          </div>
        )}
        {loading && !error && (
          <div className="flex items-center gap-2 text-zinc-400 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading operations data...
          </div>
        )}

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
            { label: "Revenue", value: fmtINR(totalRevenue), color: "#3b82f6" },
            { label: "Units Sold", value: totalUnits.toLocaleString(), color: "#10b981" },
            { label: "Walk-ins", value: totalWalkins.toLocaleString(), color: "#a855f7" },
            { label: "Conversions", value: totalConversions.toLocaleString(), color: "#f59e0b" },
          ].map((k, i) => (
            <div key={i} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 relative overflow-hidden">
              <div className="absolute top-0 left-0 right-0 h-0.5" style={{ background: k.color }} />
              <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] mb-1">{k.label}</p>
              <p className="text-xl font-extrabold text-white">{k.value}</p>
            </div>
          ))}
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3 bg-[var(--bg-card)] border border-[var(--border-subtle)] p-3 rounded-2xl flex-wrap">
          <Filter size={16} className="text-[var(--text-muted)] ml-1 shrink-0" />
          <select
            value={storeFilter}
            onChange={(e) => setStoreFilter(e.target.value)}
            className="px-3 py-2 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none max-w-[200px] w-full"
          >
            <option value="">All Stores</option>
            {[...uniqueStores].map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <select
            value={tlFilter}
            onChange={(e) => setTlFilter(e.target.value)}
            className="px-3 py-2 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none max-w-[200px] w-full"
          >
            <option value="">All TLs</option>
            {[...uniqueTLs].map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <select
            value={dateFilter}
            onChange={(e) => setDateFilter(e.target.value)}
            className="px-3 py-2 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none max-w-[200px] w-full"
          >
            <option value="">All Dates</option>
            {[...uniqueDates].map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          <span className="text-xs text-[var(--text-muted)]">{filteredData.length} records</span>
        </div>

        {storesWithNoData.length > 0 && (
          <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-4 text-xs text-amber-200">
            <p className="font-semibold mb-1.5">
              {storesWithNoData.length} store{storesWithNoData.length > 1 ? "s are" : " is"} assigned to a Team Leader but {storesWithNoData.length > 1 ? "have" : "has"} no walk-in/units submission logged for {effectiveRange.from} to {effectiveRange.to} yet:
            </p>
            <p className="text-amber-300/80">
              {storesWithNoData.map((s: any) => `${s.name} (${s.team_leader_name})`).join(", ")}
            </p>
          </div>
        )}

        {/* Table */}
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 sm:p-6 overflow-hidden">
          {loading ? (
            <TableSkeleton rows={5} cols={7} />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left border-collapse">
                <thead>
                  <tr className="text-[var(--text-muted)] text-xs uppercase tracking-wider border-b border-[var(--border-subtle)]">
                    <th className="py-3 px-4 font-semibold">Store</th>
                    <th className="py-3 px-4 font-semibold">TL</th>
                    <th className="py-3 px-4 font-semibold">Date</th>
                    <th className="py-3 px-4 font-semibold text-right">Revenue</th>
                    <th className="py-3 px-4 font-semibold text-right">Units</th>
                    <th className="py-3 px-4 font-semibold text-right">Walk-ins</th>
                    <th className="py-3 px-4 font-semibold text-right">Conversions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border-subtle)]">
                  {filteredData.slice(0, 200).map((sub: any, i: number) => (
                    <tr key={i} className="hover:bg-[var(--bg-card-hover)] transition-colors">
                      <td className="py-3.5 px-4 font-medium text-white flex items-center gap-2.5">
                        <Store size={15} className="text-[var(--accent-blue)] shrink-0" />
                        <span>{sub.store}</span>
                      </td>
                      <td className="py-3.5 px-4 text-xs text-[var(--text-secondary)]">{sub.tl}</td>
                      <td className="py-3.5 px-4 text-xs text-[var(--text-secondary)] font-medium">
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)]">
                          <Calendar size={13} className="text-[var(--text-muted)]" />
                          {sub.date}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-right font-semibold text-white">{fmtINR(sub.revenue || 0)}</td>
                      <td className="py-3.5 px-4 text-right text-[var(--text-secondary)]">{sub.units_sold || 0}</td>
                      <td className="py-3.5 px-4 text-right text-[var(--text-secondary)]">{sub.walk_ins || 0}</td>
                      <td className="py-3.5 px-4 text-right font-medium text-emerald-400">{sub.walk_in_conversions || 0}</td>
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
