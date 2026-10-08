import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Bar, CartesianGrid, ComposedChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import {
  AlertTriangle, ArrowLeft, BarChart3, Bookmark, CalendarDays, CheckCircle2, ChevronLeft, ChevronRight, ClipboardList, Eye,
  Film, Megaphone, MessageSquare, Repeat2, Share2, Star, Target, TrendingUp, UserCheck, Users,
} from "lucide-react";
import { api } from "@/lib/apiClient";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { PLATFORM_LABEL, Platform, STATUS_COLOR, Status } from "@/features/social/socialData";

// ── API shape ──────────────────────────────────────────────────────
type PaceStatus = "achieved" | "ahead" | "on_track" | "behind" | "at_risk" | "no_target" | "no_data";
interface Pace {
  target: number; achieved: number; pct: number | null; remaining: number; expected_to_date: number;
  days_total: number; days_elapsed: number; days_remaining: number;
  required_daily: number | null; current_daily: number; status: PaceStatus;
}
interface PlatformPace extends Pace { has_data: boolean; monthly_target: number }
/** One month of the tracker sheet (its latest month-to-date row). */
type SocialMonth = { month: string; as_of: string; reels: number } & Record<string, number | string | null>;
interface LeadSource {
  key: string; label: string; leads: number; converted: number; rate: number; revenue: number;
  /** WhatsApp / walk-ins: the Daily Tracker's monthly total, until they're CRM leads. */
  tracker: { label: string; value: number } | null;
}
interface Portfolio {
  store: { id: number; name: string; country: string; region: string; address: string; team_leader: string; is_active: boolean; currency: string };
  period: { start: string; end: string; as_of: string; days_total: number; days_remaining: number };
  social: {
    has_data: boolean; as_of: string | null; monthly: SocialMonth[]; last_report: SocialMonth | null; platforms: Record<Platform, PlatformPace>; reels: number; posts: number; likes: number;
    comments: number; shares: number; saves: number; reposts: number; followers: number; new_followers: number;
  };
  leads: {
    targets: { leads_monthly: number; conversion_pct: number };
    total: number; converted: number; conversion_pct: number; conversion_target_pct: number; revenue: number;
    volume: Pace; conversions: Pace;
    sources: LeadSource[];
    status_counts: Record<string, number>;
    visits: { attended: number; scheduled: number; no_show: number; total: number };
    matched_by: Record<string, number>;
    duplicates_merged: number;
    area_label: string;
    area: { label: string; shops: number; total: number; converted: number; status_counts: Record<string, number>; sources: LeadSource[] } | null;
  };
  sales: {
    monthly_target: number; pace: Pace; sales_count: number; units: number; avg_bill: number; sales_needed: number;
    series: { date: string; revenue: number | null; cumulative: number | null; target_pace: number }[];
    last_synced_at: string | null;
  };
  reviews: {
    rating: number | null; rating_as_of: string | null; rating_previous: number | null; new_reviews: number; total_reviews: number | null;
    response: string; positive: number | null; negative: number | null; unanswered: number | null;
    extra_columns: Record<string, number | string>;
  };
  analysis: {
    rows: { area: "social" | "leads" | "sales" | "reviews"; status: PaceStatus; gap: string; action: string; priority: string }[];
    strengths: string[]; concerns: string[]; needs_attention: string[];
  };
  sheet_updated_at: string | null;
}

// ── formatting ─────────────────────────────────────────────────────
const num = (n: number | null | undefined) => (n === null || n === undefined ? "—" : Math.round(n).toLocaleString("en-IN"));
function compact(n: number) {
  if (n >= 1e7) return `${+(n / 1e7).toFixed(2)}Cr`;
  if (n >= 1e5) return `${+(n / 1e5).toFixed(1)}L`;
  if (n >= 1e3) return `${+(n / 1e3).toFixed(1)}K`;
  return String(Math.round(n));
}
function moneyFmt(currency: string) {
  let f: Intl.NumberFormat;
  try {
    f = new Intl.NumberFormat(currency === "INR" ? "en-IN" : "en", { style: "currency", currency, maximumFractionDigits: 0 });
  } catch {
    f = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
  }
  return (n: number | null | undefined) => (n === null || n === undefined ? "—" : f.format(n));
}
const monthLabel = (ym: string) =>
  new Date(`${ym}-01T00:00:00`).toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
const shortDate = (iso: string) => {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
};
const localIso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

