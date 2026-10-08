import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "@/lib/apiClient";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { AISummary } from "@/components/dashboard/AISummary";
import { Filter, Store, RefreshCw, ChevronRight, Package } from "lucide-react";
import { StatCardSkeleton } from "@/components/shared/Skeleton";

import { useSocketRefresh } from "../hooks/useSocketRefresh";

const COUNTRY_COLORS: Record<string, string> = {
  India: "#3b82f6",
  UAE: "#10b981",
  Oman: "#f59e0b",
  Qatar: "#a855f7",
  Pakistan: "#ef4444",
  Malaysia: "#06b6d4",
  UK: "#ec4899",
  Bahrain: "#f97316",
};

function fmtCurrency(n: number, country: string) {
  switch (country) {
    case "India": {
      if (n >= 10000000) return `₹${(n / 10000000).toFixed(2)} Cr`;
      if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`;
      if (n >= 1000) return `₹${(n / 1000).toFixed(1)}K`;
      return `₹${n.toLocaleString("en-IN")}`;
    }
    case "UAE": return `AED ${(n / 1000).toFixed(1)}K`;
    case "Oman": return `OMR ${(n / 1000).toFixed(1)}K`;
    case "Qatar": return `QAR ${(n / 1000).toFixed(1)}K`;
    case "Pakistan": return `PKR ${(n / 100000).toFixed(1)}L`;
    case "Malaysia": return `MYR ${(n / 1000).toFixed(1)}K`;
    case "UK": return `£${(n / 1000).toFixed(1)}K`;
    case "Bahrain": return `BHD ${(n / 1000).toFixed(1)}K`;
    default: return `$${(n / 1000).toFixed(1)}K`;
  }
}

function localDateStr(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function normalizeName(n: string) {
  return (n || "").trim().toLowerCase().replace(/\s+/g, " ");
}

export default function SalesOverview() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const tab = searchParams.get("tab") || "main";
  useSocketRefresh(["sales"]);

  const [branches, setBranches] = useState<any[]>([]);
  const [branchesLoading, setBranchesLoading] = useState(true);
  const [report, setReport] = useState<any>(null);
  const [reportLoading, setReportLoading] = useState(true);
  const [storeFilter, setStoreFilter] = useState("");
  // Blank = "All Countries" — valid for the store table/list, but the top
  // Revenue/Target KPIs never blend raw values across countries (₹ + AED +
  // OMR + ... summed together is meaningless), so those cards only render
  // once a single country is picked, same convention the main Dashboard
  // page uses.
  const [countryFilter, setCountryFilter] = useState("India");

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

  const fetchBranches = useCallback(async () => {
    setBranchesLoading(true);
    try {
      // Stock is a live, point-in-time figure (not something that can be
      // read "as of 7 days ago"), so it's fetched once, independent of the
      // period filter, and merged onto each period-scoped row by name below.
      const res = await api.fetchRaw("/mcp/branches");
      if (res.ok) setBranches(await res.json());
    } catch {}
    setBranchesLoading(false);
  }, []);

  const fetchReport = useCallback(async () => {
    setReportLoading(true);
    try {
      // No country param here — always pull every country in one call and
      // filter client-side, the same way the store-name search already
      // works, so switching countries/periods doesn't refetch twice.
      const params = `group_by=branch&granularity=day&start=${effectiveRange.from}&end=${effectiveRange.to}`;
      const res = await api.fetchRaw(`/sales-reports?${params}`);
      if (res.ok) setReport(await res.json());
    } catch {}
    setReportLoading(false);
  }, [effectiveRange]);

  useEffect(() => { fetchBranches(); }, [fetchBranches]);
  useEffect(() => { fetchReport(); }, [fetchReport]);

  const loading = branchesLoading || reportLoading;

  const stockByName = useMemo(() => {
    const m = new Map<string, any>();
    for (const b of branches) {
      if (b.shop) m.set(normalizeName(b.shop), b);
    }
    return m;
  }, [branches]);

  // Combines the period-scoped revenue/target/achievement from
  // /sales-reports with the always-current stock figure from /mcp/branches,
  // matched by store name.
  const allStores = useMemo(() => {
    return (report?.breakdown || []).map((r: any) => {
      const stock = stockByName.get(normalizeName(r.key));
      return {
        store_id: r.store_id,
        team_leader: r.team_leader || "",
        shop: r.key,
        country: r.country,
        actual: r.revenue,
        target: r.target,
        achievement_pct: r.achievement_pct,
        stock_units: stock?.stock_units || 0,
        stock_items: stock?.stock_items || [],
      };
    });
  }, [report, stockByName]);

  const stores = useMemo(() => {
    return allStores
      .filter((b: any) => {
        if (storeFilter && !b.shop.toLowerCase().includes(storeFilter.toLowerCase())) return false;
        if (countryFilter && b.country !== countryFilter) return false;
        return true;
      })
      .sort((a: any, b: any) => b.achievement_pct - a.achievement_pct);
  }, [allStores, storeFilter, countryFilter]);

  const uniqueCountries = useMemo(() => {
    const cs = new Set<string>(allStores.map((b: any) => b.country).filter(Boolean));
    return Array.from(cs).sort();
  }, [allStores]);

  // Only meaningful in a single currency — blank (All Countries) leaves
  // these unset rather than adding ₹ + AED + OMR + ... into one number.
  const singleCountrySelected = countryFilter && uniqueCountries.includes(countryFilter);
  const countryStores = useMemo(
    () => (singleCountrySelected ? allStores.filter((s: any) => s.country === countryFilter) : []),
    [allStores, countryFilter, singleCountrySelected]
  );
  const totalRevenue = countryStores.reduce((s: number, st: any) => s + (st.actual || 0), 0);
  const totalTarget = countryStores.reduce((s: number, st: any) => s + (st.target || 0), 0);
  const overallAch = totalTarget > 0 ? (totalRevenue / totalTarget * 100) : 0;
  const countryCount = uniqueCountries.length;

  return (
    <ErrorBoundary>
      {tab === "analytics" ? (
        <AISummary section="sales" title="Store Overview AI Summary" />
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
                <div className="absolute right-0 mt-2 w-72 rounded-xl bg-[#11131e] border border-[var(--border-subtle)] shadow-2xl p-4 z-50 text-xs space-y-3">
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

        {/* Summary KPIs */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
          {[
            { label: "Total Revenue", value: singleCountrySelected ? fmtCurrency(totalRevenue, countryFilter) : "Select a country", color: "#3b82f6" },
            { label: "Total Target", value: singleCountrySelected ? fmtCurrency(totalTarget, countryFilter) : "Select a country", color: "#10b981" },
            { label: "Achievement", value: singleCountrySelected ? `${overallAch.toFixed(1)}%` : "—", color: overallAch >= 50 ? "#10b981" : "#f59e0b" },
            { label: "Total Branches", value: String(stores.length), color: "#a855f7" },
            { label: "Countries", value: String(countryCount), color: "#ec4899" },
          ].map((k, i) => (
            <div key={i} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 relative overflow-hidden">
              <div className="absolute top-0 left-0 right-0 h-0.5" style={{ background: k.color }} />
              <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] mb-1">{k.label}</p>
              <p className={k.value.length > 8 ? "text-base font-extrabold text-white" : "text-xl font-extrabold text-white"}>{k.value}</p>
            </div>
          ))}
        </div>

        {/* Country summary badges — each button shows that country's own total in its own currency, never blended with another country's */}
        <div className="flex flex-wrap gap-2">
          {uniqueCountries.map((country) => {
            const countryRows = allStores.filter((b: any) => b.country === country);
            const count = countryRows.length;
            const rev = countryRows.reduce((s: number, b: any) => s + (b.actual || 0), 0);
            return (
              <button
                key={country}
                onClick={() => setCountryFilter(countryFilter === country ? "" : country)}
                className={`inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border transition-colors ${
                  countryFilter === country
                    ? "bg-white/10 border-white/20 text-white"
                    : "bg-white/5 border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-white/8"
                }`}
              >
                <span className="w-2 h-2 rounded-full" style={{ background: COUNTRY_COLORS[country] || "#6b7280" }} />
                {country} ({count}) — {fmtCurrency(rev, country)}
              </button>
            );
          })}
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3 bg-[var(--bg-card)] border border-[var(--border-subtle)] p-3 rounded-2xl">
          <Filter size={16} className="text-[var(--text-muted)] ml-1 shrink-0" />
          <input
            type="text"
            placeholder="Search stores..."
            value={storeFilter}
            onChange={(e) => setStoreFilter(e.target.value)}
            className="px-3 py-2 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none max-w-[200px] w-full"
          />
          <select
            value={countryFilter}
            onChange={(e) => setCountryFilter(e.target.value)}
            className="px-3 py-2 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none max-w-[200px] w-full"
          >
            <option value="">All Countries</option>
            {uniqueCountries.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          <button
            onClick={() => { fetchBranches(); fetchReport(); }}
            disabled={loading}
            className="ml-auto flex items-center gap-2 px-3 py-2 text-xs rounded-xl border border-[var(--border-subtle)] text-[var(--text-muted)] hover:text-white disabled:opacity-50"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>

        {/* Store cards — click one for its full performance portfolio */}
        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            {Array.from({ length: 6 }).map((_, i) => <StatCardSkeleton key={i} />)}
          </div>
        ) : stores.length === 0 ? (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] text-center py-12 text-[var(--text-muted)]">No branch data available</div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            {stores.map((s: any) => {
              const color = COUNTRY_COLORS[s.country] || "#6b7280";
              const ach = s.achievement_pct || 0;
              return (
                <button
                  key={s.store_id ?? s.shop}
                  onClick={() => s.store_id && navigate(`/sales-overview/${s.store_id}`)}
                  className="group text-left rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 hover:border-[var(--border-glow)] hover:bg-[var(--bg-card-hover)] transition-colors"
                >
                  <div className="flex items-start gap-3">
                    <div className="h-10 w-10 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] flex items-center justify-center shrink-0">
                      <Store size={17} style={{ color }} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-white truncate">{s.shop}</p>
                      <p className="text-[11px] text-[var(--text-muted)] truncate flex items-center gap-1.5">
                        <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: color }} />
                        {s.country}{s.team_leader && ` · ${s.team_leader}`}
                      </p>
                    </div>
                    <ChevronRight size={16} className="text-[var(--text-muted)] group-hover:text-white shrink-0 mt-1" />
                  </div>
                  <div className="mt-4 flex items-end justify-between gap-2">
                    <div>
                      <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">Revenue</p>
                      <p className="text-lg font-extrabold text-white tabular-nums">{fmtCurrency(s.actual || 0, s.country)}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">Target</p>
                      <p className="text-sm font-semibold text-[var(--text-secondary)] tabular-nums">{fmtCurrency(s.target || 0, s.country)}</p>
                    </div>
                  </div>
                  <div className="mt-3 flex items-center gap-2.5">
                    <div className="h-2 flex-1 bg-[var(--border-subtle)] rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{ width: `${Math.min(ach, 100)}%`, backgroundColor: ach >= 65 ? "#10b981" : ach >= 35 ? "#f59e0b" : "#ef4444" }}
                      />
                    </div>
                    <span className="text-xs font-semibold text-[var(--text-primary)] tabular-nums min-w-[42px] text-right">{ach.toFixed(1)}%</span>
                  </div>
                  <p className={`mt-3 text-[11px] flex items-center gap-1.5 ${(s.stock_units || 0) < 0 ? "text-red-400" : "text-[var(--text-secondary)]"}`}>
                    <Package size={12} /> Stock {(s.stock_units || 0).toLocaleString()} units
                  </p>
                </button>
              );
            })}
          </div>
        )}
      </div>

      )}
    </ErrorBoundary>
  );
}
