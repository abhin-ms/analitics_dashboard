import { useState, useEffect, useCallback, useMemo, useRef, lazy, Suspense } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { api } from "@/lib/apiClient";
import { localDateStr } from "@/lib/utils";
import { formatByCountry as fmtByCountry } from "@/lib/formatMoney";
import { StatCard } from "@/components/shared/StatCard";
import { StatCardSkeleton } from "@/components/shared/Skeleton";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import {
  DollarSign, Target, TrendingUp, Users, Phone, Briefcase, Award, AlertTriangle, PieChart as PieIcon, BarChart3,
  Globe, Video, MessageCircle, Star, Eye, Package, Filter, MapPin, Store, RefreshCw
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, RadialBarChart, RadialBar, CartesianGrid,
  BarChart, Bar, Legend,
} from "recharts";
import { useSocketRefresh } from "../hooks/useSocketRefresh";
import { AISummary } from "@/components/dashboard/AISummary";
import {
  CardFilterPopover,
  CardFilterState,
  DEFAULT_CARD_FILTER,
  applyCardFilter,
} from "@/components/shared/CardFilterPopover";

const BranchGlobe = lazy(() => import("@/components/dashboard/BranchGlobe"));

const COLORS = ["#3b82f6", "#10b981", "#a855f7", "#f97316", "#ec4899", "#06b6d4"];

// Matches the country_id values documented on /mcp/sales/daily and used
// consistently across the MCP endpoints (1=India 2=Oman 3=Pakistan 4=UAE
// 5=Malaysia 6=UK 7=Bahrain 8=Qatar).
const COUNTRY_IDS: Record<string, number> = {
  India: 1, Oman: 2, Pakistan: 3, UAE: 4, Malaysia: 5, UK: 6, Bahrain: 7, Qatar: 8,
};
const COUNTRY_OPTIONS = Object.keys(COUNTRY_IDS);

function shortStore(name: string) {
  return name.replace("Kerala ", "").replace("Chennai ", "").replace("Bangalore ", "")
    .replace("Hyderabad ", "").replace("TN ", "").replace("Mumbai ", "")
    .replace("Delhi ", "").replace(" Lajpat Nagar", "").replace(" Mall", "").trim();
}

function startOfLocalMonth() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), 1);
}

