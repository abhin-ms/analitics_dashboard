import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Brain, Settings, RefreshCw, AlertTriangle, CheckCircle, XCircle,
  TrendingUp, ArrowUpRight, Save, FileText, Sparkles, Target, Users, MessageCircle,
} from "lucide-react";
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine,
  RadarChart, PolarGrid, PolarAngleAxis, Radar, ComposedChart,
} from "recharts";
import { api } from "@/lib/apiClient";
import { useAuthStore } from "@/lib/authStore";
import { getSocket } from "@/lib/socket";
import { DashboardChatBubble } from "./DashboardChatBubble";
import { formatMoney, formatNumber, formatPct } from "@/lib/formatMoney";
import { curateKpis, buildSectionCharts, type KpiCard, type ChartDef } from "./sectionVisuals";
import {
  CardFilterPopover,
  CardFilterState,
  DEFAULT_CARD_FILTER,
  applyCardFilter,
} from "@/components/shared/CardFilterPopover";

interface SummaryData {
  summary?: string;
  highlights?: string[];
  concerns?: string[];
  recommendations?: { priority: string; title: string; detail: string; owner?: string }[];
  anomalies?: { severity: string; store: string; metric: string; observation: string; suggested_action?: string }[];
  context?: any;
  _meta?: {
    generated_at?: string;
    provider?: string;
    model?: string;
    input_tokens?: number;
    output_tokens?: number;
    cost?: number;
    cached?: boolean;
    used_fallback?: boolean;
    ai_status?: "ok" | "error" | "fallback";
    error?: string;
    no_summary?: boolean;
    stale?: boolean;
  };
}

interface AIConfig {
  id: number;
  system_prompt: string;
  provider: string;
  model_name: string;
  updated_at?: string;
}

const MODELS: Record<string, string[]> = {
  claude: ["claude-sonnet-4-6", "claude-sonnet-4-5", "claude-haiku-4-5-20251001"],
  openai: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
};

const SEV_COLORS: Record<string, string> = {
  critical: "#ef4444",
  warning: "#f59e0b",
  info: "#3b82f6",
};

const PRIO_COLORS: Record<string, string> = {
  critical: "#ef4444",
  high: "#f59e0b",
  strategic: "#a855f7",
};

function fmtMoney(n: number) {
  return formatMoney(n ?? 0);
}

function LoadingCard() {
  return <div className="h-72 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] animate-pulse" />;
}

const CHART_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#a855f7", "#ef4444", "#06b6d4", "#ec4899", "#84cc16"];

function chartFormatter(unit?: ChartDef["unit"]) {
  return (v: any) => {
    const x = Number(v);
    if (isNaN(x)) return String(v);
    if (unit === "%") return `${x.toFixed(0)}%`;
    if (unit === "₹") return formatMoney(x);
    return formatNumber(x);
  };
}