const PACE_STATUS: Record<PaceStatus, { label: string; tone: Status }> = {
  achieved: { label: "Target met", tone: "good" },
  ahead: { label: "Ahead of pace", tone: "good" },
  on_track: { label: "On track", tone: "good" },
  behind: { label: "Behind pace", tone: "warn" },
  at_risk: { label: "At risk", tone: "crit" },
  no_target: { label: "No target", tone: "none" },
  no_data: { label: "No data", tone: "none" },
};
const PRIORITY_TONE: Record<string, Status> = {
  High: "crit", Medium: "warn", Low: "good", "On track": "good", Done: "good", "Set target": "none", "No data": "none",
};
const AREA: Record<string, { label: string; icon: typeof Megaphone }> = {
  social: { label: "Social Media", icon: Megaphone },
  leads: { label: "Leads & Conversion", icon: Users },
  sales: { label: "Sales", icon: BarChart3 },
  reviews: { label: "Google Reviews", icon: Star },
};
const CHART_BLUE = "#3b82f6";
const AXIS_TICK = { fontSize: 10, fill: "#a1a1aa" };
const TOOLTIP_STYLE = { backgroundColor: "var(--bg-card)", borderColor: "var(--border-subtle)", borderRadius: 12, fontSize: 12 };

// ── small building blocks ──────────────────────────────────────────
function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] ${className}`}>{children}</div>;
}

function Section({ n, title, icon: Icon, children, right }: {
  n: number; title: string; icon: typeof Megaphone; children: React.ReactNode; right?: React.ReactNode;
}) {
  return (
    <Card className="p-4 sm:p-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2.5 text-base sm:text-lg font-bold text-white tracking-tight">
          <Icon size={20} className="text-[var(--accent-blue)]" />
          {n}. {title}
        </h2>
        {right}
      </div>
      {children}
    </Card>
  );
}

function Stat({ label, value, sub, icon: Icon, subTone }: {
  label: string; value: React.ReactNode; sub?: React.ReactNode; icon: typeof Megaphone; subTone?: Status;
}) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-3 min-w-0">
      <div className="h-9 w-9 shrink-0 rounded-lg bg-blue-500/10 flex items-center justify-center">
        <Icon size={17} className="text-[var(--accent-blue)]" />
      </div>
      <div className="min-w-0">
        <p className="text-[11px] text-[var(--text-muted)] truncate">{label}</p>
        <p className="text-lg font-extrabold text-white leading-tight tabular-nums truncate">{value}</p>
        {sub !== undefined && (
          <p className="text-[11px] text-[var(--text-secondary)] truncate flex items-center gap-1">
            {subTone && <i className="inline-block h-1.5 w-1.5 rounded-full shrink-0" style={{ background: STATUS_COLOR[subTone] }} />}
            {sub}
          </p>
        )}
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: PaceStatus }) {
  const s = PACE_STATUS[status];
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border-subtle)] px-2.5 py-0.5 text-[11px] font-semibold text-[var(--text-primary)]">
      <i className="inline-block h-2 w-2 rounded-full" style={{ background: STATUS_COLOR[s.tone] }} />
      {s.label}
    </span>
  );
}

function Progress({ pct, status }: { pct: number | null; status: PaceStatus }) {
  const w = Math.max(0, Math.min(pct ?? 0, 100));
  return (
    <div className="h-2.5 w-full rounded-full bg-[var(--border-subtle)] overflow-hidden" role="progressbar" aria-valuenow={Math.round(w)} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full" style={{ width: `${w}%`, background: STATUS_COLOR[PACE_STATUS[status].tone] }} />
    </div>
  );
}

/** Target card: % achieved, progress bar, achieved vs remaining, pace needed. */
function TargetCard({ title, pace, fmt, unit }: { title: string; pace: Pace; fmt: (n: number) => string; unit: string }) {
  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-white">{title}</p>
        <StatusPill status={pace.status} />
      </div>
      {pace.status === "no_target" ? (
        <p className="text-sm text-[var(--text-muted)]">No target set for this store.</p>
      ) : (
        <>
          <p className="text-3xl font-extrabold text-white tabular-nums">{pace.pct ?? 0}%</p>
          <Progress pct={pace.pct} status={pace.status} />
          <div className="flex justify-between text-xs">
            <div><p className="font-bold text-white tabular-nums">{fmt(pace.achieved)}</p><p className="text-[var(--text-muted)]">achieved</p></div>
            <div className="text-right"><p className="font-bold text-white tabular-nums">{fmt(pace.remaining)}</p><p className="text-[var(--text-muted)]">remaining of {fmt(pace.target)}</p></div>
          </div>
          <div className="rounded-lg bg-blue-500/10 px-3 py-2 text-center text-xs">
            {pace.remaining <= 0 ? (
              <p className="font-semibold text-white">Target reached</p>
            ) : pace.required_daily === null ? (
              <p className="font-semibold text-white">Period ended {fmt(pace.remaining)} short</p>
            ) : (
              <>
                <p className="font-semibold text-white">{fmt(pace.required_daily)} {unit}/day needed · {pace.days_remaining} days left</p>
                <p className="text-[var(--text-muted)]">Current average: {fmt(pace.current_daily)}/day</p>
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function shiftMonth(ym: string, by: number) {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m - 1 + by, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
/** Open the browser's calendar on click, not only on the small icon. */
function openPicker(input: HTMLInputElement) {
  try {
    input.showPicker?.();
  } catch {
    /* older browsers: the native control still works */
  }
}

// ── date range ─────────────────────────────────────────────────────
type Preset = "today" | "7day" | "month" | "custom";
function rangeFor(preset: Preset, custom: { from: string; to: string } | null) {
  const now = new Date();
  const today = localIso(now);
  if (preset === "custom" && custom) return custom;
  if (preset === "today") return { from: today, to: today };
  if (preset === "7day") {
    const f = new Date(now);
    f.setDate(f.getDate() - 6);
    return { from: localIso(f), to: today };
  }
  // Whole calendar month, measured as of today, so pace and days left show.
  return {
    from: localIso(new Date(now.getFullYear(), now.getMonth(), 1)),
    to: localIso(new Date(now.getFullYear(), now.getMonth() + 1, 0)),
  };
}

// ── page ───────────────────────────────────────────────────────────
export default function StorePortfolio() {
  const { storeId } = useParams<{ storeId: string }>();
  const navigate = useNavigate();
  const [preset, setPreset] = useState<Preset>("month");
  const [custom, setCustom] = useState<{ from: string; to: string } | null>(null);
  const [platform, setPlatform] = useState<Platform>("instagram");
  const range = useMemo(() => rangeFor(preset, custom), [preset, custom]);
  const setRange = (r: { from: string; to: string }) => {
    // keep the range the right way round whichever end was moved
    setCustom(r.from <= r.to ? r : { from: r.to, to: r.from });
    setPreset("custom");
  };
  const showMonth = (ym: string) => {
    if (ym === localIso(new Date()).slice(0, 7)) {
      setPreset("month");
      return;
    }
    const [y, m] = ym.split("-").map(Number);
    setRange({ from: `${ym}-01`, to: localIso(new Date(y, m, 0)) });
  };

  const { data, isLoading, error } = useQuery({
    queryKey: ["store-portfolio", storeId, range.from, range.to],
    queryFn: () => api.get<Portfolio>(`/store-portfolio/${storeId}?start=${range.from}&end=${range.to}`),
    enabled: !!storeId,
  });

  const money = useMemo(() => moneyFmt(data?.store.currency || "INR"), [data?.store.currency]);

  return (
    <ErrorBoundary>
      <div className="space-y-6">
        {/* Header + date filter */}
        <Card className="p-4 sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="flex items-start gap-3 min-w-0">
              <button
                onClick={() => navigate("/sales-overview")}
                className="mt-1 h-9 w-9 shrink-0 rounded-lg border border-[var(--border-subtle)] flex items-center justify-center text-[var(--text-secondary)] hover:text-white"
                aria-label="Back to Store Overview"
              >
                <ArrowLeft size={16} />
              </button>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-xl sm:text-2xl font-extrabold text-white tracking-tight">{data?.store.name || "Store"}</h1>
                  {data && (
                    <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border-subtle)] px-2 py-0.5 text-[11px] font-semibold text-[var(--text-primary)]">
                      <i className="inline-block h-2 w-2 rounded-full" style={{ background: STATUS_COLOR[data.store.is_active ? "good" : "none"] }} />
                      {data.store.is_active ? "Active" : "Inactive"}
                    </span>
                  )}
                </div>
                <p className="text-xs text-[var(--text-muted)] mt-0.5">
                  Store performance portfolio
                  {data && [data.store.region, data.store.country].filter(Boolean).length > 0 && ` · ${[data.store.region, data.store.country].filter(Boolean).join(", ")}`}
                  {data?.store.team_leader && ` · Team leader ${data.store.team_leader}`}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center rounded-xl border border-[var(--border-subtle)] bg-white/5 p-0.5">
                {([["today", "Today"], ["7day", "Last 7 days"], ["month", "This month"]] as const).map(([k, label]) => (
                  <button
                    key={k}
                    onClick={() => setPreset(k)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-medium transition ${preset === k ? "bg-[var(--accent-blue)] text-white" : "text-[var(--text-secondary)] hover:text-white"}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {/* Month: step back/forward, or click the month to pick one */}
              <div className="flex items-center rounded-xl border border-[var(--border-subtle)] bg-white/5 p-0.5">
                <button onClick={() => showMonth(shiftMonth(range.from.slice(0, 7), -1))} aria-label="Previous month"
                  className="h-7 w-7 rounded-lg flex items-center justify-center text-[var(--text-secondary)] hover:text-white hover:bg-white/10">
                  <ChevronLeft size={15} />
                </button>
                <label className="relative flex items-center gap-1.5 px-2 text-xs font-semibold text-white cursor-pointer">
                  <CalendarDays size={13} className="text-[var(--accent-blue)]" />
                  {monthLabel(range.from.slice(0, 7))}
                  <input
                    type="month" value={range.from.slice(0, 7)} aria-label="Pick a month"
                    onChange={(e) => e.target.value && showMonth(e.target.value)}
                    onClick={(e) => openPicker(e.currentTarget)}
                    className="absolute inset-0 opacity-0 cursor-pointer"
                  />
                </label>
                <button onClick={() => showMonth(shiftMonth(range.from.slice(0, 7), 1))} aria-label="Next month"
                  className="h-7 w-7 rounded-lg flex items-center justify-center text-[var(--text-secondary)] hover:text-white hover:bg-white/10">
                  <ChevronRight size={15} />
                </button>
              </div>
              {/* Any range: both dates open the calendar */}
              <div className="flex items-center gap-1.5 rounded-xl border border-[var(--border-subtle)] bg-white/5 px-2 py-1 text-xs">
                {(["from", "to"] as const).map((k) => (
                  <label key={k} className="flex items-center gap-1 text-[var(--text-muted)]">
                    {k === "from" ? "From" : "to"}
                    <input
                      type="date" value={range[k]} aria-label={k === "from" ? "From date" : "To date"}
                      onClick={(e) => openPicker(e.currentTarget)}
                      onChange={(e) => e.target.value && setRange({ ...range, [k]: e.target.value })}
                      className="rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] px-2 py-1 text-xs text-white cursor-pointer focus:outline-none focus:border-blue-500"
                    />
                  </label>
                ))}
              </div>
            </div>
          </div>
          {data && (
            <p className="mt-3 text-[11px] text-[var(--text-muted)]">
              As of {shortDate(data.period.as_of)}
              {data.period.days_remaining > 0 && ` · ${data.period.days_remaining} days left`}
              {data.sales.last_synced_at && ` · MCP synced ${new Date(data.sales.last_synced_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}`}
              {data.sheet_updated_at && ` · Tracker sheet updated ${new Date(data.sheet_updated_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}`}
            </p>
          )}
        </Card>

        {error ? (
          <Card className="p-6 text-sm text-rose-400">{(error as Error).message || "Could not load this store."}</Card>
        ) : isLoading || !data ? (
          <Card className="p-6"><TableSkeleton rows={8} cols={6} /></Card>
        ) : (
          <PortfolioBody data={data} money={money} platform={platform} setPlatform={setPlatform} onViewMonth={showMonth} />
        )}
      </div>
    </ErrorBoundary>
  );
}

function PortfolioBody({ data, money, platform, setPlatform, onViewMonth }: {
  data: Portfolio; money: (n: number | null | undefined) => string; platform: Platform; setPlatform: (p: Platform) => void;
  onViewMonth: (ym: string) => void;
}) {
  const { social, leads, sales, reviews, analysis } = data;
  const sp = social.platforms[platform];
  const shownPlatforms = (Object.keys(social.platforms) as Platform[]).filter((p) => p === "instagram" || social.platforms[p].has_data);
  const statusRows = Object.entries(leads.status_counts).sort((a, b) => b[1] - a[1]);
  const maxStatus = Math.max(1, ...statusRows.map(([, c]) => c));
  const salesPace = sales.pace;
  const salesPoints = sales.series.filter((p) => p.cumulative !== null);
  const lastPoint = salesPoints[salesPoints.length - 1];

  return (
    <>
      {/* Headline KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <Stat icon={BarChart3} label="Revenue" value={money(salesPace.achieved)} sub={`${num(sales.sales_count)} sales · MCP`} />
        <Stat icon={Target} label="Sales achievement" value={salesPace.pct === null ? "—" : `${salesPace.pct}%`}
          sub={PACE_STATUS[salesPace.status].label} subTone={PACE_STATUS[salesPace.status].tone} />
        <Stat icon={Eye} label={`${PLATFORM_LABEL.instagram} views`}
          value={social.has_data ? compact(social.platforms.instagram.achieved) : "—"}
          sub={social.has_data ? `${social.platforms.instagram.pct ?? 0}% of target`
            : social.last_report ? `Not reported yet · ${monthLabel(String(social.last_report.month))}: ${compact(Number(social.last_report.instagram))}`
            : "Not reported"}
          subTone={social.has_data ? PACE_STATUS[social.platforms.instagram.status].tone : "none"} />
        <Stat icon={Users} label="Total leads" value={num(leads.total)} sub={`${leads.volume.pct ?? 0}% of target`}
          subTone={PACE_STATUS[leads.volume.status].tone} />
        <Stat icon={UserCheck} label="Conversions" value={num(leads.converted)} sub={`${leads.conversion_pct}% rate`} />
        <Stat icon={Star} label="Google rating" value={reviews.rating === null ? "—" : `${reviews.rating.toFixed(1)} ★`}
          sub={reviews.rating_as_of ? `As of ${shortDate(reviews.rating_as_of)}` : undefined} />
      </div>

      {analysis.concerns.length > 0 && (
        <div className="flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">
          <AlertTriangle size={15} className="shrink-0 mt-0.5" />
          <p><span className="font-semibold">Needs attention:</span> {analysis.concerns.join(" · ")}.</p>
        </div>
      )}

      {/* 1. Social */}
      <Section n={1} title="Social Media Performance" icon={Megaphone} right={
        <div className="flex items-center rounded-xl border border-[var(--border-subtle)] bg-white/5 p-0.5">
          {shownPlatforms.map((p) => (
            <button key={p} onClick={() => setPlatform(p)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition ${platform === p ? "bg-[var(--accent-blue)] text-white" : "text-[var(--text-secondary)] hover:text-white"}`}>
              {PLATFORM_LABEL[p]}
            </button>
          ))}
        </div>
      }>
        {!social.has_data ? (
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-4 text-sm">
            <p className="font-semibold text-white">
              No Daily Tracker row for {shortDate(data.period.start)} – {shortDate(data.period.end)} yet.
            </p>
            {social.last_report && (
              <p className="mt-1 text-xs text-[var(--text-secondary)]">
                The sheet's latest row for this store is dated {monthLabel(String(social.last_report.month))}, so its figures belong to that month.{" "}
                <button onClick={() => onViewMonth(String(social.last_report!.month))}
                  className="font-semibold text-[var(--accent-blue)] hover:underline">
                  View {monthLabel(String(social.last_report.month))} →
                </button>
              </p>
            )}
            {social.last_report && (
              <p className="mt-1 text-xs text-[var(--text-secondary)]">
                Last report ({monthLabel(String(social.last_report.month))}, up to {shortDate(String(social.last_report.as_of))}):{" "}
                {num(Number(social.last_report[platform]))} {PLATFORM_LABEL[platform]} views
                {social.last_report[`${platform}_pct`] !== null && ` · ${social.last_report[`${platform}_pct`]}% of target`}
                {` · ${num(Number(social.last_report.reels))} reels`}
              </p>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
            <Stat icon={Film} label="Reels published" value={num(social.reels)} />
            <Stat icon={Eye} label={`${PLATFORM_LABEL[platform]} views`} value={num(sp.achieved)} sub={`of ${num(sp.target)}`} />
            <Stat icon={MessageSquare} label="Comments" value={num(social.comments)} />
            <Stat icon={Share2} label="Shares" value={num(social.shares)} />
            <Stat icon={Bookmark} label="Saves" value={num(social.saves)} />
            <Stat icon={Repeat2} label="Reposts" value={num(social.reposts)} />
          </div>
        )}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-semibold text-white">{PLATFORM_LABEL[platform]} views by month vs target</p>
              <div className="flex items-center gap-3 text-[11px] text-[var(--text-secondary)]">
                <span className="flex items-center gap-1.5"><i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: CHART_BLUE }} />Views</span>
                <span className="flex items-center gap-1.5"><i className="inline-block w-4 border-t-2 border-dashed border-[#a1a1aa]" />Target to date</span>
              </div>
            </div>
            {social.monthly.length === 0 ? (
              <p className="py-12 text-center text-xs text-[var(--text-muted)]">No months reported in the tracker sheet yet.</p>
            ) : (
              <div className="h-60 mt-2">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={social.monthly} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} />
                    <XAxis dataKey="month" tick={AXIS_TICK} tickFormatter={monthLabel} />
                    <YAxis tick={AXIS_TICK} tickFormatter={compact} width={48} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "var(--border-subtle)" }}
                      labelFormatter={(_l, items) => {
                        const m = items?.[0]?.payload as SocialMonth | undefined;
                        return m ? `${monthLabel(m.month)} · up to ${shortDate(String(m.as_of))}` : "";
                      }}
                      formatter={(v, name) => [num(Number(v)), name === platform ? "Views" : "Target to date"]} />
                    <Bar dataKey={platform} fill={CHART_BLUE} radius={[4, 4, 0, 0]} maxBarSize={36} isAnimationActive={false} />
                    <Line dataKey={`${platform}_target`} stroke="#a1a1aa" strokeWidth={2} strokeDasharray="5 4"
                      dot={{ r: 4, fill: "#a1a1aa", strokeWidth: 0 }} isAnimationActive={false} />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            )}
            <p className="mt-1 text-[11px] text-[var(--text-muted)]">
              The tracker sheet gives one month-to-date figure per month, so each month is compared with its target up to the date it was filled to.
            </p>
          </div>
          {social.has_data ? (
            <div className="space-y-2">
              <TargetCard title={`${PLATFORM_LABEL[platform]} views target`} pace={sp} fmt={num} unit="views" />
              {social.as_of && <p className="text-[11px] text-[var(--text-muted)] text-center">Sheet figures up to {shortDate(social.as_of)}</p>}
            </div>
          ) : (
            <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-4 text-sm">
              <p className="font-semibold text-white">{PLATFORM_LABEL[platform]} views target</p>
              <p className="mt-2 text-3xl font-extrabold text-white tabular-nums">{num(sp.monthly_target)}</p>
              <p className="text-xs text-[var(--text-muted)]">per month · {num(sp.target)} for this period</p>
            </div>
          )}
        </div>
      </Section>

      {/* 2. Leads */}
      <Section n={2} title="Leads & Conversions" icon={Users}>
        <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
          <Stat icon={Target} label="Lead target (month)" value={num(leads.targets.leads_monthly)} sub={`${num(leads.volume.target)} for this period`} />
          <Stat icon={Users} label="Leads received" value={num(leads.total)} sub={`${leads.volume.pct ?? 0}% · ${PACE_STATUS[leads.volume.status].label}`}
            subTone={PACE_STATUS[leads.volume.status].tone} />
          <Stat icon={UserCheck} label="Conversions" value={num(leads.converted)} sub={`${leads.conversion_pct}% · ${money(leads.revenue)}`} />
          <Stat icon={TrendingUp} label="Conversion target" value={`${leads.conversion_target_pct}%`}
            sub={`${num(leads.conversions.remaining)} more to reach ${num(leads.conversions.target)}`}
            subTone={PACE_STATUS[leads.conversions.status].tone} />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
          <div className="lg:col-span-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] overflow-x-auto">
            <table className="w-full min-w-[480px] text-xs">
              <thead>
                <tr className="border-b border-[var(--border-subtle)] text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                  <th className="py-2.5 px-3 text-left font-semibold">Source</th>
                  <th className="py-2.5 px-3 text-right font-semibold">Leads</th>
                  <th className="py-2.5 px-3 text-right font-semibold">Converted</th>
                  <th className="py-2.5 px-3 text-right font-semibold">Rate</th>
                  <th className="py-2.5 px-3 text-right font-semibold">Revenue</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-subtle)]">
                {leads.sources.map((s) => (
                  <tr key={s.key} className={s.leads ? "" : "text-[var(--text-muted)]"}>
                    <td className="py-2 px-3 font-medium text-white">
                      {s.label}
                      {s.tracker && (
                        <span className="block text-[10px] font-normal text-[var(--text-muted)]">{s.tracker.label}: {num(s.tracker.value)}</span>
                      )}
                    </td>
                    <td className="py-2 px-3 text-right tabular-nums">{num(s.leads)}</td>
                    <td className="py-2 px-3 text-right tabular-nums">{num(s.converted)}</td>
                    <td className="py-2 px-3 text-right tabular-nums">{s.leads ? `${s.rate}%` : "—"}</td>
                    <td className="py-2 px-3 text-right tabular-nums">{money(s.revenue)}</td>
                  </tr>
                ))}
                <tr className="font-bold text-white bg-blue-500/5">
                  <td className="py-2.5 px-3">Total</td>
                  <td className="py-2.5 px-3 text-right tabular-nums">{num(leads.total)}</td>
                  <td className="py-2.5 px-3 text-right tabular-nums">{num(leads.converted)}</td>
                  <td className="py-2.5 px-3 text-right tabular-nums">{leads.conversion_pct}%</td>
                  <td className="py-2.5 px-3 text-right tabular-nums">{money(leads.revenue)}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div className="lg:col-span-2 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-4 space-y-2.5">
            <p className="text-sm font-semibold text-white">Current lead status</p>
            {statusRows.length === 0 ? (
              <p className="text-xs text-[var(--text-muted)]">No leads in this period.</p>
            ) : statusRows.map(([status, count]) => (
              <div key={status} className="grid grid-cols-[110px_1fr_44px] items-center gap-2 text-xs" title={`${status}: ${count}`}>
                <span className="truncate text-[var(--text-secondary)]">{status}</span>
                <div className="h-2.5 rounded-full bg-[var(--border-subtle)] overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${(count / maxStatus) * 100}%`, background: CHART_BLUE }} />
                </div>
                <span className="text-right font-semibold text-white tabular-nums">{num(count)}</span>
              </div>
            ))}
            <div className="mt-2 grid grid-cols-3 gap-2 border-t border-[var(--border-subtle)] pt-3 text-center text-xs">
              <div><p className="font-bold text-white tabular-nums">{num(leads.visits.attended)}</p><p className="text-[var(--text-muted)]">Store visits</p></div>
              <div><p className="font-bold text-white tabular-nums">{num(leads.visits.scheduled)}</p><p className="text-[var(--text-muted)]">Visits planned</p></div>
              <div><p className="font-bold text-white tabular-nums">{num(leads.visits.no_show)}</p><p className="text-[var(--text-muted)]">No-shows</p></div>
            </div>
            {leads.volume.remaining > 0 && (
              <p className="rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                {num(leads.volume.remaining)} leads remaining
                {leads.volume.required_daily !== null && ` · ${num(leads.volume.required_daily)}/day required`}
              </p>
            )}
          </div>
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-4 text-xs space-y-1.5">
            <p className="text-sm font-semibold text-white">How these leads were linked to this store</p>
            {Object.keys(leads.matched_by).length === 0 ? (
              <p className="text-[var(--text-muted)]">No leads are linked to this store in this period.</p>
            ) : Object.entries(leads.matched_by).sort((a, b) => b[1] - a[1]).map(([how, n]) => (
              <p key={how} className="flex justify-between gap-2 text-[var(--text-secondary)]">
                <span className="first-letter:uppercase">{how}</span><span className="font-semibold text-white tabular-nums">{num(n)}</span>
              </p>
            ))}
            {leads.duplicates_merged > 0 && (
              <p className="text-[var(--text-muted)]">{num(leads.duplicates_merged)} duplicate {leads.duplicates_merged === 1 ? "copy" : "copies"} (same phone within a week, from the sheet, Meta or the website) counted once.</p>
            )}
            <p className="pt-1 text-[11px] text-[var(--text-muted)]">
              City sheets only say the area. A lead counts here when it has this store, an appointment here, is the only shop in its area, or its remarks name this shop.
            </p>
          </div>
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-4 text-xs">
            <p className="text-sm font-semibold text-white">{leads.area_label ? `${leads.area_label} area leads — shop not known` : "Area leads"}</p>
            {!leads.area ? (
              <p className="mt-1.5 text-[var(--text-muted)]">
                {leads.area_label ? "Every lead from this area in the period is linked to a shop." : "This store isn't in one of the city-sheet areas."}
              </p>
            ) : (
              <>
                <p className="mt-1 text-[var(--text-secondary)]">
                  <span className="text-2xl font-extrabold text-white tabular-nums mr-1.5">{num(leads.area.total)}</span>
                  leads shared by {leads.area.shops} shops · {num(leads.area.converted)} converted
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {Object.entries(leads.area.status_counts).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([st, n]) => (
                    <span key={st} className="rounded-full border border-[var(--border-subtle)] px-2 py-0.5 text-[11px] text-[var(--text-secondary)]">{st}: <b className="text-white">{num(n)}</b></span>
                  ))}
                </div>
                <p className="mt-2 text-[11px] text-[var(--text-muted)]">Not counted against this store's target. Booking a lead's store visit links it to that shop.</p>
              </>
            )}
          </div>
        </div>
      </Section>

      {/* 3. Sales */}
      <Section n={3} title="Sales Performance" icon={BarChart3}>
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
          <Stat icon={Target} label="Monthly target" value={money(sales.monthly_target)} sub={salesPace.days_total !== 0 ? `${money(salesPace.target)} for this period` : undefined} />
          <Stat icon={BarChart3} label="Achieved" value={money(salesPace.achieved)} sub="From MCP" />
          <Stat icon={CheckCircle2} label="Achievement" value={salesPace.pct === null ? "—" : `${salesPace.pct}%`}
            sub={PACE_STATUS[salesPace.status].label} subTone={PACE_STATUS[salesPace.status].tone} />
          <Stat icon={AlertTriangle} label="Remaining" value={money(salesPace.remaining)} sub={`${salesPace.days_remaining} days left`} />
          <Stat icon={TrendingUp} label="Required daily" value={salesPace.required_daily === null ? "—" : money(salesPace.required_daily)}
            sub={`Current ${money(salesPace.current_daily)}/day`} />
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-semibold text-white">Cumulative revenue vs target pace</p>
              <div className="flex items-center gap-3 text-[11px] text-[var(--text-secondary)]">
                <span className="flex items-center gap-1.5"><i className="inline-block h-0.5 w-4" style={{ background: CHART_BLUE }} />Actual revenue</span>
                <span className="flex items-center gap-1.5"><i className="inline-block w-4 border-t-2 border-dashed border-[#a1a1aa]" />Target pace</span>
              </div>
            </div>
            <div className="h-60 mt-2">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={sales.series} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} />
                  <XAxis dataKey="date" tick={AXIS_TICK} tickFormatter={shortDate} minTickGap={16} />
                  <YAxis tick={AXIS_TICK} tickFormatter={compact} width={52} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(l) => shortDate(String(l))}
                    formatter={(v, name) => [money(Number(v)), name === "cumulative" ? "Actual" : "Target pace"]} />
                  <Line type="monotone" dataKey="target_pace" stroke="#a1a1aa" strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="cumulative" stroke={CHART_BLUE} strokeWidth={2} dot={false} connectNulls={false}
                    activeDot={{ r: 5 }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            {lastPoint && (
              <p className="mt-1 text-[11px] text-[var(--text-muted)]">
                {shortDate(lastPoint.date)}: actual {money(lastPoint.cumulative)} vs expected {money(lastPoint.target_pace)}
              </p>
            )}
          </div>
          <div className="space-y-3">
            <TargetCard title="Sales target" pace={salesPace} fmt={(n) => money(n)} unit="" />
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-3">
                <p className="text-[var(--text-muted)]">Average bill</p>
                <p className="text-base font-bold text-white tabular-nums">{money(sales.avg_bill)}</p>
              </div>
              <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-3">
                <p className="text-[var(--text-muted)]">Sales needed</p>
                <p className="text-base font-bold text-white tabular-nums">{salesPace.remaining > 0 ? `≈ ${num(sales.sales_needed)}` : "—"}</p>
              </div>
            </div>
          </div>
        </div>
      </Section>

      {/* 4. Reviews */}
      <Section n={4} title="Google Reviews" icon={Star}>
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
          <Stat icon={Star} label="Overall rating" value={reviews.rating === null ? "—" : `${reviews.rating.toFixed(1)} / 5`}
            sub={reviews.rating_as_of
              ? `As of ${shortDate(reviews.rating_as_of)}${reviews.rating_previous !== null && reviews.rating !== null && reviews.rating_previous !== reviews.rating
                ? ` · ${reviews.rating > reviews.rating_previous ? "up" : "down"} from ${reviews.rating_previous.toFixed(1)}` : ""}`
              : undefined}
            subTone={reviews.rating === null ? undefined : reviews.rating >= 4.8 ? "good" : reviews.rating >= 4.5 ? "warn" : "crit"} />
          <Stat icon={MessageSquare} label="New reviews" value={num(reviews.new_reviews)} sub="This period" />
          <Stat icon={ClipboardList} label="Total reviews" value={reviews.total_reviews === null ? "—" : num(reviews.total_reviews)} />
          <Stat icon={CheckCircle2} label="Positive / negative"
            value={reviews.positive === null && reviews.negative === null ? "—" : `${num(reviews.positive ?? 0)} / ${num(reviews.negative ?? 0)}`}
            sub={reviews.positive === null && reviews.negative === null ? "Not tracked in the sheet yet" : undefined} />
          <Stat icon={Repeat2} label="Replying to reviews" value={reviews.response || "—"}
            sub={reviews.unanswered !== null ? `${num(reviews.unanswered)} unanswered` : undefined}
            subTone={reviews.response === "Yes" ? "good" : reviews.response === "Partial" ? "warn" : reviews.response === "No" ? "crit" : undefined} />
        </div>
        {Object.keys(reviews.extra_columns).length > 0 && (
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-4">
            <p className="text-sm font-semibold text-white mb-2">More from the tracker sheet</p>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
              {Object.entries(reviews.extra_columns).map(([label, v]) => (
                <div key={label}><p className="text-[var(--text-muted)]">{label}</p><p className="font-bold text-white tabular-nums">{typeof v === "number" ? num(v) : v}</p></div>
              ))}
            </div>
          </div>
        )}
      </Section>

      {/* 5. Analysis */}
      <Section n={5} title="Overall Analysis & Action Plan" icon={ClipboardList}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-4">
            <p className="text-sm font-semibold text-white mb-2 flex items-center gap-2">
              <i className="inline-block h-2 w-2 rounded-full" style={{ background: STATUS_COLOR.good }} />Performing well
            </p>
            {analysis.strengths.length ? (
              <ul className="space-y-1 text-xs text-[var(--text-secondary)] list-disc pl-4">{analysis.strengths.map((s) => <li key={s}>{s}</li>)}</ul>
            ) : <p className="text-xs text-[var(--text-muted)]">Nothing on pace yet this period.</p>}
          </div>
          <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-4">
            <p className="text-sm font-semibold text-white mb-2 flex items-center gap-2">
              <i className="inline-block h-2 w-2 rounded-full" style={{ background: STATUS_COLOR.crit }} />Falling behind
            </p>
            {analysis.concerns.length ? (
              <ul className="space-y-1 text-xs text-[var(--text-secondary)] list-disc pl-4">{analysis.concerns.map((s) => <li key={s}>{s}</li>)}</ul>
            ) : <p className="text-xs text-[var(--text-muted)]">Every area is on pace.</p>}
          </div>
        </div>
        <div className="rounded-xl border border-[var(--border-subtle)] overflow-x-auto">
          <table className="w-full min-w-[720px] text-xs">
            <thead>
              <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-primary)] text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                <th className="py-2.5 px-3 text-left font-semibold w-44">Area</th>
                <th className="py-2.5 px-3 text-left font-semibold">Gap & required pace</th>
                <th className="py-2.5 px-3 text-left font-semibold">Recommended next step</th>
                <th className="py-2.5 px-3 text-left font-semibold w-28">Priority</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border-subtle)]">
              {analysis.rows.map((r) => {
                const A = AREA[r.area];
                return (
                  <tr key={r.area} className="align-top">
                    <td className="py-3 px-3 font-semibold text-white"><span className="flex items-center gap-2"><A.icon size={15} className="text-[var(--accent-blue)]" />{A.label}</span></td>
                    <td className="py-3 px-3 text-[var(--text-secondary)]">{r.gap}</td>
                    <td className="py-3 px-3 text-[var(--text-primary)]">{r.action}</td>
                    <td className="py-3 px-3">
                      <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border-subtle)] px-2 py-0.5 text-[11px] font-semibold text-[var(--text-primary)] whitespace-nowrap">
                        <i className="inline-block h-2 w-2 rounded-full" style={{ background: STATUS_COLOR[PRIORITY_TONE[r.priority] || "none"] }} />
                        {r.priority}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="text-[11px] text-[var(--text-muted)]">
          Worked out automatically from the figures above. Targets are monthly and spread evenly over each day of the month; pace compares what's done so far with what the target expects by {shortDate(data.period.as_of)}.
        </p>
      </Section>
    </>
  );
}