function ragColor(p: number) { return p >= 65 ? "#10b981" : p >= 35 ? "#f59e0b" : "#ef4444"; }
function ragLabel(p: number) { return p >= 100 ? "Achieved" : p >= 65 ? "On Track" : p >= 35 ? "Below Target" : "Critical"; }
function fmtINR(n: number) {
  if (n >= 100000) return `\u20b9${(n / 100000).toFixed(1)}L`;
  if (n >= 1000) return `\u20b9${(n / 1000).toFixed(1)}K`;
  return `\u20b9${n.toLocaleString("en-IN")}`;
}
// Same idea, keyed by ISO-ish currency code instead of country name — the
// MCP country-comparison data reports each country's own local_currency
// code directly (INR, AED, OMR, QAR...) rather than a country string.
function fmtByCurrency(n: number, currency: string) {
  switch (currency) {
    case "INR": {
      if (n >= 10000000) return `₹${(n / 10000000).toFixed(2)} Cr`;
      if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`;
      return `₹${(n / 1000).toFixed(1)}K`;
    }
    case "GBP": return `£${(n / 1000).toFixed(1)}K`;
    case "PKR": return `PKR ${(n / 100000).toFixed(1)}L`;
    default: return `${currency} ${(n / 1000).toFixed(1)}K`;
  }
}
function fmtNum(n: number) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

export default function Dashboard() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get("tab") || "dashboard";
  useSocketRefresh(["sheets-data"]);
  const [sheetsData, setSheetsData] = useState<any>(null);
  const [sheetsLoading, setSheetsLoading] = useState(true);
  const [sheetsError, setSheetsError] = useState("");
  const [trendFilter, setTrendFilter] = useState<CardFilterState>(DEFAULT_CARD_FILTER);
  const [todayLiveRevenue, setTodayLiveRevenue] = useState(0);
  const [mcpLiveLoading, setMcpLiveLoading] = useState(false);
  const [countryData, setCountryData] = useState<any[]>([]);
  const [countryLoading, setCountryLoading] = useState(false);
  // India revenue/target/achievement, live from MCP (McpDailySale) joined to
  // Store.team_leader_id — replaces the old Sheets-only ops_data source so
  // these cards work for Today/7 Days too, not just ranges a Team Leader
  // happened to submit a sheet row for. Walk-ins/conversions still come
  // from Sheets under the hood (MCP has no funnel data), blended in by the
  // same /sales-reports endpoint.
  const [mcpTlReport, setMcpTlReport] = useState<any>(null);
  const [mcpBranchReport, setMcpBranchReport] = useState<any>(null);
  const [mcpReportLoading, setMcpReportLoading] = useState(true);
  const [mcpReportError, setMcpReportError] = useState("");
  const [stockData, setStockData] = useState<any[]>([]);
  const [stockLoading, setStockLoading] = useState(false);
  const [stockError, setStockError] = useState("");
  const [stockCountryId, setStockCountryId] = useState(4);
  const [stockExpanded, setStockExpanded] = useState<Set<string>>(new Set());
  const [branchesData, setBranchesData] = useState<any[]>([]);
  const [branchesLoading, setBranchesLoading] = useState(false);
  const [branchesExpanded, setBranchesExpanded] = useState<Set<string>>(new Set());
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState("");
  const [period, setPeriod] = useState<"1day" | "7day" | "month" | "6month" | "1year" | "custom">("month");
  const [selectedCountry, setSelectedCountry] = useState<string>("India");
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

  // The single date range driving every section of the dashboard (KPIs,
  // trend, breakdowns, MCP-live sections) — a rolling window ending today
  // for the presets, or whatever the user picked for Custom.
  const effectiveRange = useMemo(() => {
    const now = new Date();
    const to = localDateStr(now);
    if (period === "custom" && customRange) return customRange;
    if (period === "1day") return { from: to, to }; // today only
    if (period === "month") {
      // Calendar month to date (1st of the current month through today),
      // not a rolling 30 days — matches how "monthly" is understood
      // everywhere else (MCP's own target sheets, International Sales),
      // so this card and that chart cover the exact same window instead
      // of silently comparing two different date ranges.
      const from = new Date(now.getFullYear(), now.getMonth(), 1);
      return { from: localDateStr(from), to };
    }
    const from = new Date(now);
    if (period === "7day") from.setDate(from.getDate() - 6);
    else if (period === "6month") from.setMonth(from.getMonth() - 6);
    else if (period === "1year") from.setFullYear(from.getFullYear() - 1);
    return { from: localDateStr(from), to };
  }, [period, customRange]);

  const fetchSheets = useCallback(async () => {
    setSheetsLoading(true);
    setSheetsError("");
    try {
      const res = await api.fetchRaw(
        `/ceo-dashboard/sheets-data?tab=all&start=${effectiveRange.from}&end=${effectiveRange.to}`
      );
      if (res.ok) {
        const d = await res.json();
        if (!d.error) setSheetsData(d);
      } else {
        setSheetsError("Failed to load dashboard data");
      }
    } catch {
      setSheetsError("Failed to load dashboard data");
    }
    setSheetsLoading(false);
  }, [effectiveRange]);

  const fetchMcpLive = useCallback(async () => {
    setMcpLiveLoading(true);
    try {
      // Reads today's revenue from our own database (kept fresh by the
      // regular background sync) instead of calling MCP directly — see
      // sales_report_service.get_live_today_revenue.
      const res = await api.fetchRaw(`/sales-reports/live-today?country=${encodeURIComponent(selectedCountry)}`);
      if (res.ok) {
        const d = await res.json();
        setTodayLiveRevenue(d.revenue || 0);
      }
    } catch {}
    setMcpLiveLoading(false);
  }, [selectedCountry]);

  const fetchCountryComparison = useCallback(async () => {
    setCountryLoading(true);
    try {
      // Reads the snapshot saved during the last sync (MCP does its own
      // USD conversion at that moment) instead of calling MCP directly —
      // see sales_report_service.get_country_comparison_snapshot.
      const res = await api.fetchRaw(`/sales-reports/country-comparison`);
      if (res.ok) setCountryData(await res.json());
    } catch {}
    setCountryLoading(false);
  }, []);

  const fetchMcpReports = useCallback(async () => {
    setMcpReportLoading(true);
    setMcpReportError("");
    try {
      const params = `granularity=day&country=${encodeURIComponent(selectedCountry)}&start=${effectiveRange.from}&end=${effectiveRange.to}`;
      const [tlRes, branchRes] = await Promise.all([
        api.fetchRaw(`/sales-reports?group_by=team_leader&${params}`),
        api.fetchRaw(`/sales-reports?group_by=branch&${params}`),
      ]);
      if (tlRes.ok) setMcpTlReport(await tlRes.json());
      else setMcpReportError("Couldn't load live sales data.");
      if (branchRes.ok) setMcpBranchReport(await branchRes.json());
    } catch {
      setMcpReportError("Couldn't load live sales data.");
    }
    setMcpReportLoading(false);
  }, [effectiveRange, selectedCountry]);

  const fetchStock = useCallback(async () => {
    setStockLoading(true);
    setStockError("");
    try {
      const res = await api.fetchRaw(`/mcp/stock/position?country_id=${stockCountryId}`);
      if (res.ok) {
        setStockData(await res.json());
      } else if (res.status === 403) {
        setStockError("You don't have access to view stock data.");
      } else {
        setStockError("Couldn't reach the stock system — try refreshing.");
      }
    } catch {
      setStockError("Couldn't reach the stock system — try refreshing.");
    }
    setStockLoading(false);
  }, [stockCountryId]);

  const fetchBranches = useCallback(async () => {
    setBranchesLoading(true);
    try {
      // Scoped to the same period as everything else on the page, so this
      // list changes when Today / 7 Days / Month / Custom is picked.
      const res = await api.fetchRaw(`/mcp/branches?start=${effectiveRange.from}&end=${effectiveRange.to}`);
      if (res.ok) setBranchesData(await res.json());
    } catch {}
    setBranchesLoading(false);
  }, [effectiveRange]);

  const fetchSyncStatus = useCallback(async () => {
    try {
      const res = await api.fetchRaw("/sync/mcp/status");
      if (res.ok) {
        const d = await res.json();
        setLastSyncedAt(d.last_synced_at || null);
      }
    } catch {}
  }, []);

  const handleSync = useCallback(async () => {
    setSyncing(true);
    setSyncError("");
    try {
      const res = await api.fetchRaw("/sync/mcp", { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Sync failed");
      }
      await Promise.all([
        fetchMcpLive(),
        fetchCountryComparison(),
        fetchMcpReports(),
        fetchBranches(),
        fetchStock(),
        fetchSyncStatus(),
      ]);
    } catch (e: any) {
      setSyncError(e.message || "Sync failed");
    }
    setSyncing(false);
  }, [fetchMcpLive, fetchCountryComparison, fetchMcpReports, fetchBranches, fetchStock, fetchSyncStatus]);

  useEffect(() => {
    fetchSheets();
    fetchMcpLive();
    fetchCountryComparison();
    fetchMcpReports();
    fetchBranches();
    fetchSyncStatus();
  }, [fetchSheets, fetchMcpLive, fetchCountryComparison, fetchMcpReports, fetchBranches, fetchSyncStatus]);

  useEffect(() => {
    fetchStock();
  }, [fetchStock]);

  const activeData = sheetsData;
  const activeLoading = sheetsLoading;

  // Same shape as the old Sheets-only processOpsData() result, but built
  // from the live MCP sales report (McpDailySale joined to
  // Store.team_leader_id) so it's populated for Today/7 Days too — Sheets
  // submissions are sparse/manual and often have nothing for a narrow
  // recent window even though real sales happened. Walk-ins/conversions
  // still come from Sheets under the hood; /sales-reports already blends
  // that in per store, so nothing else has to change here.
  const ops = useMemo(() => {
    if (!mcpTlReport || !mcpBranchReport) return null;

    // Branches with no monthly target set can't have a meaningful
    // achievement % (the backend reports 0% for them, same as a branch
    // that's genuinely failing) — that includes leftover placeholder rows
    // ("Store Name", the "<City> Store" template batch, "Online", etc.) as
    // well as any real branch that hasn't had a target configured yet.
    // Excluding them here keeps this ranking limited to branches it's
    // actually meaningful to rank; their revenue still counts everywhere
    // else on the dashboard, this only affects this one chart's list.
    const storeAchievements = (mcpBranchReport.breakdown || [])
      .filter((r: any) => r.target > 0)
      .map((r: any) => ({
        store: r.key, mtd: r.revenue, target: r.target, achPct: r.achievement_pct,
        walkins: r.walkins, sales: r.conversions,
        convPct: r.walkins > 0 ? Math.round((r.conversions / r.walkins) * 100) : 0,
      }))
      .sort((a: any, b: any) => b.achPct - a.achPct);

    const TL_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#06b6d4", "#f97316"];
    const tlList = (mcpTlReport.breakdown || [])
      .map((r: any, i: number) => ({
        name: r.key, target: r.target, achieved: r.revenue,
        walkins: r.walkins, conv: r.conversions, stores: r.stores || [],
        achPct: r.achievement_pct,
        convPct: r.walkins > 0 ? Math.round((r.conversions / r.walkins) * 100) : 0,
        color: TL_COLORS[i % TL_COLORS.length],
      }))
      .sort((a: any, b: any) => b.achPct - a.achPct);

    const rag = { green: 0, amber: 0, red: 0 };
    for (const sa of storeAchievements) {
      if (sa.achPct >= 65) rag.green++;
      else if (sa.achPct >= 35) rag.amber++;
      else rag.red++;
    }

    return {
      storeAchievements, tlList,
      totalRevenue: mcpTlReport.total_revenue, totalTarget: mcpTlReport.total_target,
      totalWalkins: mcpTlReport.total_walkins, totalConversions: mcpTlReport.total_conversions,
      overallAch: mcpTlReport.achievement_pct,
      overallConv: mcpTlReport.total_walkins > 0
        ? Math.round((mcpTlReport.total_conversions / mcpTlReport.total_walkins) * 100) : 0,
      rag,
      needsReview: mcpBranchReport.needs_review || [],
    };
  }, [mcpTlReport, mcpBranchReport]);


  // Derive KPI data from sheets
  const kpiData = useMemo(() => {
    if (!ops) return null;
    const totalRevenue = ops.totalRevenue;
    const totalTarget = ops.totalTarget;
    const achievementPct = ops.overallAch;
    return { totalRevenue, totalTarget, achievementPct };
  }, [ops]);

  // Revenue vs Target vs Achieved trend from ops_data grouped by date, across
  // all branches. kpiData.totalTarget is already the correct total target
  // for the selected range (the backend prorates each store's static
  // monthly_target by the range length), so the daily pace is just that
  // total divided evenly across the days in the range.
  const revenueTrend = useMemo(() => {
    if (!kpiData) return [];
    const dateMap: Record<string, number> = {};
    for (const r of (mcpTlReport?.trend || [])) {
      dateMap[r.period] = (dateMap[r.period] || 0) + (r.revenue || 0);
    }
    // Walk every day in the selected range, not just the days that had a
    // submission — otherwise a sparsely-synced period (e.g. one real day out
    // of a whole month) renders as an isolated dot with no line to connect it.
    const dates: string[] = [];
    const cursor = new Date(effectiveRange.from);
    const end = new Date(effectiveRange.to);
    while (cursor <= end) {
      dates.push(localDateStr(cursor));
      cursor.setDate(cursor.getDate() + 1);
    }
    if (!dates.length) return [];
    const dailyTarget = kpiData.totalTarget / Math.max(dates.length, 1);
    // Achieved % as a running cumulative-to-date attainment curve, not the
    // same day's revenue rescaled against a flat target — otherwise it just
    // traces the same shape as the Revenue line and the two are impossible
    // to tell apart on the chart.
    let cumRevenue = 0;
    let cumTarget = 0;
    return dates.map((date) => {
      const revenue = dateMap[date] || 0;
      cumRevenue += revenue;
      cumTarget += dailyTarget;
      return {
        date, revenue, target: dailyTarget,
        achievedPct: cumTarget > 0 ? Math.round((cumRevenue / cumTarget) * 100) : 0,
      };
    });
  }, [mcpTlReport, kpiData, effectiveRange]);

  // Revenue breakdown by TL, from the live MCP team-leader report
  const revenueBreakdown = useMemo(() => {
    if (!ops) return [];
    return ops.tlList
      .map((tl: any) => ({ name: tl.name, value: tl.achieved }))
      .filter((x: any) => x.value > 0)
      .sort((a: any, b: any) => b.value - a.value);
  }, [ops]);

  // Top team leaders from ops_data
  const topTeamLeaders = useMemo(() => {
    if (!ops) return [];
    return ops.tlList.map((tl: any) => ({
      name: tl.name,
      revenue: tl.achieved,
      target: tl.target,
      achievement: tl.achPct,
      active_leads: 0,
    }));
  }, [ops]);

  // Lead distribution from ops_data
  const leadDistribution = useMemo(() => {
    const opsData = activeData?.ops_data || [];
    if (!opsData.length) return [];
    const totalLeads = opsData.reduce((s: number, r: any) => s + (r.new_leads || 0), 0);
    const activeLeads = opsData.reduce((s: number, r: any) => s + (r.active_leads || 0), 0);
    const callsMade = opsData.reduce((s: number, r: any) => s + (r.calls_made || 0), 0);
    const callsConnected = opsData.reduce((s: number, r: any) => s + (r.calls_connected || 0), 0);
    return [
      { name: "Active Leads", value: activeLeads },
      { name: "New Leads", value: totalLeads },
      { name: "Calls Made", value: callsMade },
      { name: "Calls Connected", value: callsConnected },
    ];
  }, [activeData]);

  // Marketing data from daily_tracker (xlsx)
  const marketingData = useMemo(() => {
    const tracker = activeData?.daily_tracker || [];
    if (!tracker.length) return null;

    // tracker rows are ordered by date desc, so the first row seen per store
    // is its latest snapshot — mtd_revenue is already a cumulative running
    // total as of that date, so it must be read once, never summed across days.
    const storeMap: Record<string, any> = {};
    for (const r of tracker) {
      const s = r.store;
      if (!s) continue;
      if (!storeMap[s]) {
        storeMap[s] = {
          store: s, country: r.country, storeType: r.store_type,
          dailyRevenue: 0, mtdRevenue: r.mtd_revenue || 0, monthlyTarget: r.monthly_target || 0, unitsSold: 0, carePlus: 0, prebookings: 0,
          igVideos: 0, igViewsTarget: 0, igViewsAchieved: 0, igFollowers: 0, igNewFollowers: 0,
          igLikes: 0, igComments: 0, igSaves: 0, igShares: 0, igDms: 0, igPosts: 0,
          ytViews: 0, ytLikes: 0, ytComments: 0,
          ttViews: 0, ttLikes: 0, ttFollowers: 0,
          scViews: 0, scShares: 0,
          waChats: 0, waWalkins: 0,
          googleRating: null as number | null, googleReviews: 0,
        };
      }
      const m = storeMap[s];
      m.dailyRevenue += r.daily_revenue || 0;
      m.unitsSold += r.units_sold || 0;
      m.carePlus += r.care_plus_attached || 0;
      m.prebookings += r.prebookings || 0;
      m.igVideos += r.ig_videos_posted || 0;
      m.igViewsTarget += r.ig_views_target || 0;
      m.igViewsAchieved += r.ig_views_achieved || 0;
      m.igFollowers = r.ig_followers || m.igFollowers;
      m.igNewFollowers += r.ig_new_followers || 0;
      m.igLikes += r.ig_likes || 0;
      m.igComments += r.ig_comments || 0;
      m.igSaves += r.ig_saves || 0;
      m.igShares += r.ig_shares || 0;
      m.igDms += r.ig_dms_received || 0;
      m.igPosts += r.ig_posts_published || 0;
      m.ytViews += r.yt_views || 0;
      m.ytLikes += r.yt_likes || 0;
      m.ytComments += r.yt_comments || 0;
      m.ttViews += r.tt_views || 0;
      m.ttLikes += r.tt_likes || 0;
      m.ttFollowers = r.tt_followers || m.ttFollowers;
      m.scViews += r.sc_views || 0;
      m.scShares += r.sc_shares || 0;
      m.waChats += r.wa_chats_received || 0;
      m.waWalkins += r.wa_walkins_booked || 0;
      if (r.google_rating) m.googleRating = r.google_rating;
      m.googleReviews += r.google_new_reviews || 0;
    }

    const stores = Object.values(storeMap);
    const totals = stores.reduce((acc, s) => ({
      mtdRevenue: acc.mtdRevenue + s.mtdRevenue,
      monthlyTarget: acc.monthlyTarget + s.monthlyTarget,
      totalViews: acc.totalViews + s.igViewsAchieved + s.ytViews + s.ttViews + s.scViews,
      totalEngagements: acc.totalEngagements + s.igLikes + s.igComments + s.igSaves + s.igShares + s.ytLikes + s.ttLikes,
      totalDms: acc.totalDms + s.igDms,
      totalWaChats: acc.totalWaChats + s.waChats,
      totalWaWalkins: acc.totalWaWalkins + s.waWalkins,
      totalPrebookings: acc.totalPrebookings + s.prebookings,
      totalGoogleReviews: acc.totalGoogleReviews + s.googleReviews,
    }), { mtdRevenue: 0, monthlyTarget: 0, totalViews: 0, totalEngagements: 0, totalDms: 0, totalWaChats: 0, totalWaWalkins: 0, totalPrebookings: 0, totalGoogleReviews: 0 });

    const socialByPlatform = [
      { name: "Instagram", views: stores.reduce((s, st) => s + st.igViewsAchieved, 0), engagements: stores.reduce((s, st) => s + st.igLikes + st.igComments + st.igSaves + st.igShares, 0), color: "#E1306C" },
      { name: "YouTube", views: stores.reduce((s, st) => s + st.ytViews, 0), engagements: stores.reduce((s, st) => s + st.ytLikes + st.ytComments, 0), color: "#FF0000" },
      { name: "TikTok", views: stores.reduce((s, st) => s + st.ttViews, 0), engagements: stores.reduce((s, st) => s + st.ttLikes, 0), color: "#00f2ea" },
      { name: "Snapchat", views: stores.reduce((s, st) => s + st.scViews, 0), engagements: stores.reduce((s, st) => s + st.scShares, 0), color: "#FFFC00" },
    ];

    return { stores, totals, socialByPlatform };
  }, [activeData]);

  if (!activeLoading && !activeData) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-center p-6 bg-[var(--bg-card)] border border-[var(--border-subtle)] rounded-2xl">
        <AlertTriangle size={36} className="text-rose-400 mb-3" />
        <h3 className="text-base font-semibold text-white mb-1">Failed to load dashboard data</h3>
        <p className="text-xs text-[var(--text-muted)]">Please check backend connection or refresh.</p>
      </div>
    );
  }

  const kpiCards = kpiData
    ? [
        { title: "Total Revenue", value: kpiData.totalRevenue, type: "money" as const, icon: <DollarSign size={20} />, color: "#3b82f6", badge: !mcpLiveLoading && todayLiveRevenue > 0 ? `LIVE Today: ₹${fmtINR(todayLiveRevenue).replace("₹", "")}` : null },
        { title: "Total Target", value: kpiData.totalTarget, type: "money" as const, icon: <Target size={20} />, color: "#10b981" },
        { title: "Achievement %", value: kpiData.achievementPct, type: "percent" as const, icon: <TrendingUp size={20} />, color: "#a855f7" },
        { title: "Total Investment", value: 0, type: "money" as const, icon: <Briefcase size={20} />, color: "#f97316" },
        { title: "Active Team Leaders", value: ops?.tlList.length || 0, type: "number" as const, icon: <Users size={20} />, color: "#ec4899" },
        { title: "Active Leads", value: ops?.totalWalkins || 0, type: "number" as const, icon: <Phone size={20} />, color: "#06b6d4" },
      ]
    : [];

  const gaugeData = kpiData ? [{ name: "Achievement", value: kpiData.achievementPct, fill: "#a855f7" }] : [];
  const hasRevenueBreakdown = revenueBreakdown.length > 0;
  const hasLeadDistribution = leadDistribution.some((x) => x.value > 0);

  return (
    <ErrorBoundary>
      <div className="space-y-6 w-full min-w-0">


        {tab === "summary" && (
          <AISummary />
        )}

        {tab === "dashboard" && (
          <div className="space-y-6 w-full min-w-0">
            {/* Period header */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-bold text-white">
                  {new Date().toLocaleDateString("en-IN", { month: "long", year: "numeric" })}
                </h2>
                <p className="text-xs text-[var(--text-muted)]">
                  Today: {new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}
                  {" · "}Showing {effectiveRange.from} to {effectiveRange.to}
                </p>
              </div>
            </div>

            {/* MCP Sync Bar */}
            <div className="flex flex-wrap items-center justify-between gap-3 bg-[var(--bg-card)] border border-[var(--border-subtle)] p-3 rounded-2xl">
              <div className="text-xs text-[var(--text-muted)]">
                {lastSyncedAt
                  ? `Sales data last synced from MCP: ${new Date(lastSyncedAt).toLocaleString()}`
                  : "Sales data has not been synced from MCP yet"}
                {syncError && <span className="ml-2 text-rose-400">{syncError}</span>}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative">
                  <select
                    value={selectedCountry}
                    onChange={(e) => setSelectedCountry(e.target.value)}
                    className="appearance-none pl-3 pr-8 py-2 rounded-xl text-xs font-medium border border-[var(--border-subtle)] bg-white/5 text-[var(--text-secondary)] hover:text-white focus:outline-none focus:border-blue-500 cursor-pointer"
                    title="Country — filters Revenue, Achievement, Store/TL charts and Live Today below to this country"
                  >
                    {COUNTRY_OPTIONS.map((c) => (
                      <option key={c} value={c} className="bg-[var(--bg-card)] text-[var(--text-primary)]">{c}</option>
                    ))}
                  </select>
                  <Globe size={12} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
                </div>
                <div className="flex items-center rounded-xl border border-[var(--border-subtle)] bg-white/5 p-0.5">
                  {([
                    { key: "1day", label: "Today" },
                    { key: "7day", label: "7 Days" },
                    { key: "month", label: "Month" },
                    { key: "6month", label: "6 Month" },
                    { key: "1year", label: "1 Year" },
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
                <button
                  onClick={handleSync}
                  disabled={syncing}
                  className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-[var(--accent-blue)] text-white hover:opacity-90 transition disabled:opacity-50"
                >
                  <RefreshCw size={14} className={syncing ? "animate-spin" : ""} />
                  {syncing ? "Syncing..." : "Sync Latest Sales"}
                </button>
              </div>
            </div>

            {/* KPI Cards Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4 min-w-0">
              {activeLoading
            ? Array.from({ length: 6 }).map((_, i) => <StatCardSkeleton key={i} />)
            : kpiCards.map((card, i) => <StatCard key={i} {...card} />)}
        </div>

        {branchesData.length > 0 && (
          <ErrorBoundary>
            <Suspense fallback={<div className="h-[480px] rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] animate-pulse" />}>
              <BranchGlobe branches={branchesData} />
            </Suspense>
          </ErrorBoundary>
        )}

        {/* Charts Grid: Revenue Trend & Gauge */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 min-w-0">
          <div className="lg:col-span-2 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 flex flex-col justify-between min-w-0">
            <div className="flex items-start justify-between mb-4">
              <div>
                <h3 className="text-base font-bold text-white tracking-tight flex items-center gap-2">
                  Revenue vs Target Trend
                  {trendFilter.dateMode !== "all" && (
                    <span className="text-[10px] bg-blue-500/20 text-blue-300 border border-blue-500/30 px-2 py-0.5 rounded-full font-medium">
                      {trendFilter.dateMode === "3day"
                        ? "Last 3 Days"
                        : trendFilter.dateMode === "7day"
                        ? "Last 7 Days"
                        : trendFilter.dateMode === "30day"
                        ? "Last 30 Days"
                        : "Filtered"}
                    </span>
                  )}
                </h3>
                <p className="text-xs text-[var(--text-muted)] mt-0.5">Daily revenue, target pace, and cumulative achievement % across all branches</p>
              </div>
              <CardFilterPopover
                filter={trendFilter}
                onFilterChange={setTrendFilter}
              />
            </div>
            {mcpReportLoading ? (
              <div className="h-72 sm:h-80 animate-pulse bg-[var(--border-subtle)]/30 rounded-xl" />
            ) : !ops ? (
              <div className="h-72 sm:h-80 flex items-center justify-center text-sm text-[var(--text-muted)] text-center px-6">
                {mcpReportError || "No sales data for this period yet"}
              </div>
            ) : (
              <div className="h-72 sm:h-80 w-full min-w-0">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={applyCardFilter(revenueTrend, trendFilter)} margin={{ top: 12, right: 15, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                    <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#a1a1aa" }} tickFormatter={(v) => String(v).slice(5)} />
                    <YAxis
                      yAxisId="amount" domain={["auto", "auto"]} width={48}
                      tick={{ fontSize: 11, fill: "#93c5fd" }} tickFormatter={(v) => fmtINR(v)}
                    />
                    <YAxis
                      yAxisId="pct" orientation="right" domain={[0, "auto"]} width={42}
                      tick={{ fontSize: 11, fill: "#fbbf24" }} tickFormatter={(v) => `${v}%`}
                    />
                    <Tooltip
                      contentStyle={{ backgroundColor: "var(--bg-card)", borderColor: "var(--border-subtle)", borderRadius: "12px", fontSize: "12px", color: "var(--text-primary)" }}
                      labelStyle={{ color: "var(--text-primary)", fontWeight: 700, marginBottom: 4 }}
                      itemStyle={{ fontWeight: 600, color: "var(--text-primary)" }}
                      formatter={(value: any, name?: any) => (name === "Achieved %" ? [`${value}%`, name] : [fmtINR(Number(value)), name])}
                    />
                    <Legend wrapperStyle={{ fontSize: 12, fontWeight: 600, color: "#e5e7eb", paddingTop: 8 }} iconType="line" />
                    <Line
                      yAxisId="amount" type="monotone" dataKey="revenue" name="Revenue"
                      stroke="#3b82f6" strokeWidth={3.5}
                      dot={{ r: 4, fill: "#3b82f6", strokeWidth: 0 }} activeDot={{ r: 7 }}
                    />
                    <Line
                      yAxisId="amount" type="monotone" dataKey="target" name="Target"
                      stroke="#10b981" strokeWidth={3.5}
                      dot={{ r: 4, fill: "#10b981", strokeWidth: 0 }} activeDot={{ r: 7 }}
                    />
                    <Line
                      yAxisId="pct" type="monotone" dataKey="achievedPct" name="Achieved %"
                      stroke="#f59e0b" strokeWidth={3.5}
                      dot={{ r: 4, fill: "#f59e0b", strokeWidth: 0 }} activeDot={{ r: 7 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 flex flex-col justify-between min-w-0">
            <div>
              <h3 className="text-base font-bold text-white tracking-tight">Overall Achievement Rate</h3>
              <p className="text-xs text-[var(--text-muted)] mb-4">Target fulfillment for the selected period</p>
            </div>
            {mcpReportLoading ? (
              <div className="h-64 sm:h-72 animate-pulse bg-[var(--border-subtle)]/30 rounded-xl" />
            ) : !ops ? (
              <div className="h-64 sm:h-72 flex items-center justify-center text-sm text-[var(--text-muted)] text-center px-6">
                {mcpReportError || "No sales data for this period yet"}
              </div>
            ) : (
              <div className="h-64 sm:h-72 w-full min-w-0 flex items-center justify-center relative">
                <ResponsiveContainer width="100%" height="100%">
                  <RadialBarChart cx="50%" cy="50%" innerRadius="65%" outerRadius="95%" barSize={18} data={gaugeData} startAngle={180} endAngle={0}>
                    <RadialBar dataKey="value" cornerRadius={10} />
                  </RadialBarChart>
                </ResponsiveContainer>
                <div className="absolute inset-0 flex flex-col items-center justify-center top-6">
                  <span className="text-3xl font-extrabold text-white tracking-tight">{(kpiData?.achievementPct || 0).toFixed(1)}%</span>
                  <span className="text-xs text-[var(--text-muted)] font-medium mt-1">Goal Completed</span>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* ══════════ CEO OVERVIEW: Store Achievement + TL Achievement ══════════ */}
        {!mcpReportLoading && !ops && (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-8 text-center text-[var(--text-muted)] text-sm">
            {mcpReportError || `No sales data for ${effectiveRange.from === effectiveRange.to ? effectiveRange.from : `${effectiveRange.from} to ${effectiveRange.to}`} yet.`}
          </div>
        )}
        {ops && ops.needsReview && ops.needsReview.length > 0 && (
          <div className="flex items-center justify-between gap-3 p-4 rounded-2xl bg-amber-500/10 border border-amber-500/25 text-amber-300 text-sm">
            <span className="flex items-center gap-2">
              <AlertTriangle size={16} />
              {ops.needsReview.length} branch{ops.needsReview.length > 1 ? "es" : ""} synced from MCP need a team leader assignment (excluded from {selectedCountry} Revenue/TL Achievement below).
            </span>
            <Link
              to="/settings/branch-assignment"
              className="shrink-0 px-3 py-1.5 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-xs font-semibold"
            >
              Review Branches
            </Link>
          </div>
        )}
        {ops && (
          <>
            {/* CEO KPI Row */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 min-w-0">
              {[
                { label: `${selectedCountry} Revenue`, value: fmtINR(ops.totalRevenue), sub: `vs ${fmtINR(ops.totalTarget)} target`, color: "#3b82f6" },
                { label: `${selectedCountry} Achievement`, value: `${ops.overallAch}%`, sub: `${ops.tlList.length} TLs \u00b7 ${ops.storeAchievements.length} stores`, color: ops.overallAch >= 50 ? "#10b981" : "#f59e0b" },
                { label: "Walk-ins", value: ops.totalWalkins.toLocaleString(), sub: `${ops.totalConversions} conversions \u00b7 ${ops.overallConv}%`, color: "#10b981" },
                { label: "Critical Stores", value: String(ops.rag.red), sub: `${ops.rag.red} below 35% target`, color: "#ef4444" },
              ].map((k, i) => (
                <div key={i} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 relative overflow-hidden">
                  <div className="absolute top-0 left-0 right-0 h-0.5" style={{ background: k.color }} />
                  <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] mb-1">{k.label}</p>
                  <p className="text-xl font-extrabold text-white">{k.value}</p>
                  <p className="text-[11px] text-[var(--text-muted)] mt-0.5">{k.sub}</p>
                </div>
              ))}
            </div>

            {/* Store Achievement + TL Achievement Charts */}
            <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 min-w-0">
              <div className="lg:col-span-3 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 min-w-0">
                <div className="flex flex-wrap items-start justify-between gap-2 mb-1">
                  <div>
                    <h3 className="text-sm font-bold text-white tracking-tight mb-1">{selectedCountry} Store MTD Achievement %</h3>
                    <p className="text-xs text-[var(--text-muted)]">All {ops.storeAchievements.length} {selectedCountry} stores ranked by performance</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[var(--text-secondary)] shrink-0">
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ background: "#10b981" }} />On Track (65%+)</span>
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ background: "#f59e0b" }} />Below Target (35-64%)</span>
                    <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full" style={{ background: "#ef4444" }} />Critical (&lt;35%)</span>
                  </div>
                </div>
                <div className="h-[420px] w-full min-w-0 mt-3">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={ops.storeAchievements} layout="vertical" margin={{ left: 5, right: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                      <XAxis type="number" domain={[0, 120]} tick={{ fontSize: 10, fill: "#a1a1aa" }} tickFormatter={(v) => `${v}%`} />
                      <YAxis type="category" dataKey="store" tick={{ fontSize: 9, fill: "#a1a1aa" }} width={120} tickFormatter={shortStore} />
                      <Tooltip
                        formatter={(v: any) => [`${v}% — ${ragLabel(Number(v))}`, "Achievement"]}
                        contentStyle={{ backgroundColor: "var(--bg-card)", borderColor: "var(--border-subtle)", borderRadius: "12px", fontSize: "12px" }}
                        labelStyle={{ color: "var(--text-primary)" }}
                        itemStyle={{ color: "var(--text-primary)" }}
                      />
                      <Bar dataKey="achPct" radius={[0, 4, 4, 0]} label={{ position: "right", fontSize: 9, fill: "var(--text-secondary)", formatter: (v: any) => ragLabel(Number(v)) }}>
                        {ops.storeAchievements.map((s: any, i: number) => <Cell key={i} fill={ragColor(s.achPct)} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="lg:col-span-2 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 min-w-0">
                <h3 className="text-sm font-bold text-white tracking-tight mb-1">TL Achievement %</h3>
                <p className="text-xs text-[var(--text-muted)] mb-4">Team leader performance ranking</p>
                <div className="h-[420px] w-full min-w-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={ops.tlList.map((t: any) => ({ name: t.name, achPct: t.achPct, color: t.color }))}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                      <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#a1a1aa" }} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: "#a1a1aa" }} tickFormatter={(v) => `${v}%`} />
                      <Tooltip formatter={(v: any) => [`${v}% — ${ragLabel(Number(v))}`, "Achievement"]} contentStyle={{ backgroundColor: "var(--bg-card)", borderColor: "var(--border-subtle)", borderRadius: "12px", fontSize: "12px" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} />
                      <Bar dataKey="achPct" radius={[6, 6, 0, 0]}>
                        {ops.tlList.map((t: any, i: number) => <Cell key={i} fill={ragColor(t.achPct)} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>

            {/* RAG Donut + TL Target vs Achieved + Walk-ins */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 min-w-0">
              <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 min-w-0">
                <h3 className="text-sm font-bold text-white tracking-tight mb-1">RAG Status Distribution</h3>
                <p className="text-xs text-[var(--text-muted)] mb-4">Store health overview</p>
                <div className="h-56 w-full min-w-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={[{ name: "Green \u226565%", value: ops.rag.green }, { name: "Amber 35\u201364%", value: ops.rag.amber }, { name: "Red <35%", value: ops.rag.red }]} cx="50%" cy="50%" innerRadius={45} outerRadius={75} dataKey="value" stroke="#11131e" strokeWidth={2}>
                        <Cell fill="#10b981" /><Cell fill="#f59e0b" /><Cell fill="#ef4444" />
                      </Pie>
                      <Tooltip contentStyle={{ backgroundColor: "var(--bg-card)", borderColor: "var(--border-subtle)", borderRadius: "12px", fontSize: "12px" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} />
                      {/* A bare <Legend> next to a single <Pie> doesn't reliably map
                          each slice's color to its label — passing an explicit
                          payload guarantees the right color swatch next to the
                          right label, with the actual store count included. */}
                      <Legend
                        wrapperStyle={{ fontSize: 11, color: "#a1a1aa" }}
                        {...({
                          payload: [
                            { value: `Green ≥65% (${ops.rag.green} stores)`, type: "square", color: "#10b981" },
                            { value: `Amber 35–64% (${ops.rag.amber} stores)`, type: "square", color: "#f59e0b" },
                            { value: `Red <35% (${ops.rag.red} stores)`, type: "square", color: "#ef4444" },
                          ],
                        } as any)}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 min-w-0">
                <h3 className="text-sm font-bold text-white tracking-tight mb-1">TL Target vs Achieved (\u20b9 Lakhs)</h3>
                <p className="text-xs text-[var(--text-muted)] mb-4">Monthly comparison</p>
                <div className="h-56 w-full min-w-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={ops.tlList.map((t: any) => ({ name: t.name, target: +(t.target / 100000).toFixed(1), achieved: +(t.achieved / 100000).toFixed(1) }))}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                      <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#a1a1aa" }} />
                      <YAxis tick={{ fontSize: 10, fill: "#a1a1aa" }} tickFormatter={(v) => `\u20b9${v}L`} />
                      <Tooltip contentStyle={{ backgroundColor: "var(--bg-card)", borderColor: "var(--border-subtle)", borderRadius: "12px", fontSize: "12px" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} formatter={(v: any) => `\u20b9${v}L`} />
                      <Legend wrapperStyle={{ fontSize: 11, color: "#a1a1aa" }} />
                      <Bar dataKey="target" fill="#374151" radius={[4, 4, 0, 0]} />
                      <Bar dataKey="achieved" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 min-w-0">
                <h3 className="text-sm font-bold text-white tracking-tight mb-1">WhatsApp Walk-ins \u2014 Top Stores</h3>
                <p className="text-xs text-[var(--text-muted)] mb-4">Marketing channel performance</p>
                <div className="h-56 w-full min-w-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={[...ops.storeAchievements].filter((s: any) => s.walkins > 0).sort((a: any, b: any) => b.walkins - a.walkins).slice(0, 12).map((s: any) => ({ name: shortStore(s.store), walkins: s.walkins }))} layout="vertical" margin={{ left: 5, right: 20 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                      <XAxis type="number" tick={{ fontSize: 10, fill: "#a1a1aa" }} />
                      <YAxis type="category" dataKey="name" tick={{ fontSize: 9, fill: "#a1a1aa" }} width={90} />
                      <Tooltip contentStyle={{ backgroundColor: "var(--bg-card)", borderColor: "var(--border-subtle)", borderRadius: "12px", fontSize: "12px" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} />
                      <Bar dataKey="walkins" fill="#25d366" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>

            {/* TL Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 min-w-0">
              {ops.tlList.map((tl: any, i: number) => (
                <div key={i} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 relative overflow-hidden">
                  <div className="absolute top-0 left-0 right-0 h-0.5" style={{ background: tl.color }} />
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-sm font-bold text-white">{tl.name}</span>
                    <span className="text-xl font-extrabold" style={{ color: tl.color }}>{tl.achPct}%</span>
                  </div>
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[var(--text-muted)] mb-3">
                    <span>{"\ud83c\udfaf"} {fmtINR(tl.target)}</span>
                    <span>{"\u2705"} {fmtINR(tl.achieved)}</span>
                    <span>{"\ud83d\udc63"} {tl.walkins} walkins</span>
                    <span>{"\ud83e\udd1d"} {tl.conv} conv ({tl.convPct}%)</span>
                  </div>
                  <div className="w-full bg-[var(--border-subtle)] rounded-full h-2 overflow-hidden mb-2">
                    <div className="h-full rounded-full" style={{ width: `${Math.min(tl.achPct, 100)}%`, background: tl.color }} />
                  </div>
                  <p className="text-[11px] text-[var(--text-muted)]">Stores: <span className="text-[var(--text-secondary)]">{tl.stores.join(", ")}</span></p>
                </div>
              ))}
            </div>
          </>
        )}

        {/* ══════════ INTERNATIONAL SALES (MCP Live) ══════════ */}
        {countryData.length > 0 && (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <Globe className="text-emerald-400" size={20} />
              <h3 className="text-base font-bold text-white tracking-tight">International Sales</h3>
              <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/25">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                Synced from MCP
              </span>
            </div>
            <p className="text-xs text-[var(--text-muted)] mb-4">Bars normalized to USD for comparison — figures below show each country's own currency, as of the last sync</p>
            {countryLoading ? (
              <div className="h-[300px] rounded-xl bg-[var(--border-subtle)]/20 animate-pulse" />
            ) : (
              <div className="h-[300px] w-full min-w-0">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={countryData} layout="vertical" margin={{ left: 10, right: 30 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis type="number" tick={{ fontSize: 10, fill: "#a1a1aa" }} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}K`} />
                    <YAxis type="category" dataKey="country" width={90} tick={{ fontSize: 11, fill: "#a1a1aa" }} />
                    <Tooltip
                      formatter={(v: any, _name: any, item: any) => [
                        `${fmtByCurrency(item?.payload?.local_amount || 0, item?.payload?.local_currency || "")} (≈ $${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2 })})`,
                        "Revenue",
                      ]}
                      contentStyle={{ backgroundColor: "var(--bg-card)", borderColor: "var(--border-subtle)", borderRadius: "12px", fontSize: "12px", color: "var(--text-primary)" }}
                      labelStyle={{ color: "var(--text-primary)" }}
                      itemStyle={{ color: "var(--text-primary)" }}
                    />
                    <Bar dataKey="usd_amount" radius={[0, 6, 6, 0]}>
                      {countryData.map((entry: any) => (
                        <Cell key={entry.country} fill={
                          entry.country?.toUpperCase() === "INDIA" ? "#3b82f6" :
                          entry.country?.toUpperCase() === "UAE" ? "#10b981" :
                          entry.country?.toUpperCase() === "OMAN" ? "#f59e0b" :
                          entry.country?.toUpperCase() === "QATAR" ? "#a855f7" :
                          entry.country?.toUpperCase() === "PAKISTAN" ? "#ef4444" :
                          entry.country?.toUpperCase() === "MALAYSIA" ? "#06b6d4" :
                          entry.country?.toUpperCase() === "UK" ? "#ec4899" :
                          entry.country?.toUpperCase() === "BAHRAIN" ? "#f97316" : "#6b7280"
                        } />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
            {/* Country summary cards */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 mt-4">
              {countryData.map((c: any) => (
                <div key={c.country} className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-card-hover)] p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-2.5 h-2.5 rounded-full" style={{
                      background: c.country?.toUpperCase() === "INDIA" ? "#3b82f6" :
                        c.country?.toUpperCase() === "UAE" ? "#10b981" :
                        c.country?.toUpperCase() === "OMAN" ? "#f59e0b" :
                        c.country?.toUpperCase() === "QATAR" ? "#a855f7" :
                        c.country?.toUpperCase() === "PAKISTAN" ? "#ef4444" :
                        c.country?.toUpperCase() === "MALAYSIA" ? "#06b6d4" :
                        c.country?.toUpperCase() === "UK" ? "#ec4899" :
                        c.country?.toUpperCase() === "BAHRAIN" ? "#f97316" : "#6b7280"
                    }} />
                    <span className="text-xs font-semibold text-white">{c.country}</span>
                  </div>
                  <p className="text-lg font-bold text-white">{fmtByCurrency(c.local_amount || 0, c.local_currency || "")}</p>
                  <p className="text-[10px] text-[var(--text-muted)]">≈ ${c.usd_amount?.toLocaleString(undefined, { maximumFractionDigits: 0 })} USD</p>
                  <p className="text-[10px] text-[var(--text-muted)]">{c.sales_count} sales · ${c.avg_ticket_usd?.toFixed(0)} avg (USD)</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ══════════ STOCK POSITION (MCP Live) ══════════ */}
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 min-w-0">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Package className="text-amber-400" size={20} />
              <h3 className="text-base font-bold text-white tracking-tight">Stock Position</h3>
              <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/25">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                LIVE from MCP
              </span>
            </div>
            <div className="flex items-center gap-2">
              <Filter size={14} className="text-[var(--text-muted)]" />
              <select
                value={stockCountryId}
                onChange={(e) => setStockCountryId(Number(e.target.value))}
                className="bg-[var(--bg-card)] border border-[var(--border-subtle)] rounded-lg px-3 py-1.5 text-xs text-white"
              >
                <option value={1}>India</option>
                <option value={2}>Oman</option>
                <option value={4}>UAE</option>
                <option value={5}>Malaysia</option>
                <option value={6}>UK</option>
                <option value={7}>Bahrain</option>
                <option value={8}>Qatar</option>
              </select>
            </div>
          </div>
          <p className="text-xs text-[var(--text-muted)] mb-4">Current inventory levels by shop</p>
          {stockLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="h-12 rounded-xl bg-[var(--border-subtle)]/20 animate-pulse" />
              ))}
            </div>
          ) : stockError ? (
            <div className="text-center py-8 text-amber-400 text-sm">{stockError}</div>
          ) : stockData.length === 0 ? (
            <div className="text-center py-8 text-[var(--text-muted)] text-sm">No stock data available</div>
          ) : (
            <div className="space-y-2">
              {/* Summary row */}
              <div className="flex gap-4 mb-3">
                <div className="text-center">
                  <p className="text-[10px] text-[var(--text-muted)] uppercase">Total Units</p>
                  <p className="text-lg font-bold text-white">{stockData.reduce((s: number, shop: any) => s + (shop.total_units || 0), 0).toLocaleString()}</p>
                </div>
                <div className="text-center">
                  <p className="text-[10px] text-[var(--text-muted)] uppercase">Shops</p>
                  <p className="text-lg font-bold text-white">{stockData.length}</p>
                </div>
                <div className="text-center">
                  <p className="text-[10px] text-[var(--text-muted)] uppercase">SKUs</p>
                  <p className="text-lg font-bold text-white">{stockData.reduce((s: number, shop: any) => s + (shop.items?.length || 0), 0)}</p>
                </div>
              </div>
              {stockData.map((shop: any) => (
                <div key={shop.shop} className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-card-hover)] overflow-hidden">
                  <button
                    onClick={() => {
                      setStockExpanded((prev) => {
                        const next = new Set(prev);
                        if (next.has(shop.shop)) next.delete(shop.shop);
                        else next.add(shop.shop);
                        return next;
                      });
                    }}
                    className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/5 transition-colors"
                  >
                    <div className="flex items-center gap-3">
                      <Package size={14} className="text-[var(--text-muted)]" />
                      <span className="text-sm font-medium text-white">{shop.shop}</span>
                    </div>
                    <div className="flex items-center gap-4">
                      <span className="text-xs text-[var(--text-muted)]">{shop.items?.length || 0} SKUs</span>
                      <span className={`text-sm font-bold ${(shop.total_units || 0) < 0 ? "text-red-400" : "text-emerald-400"}`}>
                        {shop.total_units || 0}
                      </span>
                    </div>
                  </button>
                  {stockExpanded.has(shop.shop) && shop.items && (
                    <div className="border-t border-[var(--border-subtle)]">
                      <table className="w-full">
                        <thead>
                          <tr className="text-[10px] text-[var(--text-muted)] uppercase">
                            <th className="text-left px-4 py-2">Model</th>
                            <th className="text-left px-4 py-2">Material</th>
                            <th className="text-left px-4 py-2">Position</th>
                            <th className="text-right px-4 py-2">Count</th>
                          </tr>
                        </thead>
                        <tbody>
                          {shop.items.map((item: any, i: number) => (
                            <tr key={i} className="border-t border-[var(--border-subtle)]/50 hover:bg-white/5">
                              <td className="px-4 py-1.5 text-xs text-white">{item.model}</td>
                              <td className="px-4 py-1.5 text-xs text-[var(--text-muted)]">{item.material}</td>
                              <td className="px-4 py-1.5 text-xs text-[var(--text-muted)]">{item.position}</td>
                              <td className={`px-4 py-1.5 text-xs text-right font-medium ${(item.count || 0) < 0 ? "text-red-400" : "text-emerald-400"}`}>
                                {item.count}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ══════════ ALL BRANCHES (MCP Live) ══════════ */}
        {branchesData.length > 0 && (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <MapPin className="text-cyan-400" size={20} />
              <h3 className="text-base font-bold text-white tracking-tight">All Branches</h3>
              <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/25">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                LIVE from MCP
              </span>
            </div>
            <p className="text-xs text-[var(--text-muted)] mb-4">
              {branchesData.length} branches across {new Set(branchesData.map((b: any) => b.country)).size} countries \u00b7 revenue and target for {effectiveRange.from === effectiveRange.to ? effectiveRange.from : `${effectiveRange.from} to ${effectiveRange.to}`}
            </p>

            {/* Summary cards by country */}
            <div className="flex flex-wrap gap-2 mb-4">
              {Object.entries(
                branchesData.reduce((acc: Record<string, number>, b: any) => {
                  acc[b.country] = (acc[b.country] || 0) + 1;
                  return acc;
                }, {})
              ).map(([country, count]) => (
                <span key={country} className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-white/5 border border-[var(--border-subtle)] text-[var(--text-secondary)]">
                  <span className="w-2 h-2 rounded-full" style={{
                    background: country === "India" ? "#3b82f6" :
                      country === "UAE" ? "#10b981" :
                      country === "Oman" ? "#f59e0b" :
                      country === "Qatar" ? "#a855f7" :
                      country === "Pakistan" ? "#ef4444" :
                      country === "Malaysia" ? "#06b6d4" :
                      country === "UK" ? "#ec4899" :
                      country === "Bahrain" ? "#f97316" : "#6b7280"
                  }} />
                  {country}: {count}
                </span>
              ))}
            </div>

            {branchesLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="h-14 rounded-xl bg-[var(--border-subtle)]/20 animate-pulse" />
                ))}
              </div>
            ) : (
              <div className="space-y-2">
                {Object.entries(
                  branchesData.reduce((acc: Record<string, any[]>, b: any) => {
                    if (!acc[b.country]) acc[b.country] = [];
                    acc[b.country].push(b);
                    return acc;
                  }, {})
                ).map(([country, shops]) => (
                  <div key={country}>
                    <button
                      onClick={() => {
                        setBranchesExpanded((prev) => {
                          const next = new Set(prev);
                          if (next.has(country)) next.delete(country);
                          else next.add(country);
                          return next;
                        });
                      }}
                      className="flex items-center justify-between w-full px-4 py-2.5 rounded-xl bg-white/5 border border-[var(--border-subtle)] hover:bg-white/8 transition-colors mb-1"
                    >
                      <div className="flex items-center gap-2">
                        <span className="w-2.5 h-2.5 rounded-full" style={{
                          background: country === "India" ? "#3b82f6" :
                            country === "UAE" ? "#10b981" :
                            country === "Oman" ? "#f59e0b" :
                            country === "Qatar" ? "#a855f7" :
                            country === "Pakistan" ? "#ef4444" :
                            country === "Malaysia" ? "#06b6d4" :
                            country === "UK" ? "#ec4899" :
                            country === "Bahrain" ? "#f97316" : "#6b7280"
                        }} />
                        <span className="text-sm font-semibold text-white">{country}</span>
                        <span className="text-xs text-[var(--text-muted)]">({shops.length} branches)</span>
                      </div>
                      <span className="text-xs text-[var(--text-muted)]">{branchesExpanded.has(country) ? "▲" : "▼"}</span>
                    </button>
                    {branchesExpanded.has(country) && (
                      <div className="ml-4 space-y-1 mt-1 mb-2">
                        {shops.map((b: any) => (
                          <div key={b.shop} className="flex items-center justify-between px-4 py-2.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-card-hover)] hover:bg-white/5 transition-colors">
                            <div className="flex items-center gap-3 min-w-0">
                              <Store size={14} className="text-[var(--text-muted)] shrink-0" />
                              <span className="text-sm font-medium text-white truncate">{b.shop}</span>
                              {b.status && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/25 shrink-0">
                                  {b.status}
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-4 shrink-0">
                              <div className="text-right">
                                <p className="text-[10px] text-[var(--text-muted)]">Target</p>
                                <p className="text-xs font-medium text-white">{b.target > 0 ? fmtByCountry(b.target, b.country) : "\u2014"}</p>
                              </div>
                              <div className="text-right">
                                <p className="text-[10px] text-[var(--text-muted)]">Achieved</p>
                                <p className="text-xs font-medium text-white">{b.actual > 0 ? fmtByCountry(b.actual, b.country) : "\u2014"}</p>
                              </div>
                              <div className="text-right w-12">
                                <p className="text-[10px] text-[var(--text-muted)]">Ach %</p>
                                <p
                                  className={`text-xs font-bold ${b.target > 0 ? (b.achievement_pct >= 65 ? "text-emerald-400" : b.achievement_pct >= 35 ? "text-amber-400" : "text-red-400") : "text-[var(--text-muted)]"}`}
                                  title={b.target > 0 ? "" : "No target is set for this branch, so there is no achievement %"}
                                >
                                  {b.target > 0 ? `${b.achievement_pct.toFixed(1)}%` : "\u2014"}
                                </p>
                              </div>
                              <div className="text-right">
                                <p className="text-[10px] text-[var(--text-muted)]">Stock</p>
                                <p className={`text-xs font-medium ${b.stock_units < 0 ? "text-red-400" : "text-emerald-400"}`}>
                                  {b.stock_units || 0}
                                </p>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ══════════ MARKETING & SOCIAL MEDIA SECTION (from xlsx) ══════════ */}
        {marketingData && (
          <>
            {/* Marketing KPI Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 min-w-0">
              {[
                { label: "Total Social Reach", value: fmtNum(marketingData.totals.totalViews), icon: <Eye size={20} />, color: "#3b82f6", suffix: "views" },
                { label: "Total Engagements", value: fmtNum(marketingData.totals.totalEngagements), icon: <Video size={20} />, color: "#E1306C", suffix: "" },
                { label: "WhatsApp Leads", value: marketingData.totals.totalWaChats.toLocaleString(), icon: <MessageCircle size={20} />, color: "#25d366", suffix: `chats · ${marketingData.totals.totalWaWalkins} walk-ins` },
                { label: "Google Reviews", value: marketingData.totals.totalGoogleReviews.toLocaleString(), icon: <Star size={20} />, color: "#f59e0b", suffix: `across ${marketingData.stores.length} stores` },
              ].map((k, i) => (
                <div key={i} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 relative overflow-hidden">
                  <div className="absolute top-0 left-0 right-0 h-0.5" style={{ background: k.color }} />
                  <div className="flex items-center gap-2 mb-2">
                    <div className="p-2 rounded-lg" style={{ background: `${k.color}20` }}>
                      <div style={{ color: k.color }}>{k.icon}</div>
                    </div>
                    <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">{k.label}</p>
                  </div>
                  <p className="text-xl font-extrabold text-white">{k.value}</p>
                  <p className="text-[11px] text-[var(--text-muted)] mt-0.5">{k.suffix}</p>
                </div>
              ))}
            </div>

            {/* Social Media Performance Chart */}
            <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 min-w-0">
              <h3 className="text-base font-bold text-white tracking-tight mb-1">Social Media Performance by Platform</h3>
              <p className="text-xs text-[var(--text-muted)] mb-4">Views vs Engagements across Instagram, YouTube, TikTok, Snapchat</p>
              <div className="h-64 w-full min-w-0">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={marketingData.socialByPlatform}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                    <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#a1a1aa" }} />
                    <YAxis tick={{ fontSize: 10, fill: "#a1a1aa" }} />
                    <Tooltip contentStyle={{ backgroundColor: "var(--bg-card)", borderColor: "var(--border-subtle)", borderRadius: "12px", fontSize: "12px" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} />
                    <Legend wrapperStyle={{ fontSize: 11, color: "#a1a1aa" }} />
                    <Bar dataKey="views" fill="#3b82f6" name="Views" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="engagements" fill="#a855f7" name="Engagements" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Store Marketing Table */}
            <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 min-w-0">
              <div className="flex items-center gap-2 mb-4">
                <Globe className="text-[#E1306C]" size={20} />
                <div>
                  <h3 className="text-base font-bold text-white tracking-tight">Store Marketing Summary</h3>
                  <p className="text-xs text-[var(--text-muted)]">Social media + WhatsApp + Google Reviews by store</p>
                </div>
              </div>
              <div className="overflow-x-auto w-full">
                <table className="w-full text-sm text-left border-collapse min-w-[900px]">
                  <thead>
                    <tr className="text-[var(--text-muted)] text-xs uppercase tracking-wider border-b border-[var(--border-subtle)]">
                      <th className="py-3 px-3 font-semibold">Store</th>
                      <th className="py-3 px-3 font-semibold text-right">IG Views</th>
                      <th className="py-3 px-3 font-semibold text-right">IG Followers</th>
                      <th className="py-3 px-3 font-semibold text-right">IG Engagements</th>
                      <th className="py-3 px-3 font-semibold text-right">YT Views</th>
                      <th className="py-3 px-3 font-semibold text-right">TT Views</th>
                      <th className="py-3 px-3 font-semibold text-right">WA Chats</th>
                      <th className="py-3 px-3 font-semibold text-right">Google Reviews</th>
                      <th className="py-3 px-3 font-semibold text-right">MTD Revenue</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border-subtle)]">
                    {marketingData.stores.sort((a: any, b: any) => b.mtdRevenue - a.mtdRevenue).map((s: any, i: number) => (
                      <tr key={i} className="hover:bg-[var(--bg-card-hover)] transition-colors">
                        <td className="py-3 px-3 font-medium text-white text-xs">{shortStore(s.store)}</td>
                        <td className="py-3 px-3 text-right text-xs">{(s.igViewsAchieved || 0).toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-xs">{(s.igFollowers || 0).toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-xs">{(s.igLikes + s.igComments + s.igSaves + s.igShares).toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-xs">{(s.ytViews || 0).toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-xs">{(s.ttViews || 0).toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-xs">{(s.waChats || 0).toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-xs">{(s.googleReviews || 0).toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-xs font-semibold text-white">{"\u20b9"}{(s.mtdRevenue || 0).toLocaleString("en-IN")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}

        {/* Loading indicator for sheets */}
        {sheetsLoading && (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-8 text-center">
            <div className="text-sm text-[var(--text-muted)]">Loading dashboard data...</div>
          </div>
        )}

        {/* Breakdown Charts Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 min-w-0">
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 min-w-0">
            <h3 className="text-base font-bold text-white tracking-tight mb-1">Revenue Breakdown</h3>
            <p className="text-xs text-[var(--text-muted)] mb-4">Distribution by team leader</p>
            {mcpReportLoading ? (
              <div className="h-64 animate-pulse bg-[var(--border-subtle)]/30 rounded-xl" />
            ) : !hasRevenueBreakdown ? (
              <div className="h-64 flex flex-col items-center justify-center text-center p-4">
                <PieIcon size={32} className="text-[var(--text-muted)] mb-2 opacity-40" />
                <p className="text-xs font-semibold text-[var(--text-secondary)]">No revenue logged yet</p>
                <p className="text-[11px] text-[var(--text-muted)] mt-0.5">Live sales revenue by team leader will appear here</p>
              </div>
            ) : (
              <div className="h-64 w-full min-w-0">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={revenueBreakdown} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={85} innerRadius={50} paddingAngle={4}>
                      {revenueBreakdown.map((_: any, i: number) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} stroke="rgba(0,0,0,0.4)" strokeWidth={2} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{ backgroundColor: "var(--bg-card)", borderColor: "var(--border-subtle)", borderRadius: "12px", fontSize: "12px" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 min-w-0">
            <h3 className="text-base font-bold text-white tracking-tight mb-1">Lead Status Distribution</h3>
            <p className="text-xs text-[var(--text-muted)] mb-4">Current lead qualification funnel</p>
            {sheetsLoading ? (
              <div className="h-64 animate-pulse bg-[var(--border-subtle)]/30 rounded-xl" />
            ) : !hasLeadDistribution ? (
              <div className="h-64 flex flex-col items-center justify-center text-center p-4">
                <PieIcon size={32} className="text-[var(--text-muted)] mb-2 opacity-40" />
                <p className="text-xs font-semibold text-[var(--text-secondary)]">No leads registered yet</p>
                <p className="text-[11px] text-[var(--text-muted)] mt-0.5">Add leads in the Leads module to see status distribution</p>
              </div>
            ) : (
              <div className="h-64 w-full min-w-0">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={leadDistribution} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={85} innerRadius={50} paddingAngle={4}>
                      {leadDistribution.map((_: any, i: number) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} stroke="rgba(0,0,0,0.4)" strokeWidth={2} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{ backgroundColor: "var(--bg-card)", borderColor: "var(--border-subtle)", borderRadius: "12px", fontSize: "12px" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>

        {/* Top Team Leaders Table Card */}
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 min-w-0">
          <div className="flex items-center gap-2 mb-4">
            <Award className="text-[var(--accent-blue)]" size={20} />
            <div>
              <h3 className="text-base font-bold text-white tracking-tight">Top Performing Team Leaders</h3>
              <p className="text-xs text-[var(--text-muted)]">Leading teams by revenue achievement</p>
            </div>
          </div>
          <div className="overflow-x-auto w-full">
            <table className="w-full text-sm text-left border-collapse min-w-[600px]">
              <thead>
                <tr className="text-[var(--text-muted)] text-xs uppercase tracking-wider border-b border-[var(--border-subtle)]">
                  <th className="py-3 px-4 font-semibold">Team Leader</th>
                  <th className="py-3 px-4 font-semibold text-right">Revenue</th>
                  <th className="py-3 px-4 font-semibold text-right">Target</th>
                  <th className="py-3 px-4 font-semibold text-right">Achievement</th>
                  <th className="py-3 px-4 font-semibold text-right">Active Leads</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-subtle)]">
                {topTeamLeaders.map((tl: any, i: number) => (
                  <tr key={i} className="hover:bg-[var(--bg-card-hover)] transition-colors">
                    <td className="py-3.5 px-4 font-medium text-white flex items-center gap-3">
                      <div className="h-8 w-8 rounded-full bg-[var(--accent-blue)]/15 border border-[var(--accent-blue)]/30 flex items-center justify-center text-[var(--accent-blue)] font-bold text-xs shrink-0">
                        {tl.name ? tl.name.charAt(0) : "T"}
                      </div>
                      <span>{tl.name}</span>
                    </td>
                    <td className="py-3.5 px-4 text-right font-semibold text-white">{"\u20b9"}{(tl.revenue || 0).toLocaleString("en-IN")}</td>
                    <td className="py-3.5 px-4 text-right text-[var(--text-secondary)]">{"\u20b9"}{(tl.target || 0).toLocaleString("en-IN")}</td>
                    <td className="py-3.5 px-4 text-right">
                      <div className="flex items-center justify-end gap-2.5">
                        <div className="w-24 h-2 bg-[var(--border-subtle)] rounded-full overflow-hidden shrink-0">
                          <div className="h-full rounded-full bg-gradient-to-r from-blue-500 to-emerald-400" style={{ width: `${Math.min(tl.achievement || 0, 100)}%` }} />
                        </div>
                        <span className="text-xs font-semibold text-[var(--text-primary)] min-w-[42px] text-right">{(tl.achievement || 0).toFixed(1)}%</span>
                      </div>
                    </td>
                    <td className="py-3.5 px-4 text-right font-medium text-[var(--text-primary)]">{tl.active_leads || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Bottom Summary Strip */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 min-w-0">
          {[
            { label: "Total Stores", value: ops?.storeAchievements.length || 0 },
            { label: "Green Stores (65%+)", value: ops?.rag.green || 0 },
            { label: "Red Stores (<35%)", value: ops?.rag.red || 0 },
          ].map((item, i) => (
            <div key={i} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 text-center hover:border-white/10 transition-colors">
              <p className="text-xs font-medium uppercase tracking-wider text-[var(--text-muted)] mb-1">{item.label}</p>
              <p className="text-2xl font-bold text-white">{item.value}</p>
            </div>
          ))}
        </div>
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
}