function SectionChartCard({ def }: { def: ChartDef }) {
  const [filter, setFilter] = useState<CardFilterState>(DEFAULT_CARD_FILTER);
  const fmt = chartFormatter(def.unit);
  const tickFill = { fontSize: 10, fill: "#a1a1aa" };
  const tooltipStyle = { backgroundColor: "var(--bg-card)", borderColor: "var(--border-subtle)", borderRadius: "12px", fontSize: "12px" };
  const tooltipLabelStyle = { color: "var(--text-primary)" };
  const tooltipItemStyle = { color: "var(--text-primary)" };
  const hasPctAxis = def.series.some((s) => s.yAxisId === "pct");

  // Extract entity options (e.g. stores, names, or categories)
  const entityOptions = useMemo(() => {
    if (!def.data || !Array.isArray(def.data)) return [];
    const set = new Set<string>();
    def.data.forEach((row) => {
      if (row.name) set.add(String(row.name));
      if (row.store) set.add(String(row.store));
      if (row.tl) set.add(String(row.tl));
    });
    return Array.from(set).slice(0, 30);
  }, [def.data]);

  // Apply card-level filters
  const filteredData = useMemo(() => {
    return applyCardFilter(def.data, filter);
  }, [def.data, filter]);

  const isFiltered =
    filter.dateMode !== "all" || (filter.selectedEntity && filter.selectedEntity !== "all");

  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 min-w-0 h-full flex flex-col justify-between">
      <div>
        <div className="flex items-start justify-between gap-2 mb-2">
          <div>
            <h3 className="text-sm font-bold text-white tracking-tight flex items-center gap-2">
              {def.title}
              {isFiltered && (
                <span className="text-[10px] bg-blue-500/20 text-blue-300 border border-blue-500/30 px-2 py-0.5 rounded-full font-medium">
                  {filter.dateMode === "3day"
                    ? "Last 3 Days"
                    : filter.dateMode === "7day"
                    ? "Last 7 Days"
                    : filter.dateMode === "30day"
                    ? "Last 30 Days"
                    : filter.selectedEntity && filter.selectedEntity !== "all"
                    ? filter.selectedEntity
                    : "Filtered"}
                </span>
              )}
            </h3>
            {def.subtitle && <p className="text-xs text-[var(--text-muted)] mt-0.5">{def.subtitle}</p>}
          </div>

          {/* 3-Dot Filter Popover Menu */}
          <CardFilterPopover
            filter={filter}
            onFilterChange={setFilter}
            entityLabel="Entity"
            entityOptions={entityOptions}
          />
        </div>
      </div>

      <div className="h-64 w-full min-w-0 mt-2">
        {def.type === "line" && (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={filteredData} margin={{ top: 10, right: 15, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey={def.xKey} tick={tickFill} />
              <YAxis tick={tickFill} tickFormatter={fmt} width={70} />
              <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} itemStyle={tooltipItemStyle} formatter={(v: any) => fmt(v)} />
              <Legend wrapperStyle={{ fontSize: 11, color: "#a1a1aa" }} />
              {def.series.map((s) => (
                <Line key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={s.color} strokeWidth={2.5} dot={{ r: 2.5, fill: s.color }} activeDot={{ r: 5 }} />
              ))}
              {def.reference && (
                <ReferenceLine y={def.reference.y} stroke="#a855f7" strokeDasharray="6 4" label={{ value: def.reference.label, fill: "#a855f7", fontSize: 11, position: "insideTopRight" }} />
              )}
            </LineChart>
          </ResponsiveContainer>
        )}
        {def.type === "bar" && (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={filteredData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey={def.xKey} tick={tickFill} />
              <YAxis tick={tickFill} tickFormatter={fmt} width={70} />
              <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} itemStyle={tooltipItemStyle} formatter={(v: any) => fmt(v)} />
              <Legend wrapperStyle={{ fontSize: 11, color: "#a1a1aa" }} />
              {def.series.map((s) => (
                <Bar key={s.key} dataKey={s.key} name={s.name} fill={s.color} radius={[4, 4, 0, 0]} stackId={def.stacked ? "a" : undefined} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}
        {def.type === "hbar" && (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={filteredData} layout="vertical" margin={{ top: 5, right: 20, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis type="number" tick={tickFill} tickFormatter={fmt} />
              <YAxis type="category" dataKey={def.xKey} tick={tickFill} width={130} />
              <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} itemStyle={tooltipItemStyle} formatter={(v: any) => fmt(v)} />
              {def.series.map((s) => (
                <Bar key={s.key} dataKey={s.key} name={s.name} fill={s.color} radius={[0, 4, 4, 0]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}
        {def.type === "donut" && (() => {
          const RAG_COLOR_MAP: Record<string, string> = {
            "Green ≥65%": "#10b981",
            "Amber 35–64%": "#f59e0b",
            "Red <35%": "#ef4444",
          };
          const isRagChart = def.id === "rag";
          return (
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={filteredData} cx="50%" cy="50%" innerRadius={50} outerRadius={85} dataKey="value" nameKey="name" stroke="#11131e" strokeWidth={2}>
                  {filteredData.map((entry: any, i: number) => {
                    const color = isRagChart
                      ? (RAG_COLOR_MAP[entry.name] || CHART_COLORS[i % CHART_COLORS.length])
                      : ((def.colors && def.colors[i]) || CHART_COLORS[i % CHART_COLORS.length]);
                    return <Cell key={i} fill={color} />;
                  })}
                </Pie>
                <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} itemStyle={tooltipItemStyle} />
                <Legend wrapperStyle={{ fontSize: 11, color: "#a1a1aa" }} />
              </PieChart>
            </ResponsiveContainer>
          );
        })()}
        {def.type === "radar" && (
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart data={filteredData} outerRadius="75%">
              <PolarGrid stroke="rgba(255,255,255,0.1)" />
              <PolarAngleAxis dataKey={def.xKey} tick={{ fontSize: 10, fill: "#a1a1aa" }} />
              {def.series.map((s) => (
                <Radar key={s.key} dataKey={s.key} name={s.name} stroke={s.color} fill={s.color} fillOpacity={0.35} />
              ))}
              <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} itemStyle={tooltipItemStyle} formatter={(v: any) => fmt(v)} />
            </RadarChart>
          </ResponsiveContainer>
        )}
        {def.type === "composed" && (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={filteredData} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey={def.xKey} tick={tickFill} />
              <YAxis yAxisId="main" tick={tickFill} tickFormatter={fmt} width={70} />
              {hasPctAxis && <YAxis yAxisId="pct" orientation="right" tick={tickFill} tickFormatter={(v: any) => `${v}%`} width={40} />}
              <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} itemStyle={tooltipItemStyle} />
              <Legend wrapperStyle={{ fontSize: 11, color: "#a1a1aa" }} />
              {def.series.map((s) =>
                s.kind === "line" ? (
                  <Line key={s.key} yAxisId={s.yAxisId} type="monotone" dataKey={s.key} name={s.name} stroke={s.color} strokeWidth={2.5} dot={{ r: 2.5 }} />
                ) : (
                  <Bar key={s.key} yAxisId={s.yAxisId} dataKey={s.key} name={s.name} fill={s.color} radius={[4, 4, 0, 0]} />
                )
              )}
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

export function AISummary({ section = "overview", title = "AI Executive Summary" }: { section?: string; title?: string } = {}) {
  const canManage = useAuthStore((s) =>
    s.hasPermission("ai_analytics", "manage") || ["SuperAdmin", "Admin", "CEO"].includes(s.user?.role_name || "")
  );
  const isAuthenticated = useAuthStore((s) => !!s.token);

  const [data, setData] = useState<SummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // company-wide summaries are admin-only; other roles just don't get the card
  const [forbidden, setForbidden] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const [showSettings, setShowSettings] = useState(false);
  const [config, setConfig] = useState<AIConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  const [regenMsg, setRegenMsg] = useState<{ kind: "ok" | "err" | "warn"; text: string } | null>(null);

  // showSkeleton is only true for the very first load. A background sync
  // event (Sheets/MCP/etc. sync every 1-15 min, broadcast to every open
  // browser) used to call this with the skeleton on every time, blanking
  // out an already-displayed summary and redrawing it a moment later —
  // that's the "blinking" this page showed roughly every 1-3 minutes. The
  // AI summary is cached and only actually changes when someone clicks
  // Regenerate, so a background refresh only needs to silently swap in
  // any updated data, never force a visible reload of content already
  // on screen.
  const fetchSummary = useCallback(async (showSkeleton: boolean) => {
    if (showSkeleton) setLoading(true);
    setError(null);
    try {
      const res = await api.fetchRaw(`/ai-analytics/summary?section=${section}`);
      if (res.status === 403) {
        setForbidden(true);
        return;
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const d = await res.json();
      setData(d);
    } catch (e: any) {
      if (showSkeleton) setError(e.message);
    } finally {
      if (showSkeleton) setLoading(false);
    }
  }, [section]);

  useEffect(() => {
    fetchSummary(true);
  }, [fetchSummary]);

  useEffect(() => {
    if (!isAuthenticated) return;
    const socket = getSocket();
    if (!socket) return;
    const handleRefresh = () => {
      fetchSummary(false);
    };
    socket.on("data:refresh", handleRefresh);
    return () => {
      socket.off("data:refresh", handleRefresh);
    };
  }, [isAuthenticated, fetchSummary]);

  const openSettings = useCallback(async () => {
    setConfigError(null);
    setSavedMsg(null);
    try {
      const cfg = await api.get<AIConfig>(`/ai-analytics/config?section=${section}`);
      setConfig(cfg);
      setShowSettings(true);
    } catch (e: any) {
      setConfigError(e.message);
      setShowSettings(true);
    }
  }, [section]);

  const saveConfig = useCallback(async () => {
    if (!config) return;
    setSaving(true);
    setConfigError(null);
    setSavedMsg(null);
    try {
      const updated = await api.put<AIConfig>(`/ai-analytics/config?section=${section}`, {
        system_prompt: config.system_prompt,
        provider: config.provider,
        model_name: config.model_name,
      });
      setConfig(updated);
      setSavedMsg("Prompt saved. Regenerate to apply.");
    } catch (e: any) {
      setConfigError(e.message);
    } finally {
      setSaving(false);
    }
  }, [config, section]);

  const regenerate = useCallback(async () => {
    setRegenerating(true);
    setConfigError(null);
    setSavedMsg(null);
    setRegenMsg(null);
    try {
      const d = await api.post<SummaryData>(`/ai-analytics/summary/regenerate?section=${section}`);
      setData(d);
      const st = d?._meta?.ai_status;
      if (st === "ok") {
        setRegenMsg({
          kind: "ok",
          text: `AI summary regenerated successfully (${d._meta?.provider || "claude"} / ${d._meta?.model || ""}).`,
        });
      } else if (st === "error") {
        setRegenMsg({
          kind: "err",
          text: `AI generation failed — showing template summary${d?._meta?.error ? `: ${d._meta.error}` : ""}.`,
        });
      } else {
        setRegenMsg({ kind: "warn", text: "Summary regenerated with the template (no AI key configured)." });
      }
    } catch (e: any) {
      setConfigError(e.message);
    } finally {
      setRegenerating(false);
    }
  }, [section]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    await fetchSummary(false);
    setRefreshing(false);
  }, [fetchSummary]);

  const charts = useMemo<ChartDef[]>(() => buildSectionCharts(section, data?.context), [data, section]);

  const kpis = useMemo<KpiCard[]>(() => curateKpis(section, data?.context), [data, section]);

  if (forbidden) return null;

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="h-5 w-56 rounded bg-white/5 animate-pulse" />
            <div className="h-3 w-72 rounded bg-white/5 animate-pulse mt-2" />
          </div>
        </div>
        <LoadingCard />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <LoadingCard />
          <LoadingCard />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-10 text-center flex flex-col items-center">
        <AlertTriangle size={36} className="text-rose-400 mb-3" />
        <h3 className="text-base font-semibold text-white mb-1">Failed to load AI summary</h3>
        <p className="text-xs text-[var(--text-muted)] mb-4">{error}</p>
        <button
          onClick={refresh}
          className="px-4 py-2 rounded-lg bg-[var(--accent-blue)] text-white text-sm font-semibold hover:opacity-90"
        >
          Retry
        </button>
      </div>
    );
  }

  const meta = data?._meta;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="rounded-2xl border border-[var(--border-subtle)] bg-gradient-to-r from-[#11131e] via-[#151a2e] to-[#1a1430] p-5 sm:p-6 relative overflow-hidden">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-xl bg-purple-500/20 border border-purple-500/30 flex items-center justify-center">
              <Brain className="text-purple-400" size={22} />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white tracking-tight flex items-center gap-2">
                {title}
                <Sparkles className="text-amber-400" size={16} />
              </h2>
              <p className="text-xs text-[var(--text-muted)] mt-0.5">
                {meta?.generated_at
                  ? `Generated ${new Date(meta.generated_at).toLocaleString()}`
                  : meta?.no_summary
                    ? "No AI summary generated yet"
                    : "Not generated"}
                {meta?.stale && (
                  <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-blue-500/15 border border-blue-500/30 text-blue-300 text-[10px] font-medium">
                    data updated — click Regenerate for fresh analysis
                  </span>
                )}
                {meta?.used_fallback && (
                  <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-500/15 border border-amber-500/30 text-amber-300 text-[10px] font-medium">
                    <AlertTriangle size={10} /> Template fallback
                  </span>
                )}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {meta && (
              <span className="hidden sm:inline-flex items-center gap-1.5 text-[10px] text-[var(--text-muted)] px-2 py-1 rounded-lg bg-white/5 border border-[var(--border-subtle)]">
                <span
                  className={`inline-block w-1.5 h-1.5 rounded-full ${
                    meta.ai_status === "ok"
                      ? "bg-emerald-400"
                      : meta.ai_status === "error"
                        ? "bg-rose-400"
                        : "bg-amber-400"
                  }`}
                  title={meta.error || meta.ai_status}
                />
                {meta.ai_status === "ok"
                  ? "AI"
                  : meta.ai_status === "error"
                    ? "Failed"
                    : "Template"}
                {meta.provider ? ` · ${meta.provider}` : ""}
                {meta.model ? ` · ${meta.model}` : ""}
                {(meta.input_tokens || 0) > 0 && ` · ${(meta.input_tokens || 0).toLocaleString()} in / ${(meta.output_tokens || 0).toLocaleString()} out`}
                {(meta.cost || 0) > 0 && ` · ${fmtMoney(meta.cost || 0)}`}
                {meta.cached && " · cached"}
                {meta.ai_status === "error" && meta.error && (
                  <span className="max-w-[220px] truncate text-rose-300"> · {meta.error}</span>
                )}
              </span>
            )}
            <button
              onClick={refresh}
              disabled={refreshing}
              className="p-2 rounded-lg bg-white/5 border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-white hover:border-white/20 disabled:opacity-50"
              title="Refresh"
            >
              <RefreshCw size={16} className={refreshing ? "animate-spin" : ""} />
            </button>
            {canManage && (
              <button
                onClick={openSettings}
                className="px-3 py-2 rounded-lg bg-blue-500/15 border border-blue-500/30 text-blue-300 hover:bg-blue-500/25 text-sm font-semibold flex items-center gap-1.5"
              >
                <Settings size={15} /> Prompt Settings
              </button>
            )}
          </div>
        </div>
      </div>

      {/* No summary yet */}
      {meta?.no_summary && (
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-10 text-center flex flex-col items-center">
          <Sparkles size={36} className="text-purple-400 mb-3" />
          <h3 className="text-base font-semibold text-white mb-1">No AI summary generated yet</h3>
          <p className="text-xs text-[var(--text-muted)] mb-4 max-w-md">
            Click Generate Now to create an AI analysis of the current month's data for this tab. This calls Claude once; the result is saved and reused until you regenerate.
          </p>
          <button
            onClick={regenerate}
            disabled={regenerating}
            className="px-5 py-2.5 rounded-lg bg-[var(--accent-blue)] text-white text-sm font-semibold hover:opacity-90 flex items-center gap-2 disabled:opacity-50"
          >
            <Sparkles size={15} />
            {regenerating ? "Generating…" : "Generate Now"}
          </button>
        </div>
      )}

      {/* Narrative */}
      {data?.summary && (
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6">
          <div className="flex items-center gap-2 mb-3">
            <FileText className="text-[var(--accent-blue)]" size={18} />
            <h3 className="text-sm font-bold text-white tracking-tight">Executive Brief</h3>
          </div>
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed whitespace-pre-wrap">{data.summary}</p>

          {(data.highlights?.length || data.concerns?.length) && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
              <div>
                <div className="flex items-center gap-1.5 mb-2">
                  <CheckCircle size={14} className="text-emerald-400" />
                  <span className="text-xs font-semibold text-emerald-300 uppercase tracking-wider">Highlights</span>
                </div>
                <ul className="space-y-1.5">
                  {data.highlights?.map((h, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-[var(--text-secondary)]">
                      <ArrowUpRight size={13} className="text-emerald-400 mt-0.5 shrink-0" />
                      <span>{h}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <div className="flex items-center gap-1.5 mb-2">
                  <XCircle size={14} className="text-rose-400" />
                  <span className="text-xs font-semibold text-rose-300 uppercase tracking-wider">Concerns</span>
                </div>
                <ul className="space-y-1.5">
                  {data.concerns?.map((c, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-[var(--text-secondary)]">
                      <AlertTriangle size={13} className="text-rose-400 mt-0.5 shrink-0" />
                      <span>{c}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      )}

      {/* KPI Cards */}
      {kpis.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
          {kpis.map((k, i) => (
            <div key={i} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 relative overflow-hidden">
              <div className="absolute top-0 left-0 right-0 h-0.5" style={{ background: k.color }} />
              <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] mb-1">{k.label}</p>
              <p className="text-xl font-extrabold text-white">{k.value}</p>
              {k.sub ? <p className="text-[11px] text-[var(--text-muted)] mt-0.5">{k.sub}</p> : null}
              {k.delta ? (
                <p className={`text-[11px] font-semibold mt-1 inline-flex items-center gap-1 ${k.delta.dir === "up" ? "text-emerald-400" : "text-rose-400"}`}>
                  {k.delta.dir === "up" ? "▲" : "▼"} {k.delta.text}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      )}

      {/* Charts */}
      {charts.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {charts.map((def) => (
            <div key={def.id} className={def.span === 2 ? "lg:col-span-2" : ""}>
              <SectionChartCard def={def} />
            </div>
          ))}
        </div>
      )}

      {/* Anomalies */}
      {data?.anomalies?.length ? (
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5">
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle className="text-rose-400" size={18} />
            <h3 className="text-sm font-bold text-white tracking-tight">Anomalies & Alerts</h3>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {data.anomalies.map((a, i) => {
              const color = SEV_COLORS[a.severity] || "#3b82f6";
              return (
                <div key={i} className="rounded-xl border p-4" style={{ borderColor: `${color}40`, background: `${color}0d` }}>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-bold text-white">{a.store}</span>
                    <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full font-semibold" style={{ color, background: `${color}20`, border: `1px solid ${color}40` }}>
                      {a.severity}
                    </span>
                  </div>
                  <p className="text-[11px] text-[var(--text-muted)] uppercase tracking-wider mb-1">{a.metric}</p>
                  <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{a.observation}</p>
                  {a.suggested_action && (
                    <p className="text-[11px] text-[var(--text-secondary)] mt-2 flex items-start gap-1.5">
                      <Target size={12} className="mt-0.5 shrink-0" style={{ color }} />
                      <span><strong style={{ color }}>Action:</strong> {a.suggested_action}</span>
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {/* Recommendations */}
      {data?.recommendations?.length ? (
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5">
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp className="text-emerald-400" size={18} />
            <h3 className="text-sm font-bold text-white tracking-tight">Recommendations to Improve</h3>
          </div>
          <div className="space-y-3">
            {data.recommendations.map((r, i) => {
              const color = PRIO_COLORS[r.priority] || "#a855f7";
              return (
                <div key={i} className="flex gap-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-card-hover)] p-4">
                  <div className="w-7 h-7 rounded-lg flex items-center justify-center text-sm font-extrabold shrink-0" style={{ color, background: `${color}18`, border: `1px solid ${color}35` }}>
                    {i + 1}
                  </div>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2 mb-1">
                      <span className="text-sm font-bold text-white">{r.title}</span>
                      <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full font-semibold" style={{ color, background: `${color}20`, border: `1px solid ${color}40` }}>
                        {r.priority}
                      </span>
                    </div>
                    <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{r.detail}</p>
                    {r.owner && (
                      <p className="text-[11px] text-[var(--text-muted)] mt-1.5 flex items-center gap-1.5">
                        <Users size={12} /> Owner: {r.owner}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {/* Settings Modal */}
      {showSettings && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={() => setShowSettings(false)}>
          <div className="w-full max-w-2xl rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-6 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Brain className="text-purple-400" size={18} />
                <h3 className="text-base font-bold text-white tracking-tight">AI Prompt Settings — {title}</h3>
              </div>
              <button onClick={() => setShowSettings(false)} className="p-1.5 rounded-lg bg-white/5 text-[var(--text-muted)] hover:text-white">✕</button>
            </div>

            <p className="text-xs text-[var(--text-muted)] mb-4">
              Configure how Claude analyzes the dashboard data for the <span className="text-white">{title}</span> tab. Only Super Admin, Admin and CEO can edit this.
            </p>

            {configError && (
              <div className="mb-4 p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">{configError}</div>
            )}
            {savedMsg && (
              <div className="mb-4 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-xs">{savedMsg}</div>
            )}
            {regenMsg && (
              <div className={`mb-4 p-3 rounded-lg border text-xs ${
                regenMsg.kind === "ok"
                  ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                  : regenMsg.kind === "err"
                    ? "bg-rose-500/10 border-rose-500/30 text-rose-300"
                    : "bg-amber-500/10 border-amber-500/30 text-amber-300"
              }`}>
                {regenMsg.text}
              </div>
            )}

            {!config ? (
              <div className="h-48 rounded-xl bg-white/5 animate-pulse" />
            ) : (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
                  <div>
                    <label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">Provider</label>
                    <select
                      value={config.provider}
                      onChange={(e) => setConfig({ ...config, provider: e.target.value })}
                      className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white"
                    >
                      <option value="claude">Claude (Anthropic)</option>
                      <option value="openai">ChatGPT (OpenAI)</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">Model</label>
                    <select
                      value={config.model_name}
                      onChange={(e) => setConfig({ ...config, model_name: e.target.value })}
                      className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white"
                    >
                      {(MODELS[config.provider] || MODELS.claude).map((m) => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="mb-4">
                  <label className="text-xs font-semibold text-[var(--text-muted)] mb-1 block">Analysis Instruction Prompt</label>
                  <textarea
                    value={config.system_prompt}
                    onChange={(e) => setConfig({ ...config, system_prompt: e.target.value })}
                    rows={10}
                    className="w-full px-3 py-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white font-mono leading-relaxed"
                  />
                  <p className="text-[10px] text-[var(--text-muted)] mt-1">
                    Tip: keep the JSON output schema so the summary section stays structured.
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-2 justify-end">
                  <button
                    onClick={regenerate}
                    disabled={regenerating}
                    className="px-4 py-2 rounded-lg bg-purple-500/15 border border-purple-500/30 text-purple-300 hover:bg-purple-500/25 text-sm font-semibold flex items-center gap-1.5 disabled:opacity-50"
                  >
                    <RefreshCw size={14} className={regenerating ? "animate-spin" : ""} />
                    {regenerating ? "Generating…" : meta?.no_summary ? "Generate Now" : "Regenerate Now"}
                  </button>
                  <button
                    onClick={saveConfig}
                    disabled={saving}
                    className="px-4 py-2 rounded-lg bg-[var(--accent-blue)] text-white text-sm font-semibold flex items-center gap-1.5 hover:opacity-90 disabled:opacity-50"
                  >
                    <Save size={14} />
                    {saving ? "Saving…" : "Save Prompt"}
                  </button>
                  <button
                    onClick={() => setShowSettings(false)}
                    className="px-4 py-2 rounded-lg bg-white/5 text-[var(--text-secondary)] text-sm font-semibold hover:text-white"
                  >
                    Cancel
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
      <DashboardChatBubble />
    </div>
  );
}