import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Eye, RefreshCw, FileSpreadsheet, Video, UserPlus, MessageCircle, Footprints, Star,
  MessageSquareReply, Search, AlertTriangle, Trophy, Clock, Target,
} from "lucide-react";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { EmptyState } from "@/components/shared/EmptyState";
import { Modal } from "@/features/crm/components/ui";
import { useSocketRefresh } from "@/hooks/useSocketRefresh";
import { api } from "@/lib/apiClient";
import {
  useSocialPerformance, totalsOf, overallStatus, statusRank, attentionReasons,
  viewsStatus, ratingStatus, repliedStatus, freshnessStatus, fmtCompact, monthLabel,
  fmtDateTime, fmtPeriod, timeAgo,
  COUNTRY_LABEL, STATUS_COLOR, STATUS_ICON, RATING_GOOD, RATING_WARN, STALE_DAYS,
  PLATFORMS, PLATFORM_LABEL, PLATFORM_COLOR,
  Platform, SocialScope, SocialStore, SocialTotals, Status,
} from "@/features/social/socialData";
import { Card, Tip, StatusPill, StatusLegend, BarRow, StatusBar } from "@/features/social/ui";

const VIEWS_CAP = 300; // bars stop at 300% of target; the label shows the real value

const FRESH_LABEL: Record<Status, string> = { good: "Up to date", warn: "Few days old", crit: "Stale", none: "Never updated" };

/** Social performance for whoever is logged in: every store for admin
 * roles, a team leader's own stores, or a store account's store(s). Used as
 * the /social-performance page and as the store accounts' home dashboard. */
export default function SocialPerformance() {
  useSocketRefresh(["sheets-data"]);
  const [month, setMonth] = useState<string | undefined>();
  const [country, setCountry] = useState("ALL");
  const [showStatus, setShowStatus] = useState(false);
  const { scope, months, month: active, lastSyncedAt, stores: allStores, isLoading, error, empty } = useSocialPerformance(month);

  const countries = useMemo(() => [...new Set(allStores.map((s) => s.country).filter(Boolean))], [allStores]);
  const stores = useMemo(
    () => (country === "ALL" ? allStores : allStores.filter((s) => s.country === country)),
    [allStores, country],
  );
  const t = useMemo(() => totalsOf(stores), [stores]);

  return (
    <ErrorBoundary>
      <div className="space-y-6 w-full min-w-0">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-white flex flex-wrap items-center gap-2">
              Social Performance
              {scope && scope.kind !== "company" && (
                <span className="rounded-full border border-[var(--border-subtle)] px-2.5 py-0.5 text-xs font-semibold text-blue-300">{scope.label}</span>
              )}
            </h2>
            <p className="text-xs text-[var(--text-muted)]">
              Reach, engagement, leads and Google reviews{stores.length === 1 ? "" : " per store"} · from the BP Store Daily Tracker sheet
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {months.length > 0 && (
              <select
                value={active}
                onChange={(e) => setMonth(e.target.value)}
                className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-card)] px-3 py-1.5 text-xs text-white"
                aria-label="Month"
              >
                {months.map((m) => <option key={m} value={m}>{monthLabel(m)}</option>)}
              </select>
            )}
            {countries.length > 1 && (
              <div className="flex flex-wrap gap-1 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-card)] p-1">
                {["ALL", ...countries].map((c) => (
                  <button
                    key={c}
                    onClick={() => setCountry(c)}
                    className={`rounded-md px-2.5 py-1 text-xs font-semibold transition-colors ${
                      country === c ? "bg-blue-500/20 text-blue-300" : "text-[var(--text-muted)] hover:text-white"
                    }`}
                  >
                    {c === "ALL" ? "All countries" : COUNTRY_LABEL[c] || c}
                  </button>
                ))}
              </div>
            )}
            {stores.length > 0 && (
              <button
                onClick={() => setShowStatus(true)}
                className="flex items-center gap-1.5 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-card)] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[var(--bg-card-hover)]"
              >
                <Clock size={14} className="text-[var(--text-muted)]" />
                Sheet update status
                {t.freshCounts.crit + t.freshCounts.none > 0 && (
                  <span className="rounded-full bg-rose-500/15 px-1.5 text-[10px] text-rose-300">{t.freshCounts.crit + t.freshCounts.none}</span>
                )}
              </button>
            )}
          </div>
        </div>

        {scope && <SheetSyncBar scope={scope} lastSyncedAt={lastSyncedAt} stores={stores} />}

        {isLoading ? (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-6"><TableSkeleton /></div>
        ) : error ? (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-8 text-center">
            <AlertTriangle size={32} className="mx-auto mb-2 text-rose-400" />
            <p className="text-sm font-semibold text-white">Couldn't load social performance data</p>
            <p className="text-xs text-[var(--text-muted)] mt-1">Check the backend connection and the Daily Tracker sync.</p>
          </div>
        ) : empty || !stores.length ? (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)]">
            <EmptyState
              title={scope?.kind === "company" ? "No social data yet" : "No store linked to your account"}
              description={scope?.kind === "company"
                ? "Nothing has been synced from the Daily Input tab of the tracker sheet for this selection."
                : "Ask an admin to link your account to your store(s) in Settings → Users (or Team Leaders & Branches)."}
            />
          </div>
        ) : (
          <Content stores={stores} t={t} scope={scope!} />
        )}

        <UpdateStatusModal open={showStatus} onClose={() => setShowStatus(false)} stores={stores} showTl={scope?.kind === "company"} />
      </div>
    </ErrorBoundary>
  );
}

/** When the sheet was last read, when a single store last updated it, and —
 * for admins — a button to re-read the sheet now. */
function SheetSyncBar({ scope, lastSyncedAt, stores }: { scope: SocialScope; lastSyncedAt: string | null; stores: SocialStore[] }) {
  const qc = useQueryClient();
  const statusQ = useQuery({
    queryKey: ["sheets-data", "tracker-sync-status"],
    enabled: scope.can_sync,
    queryFn: async () => {
      const res = await api.fetchRaw("/sync/daily-tracker/status");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    refetchInterval: 60_000,
  });
  const sync = useMutation({
    mutationFn: async () => {
      const res = await api.fetchRaw("/sync/daily-tracker", { method: "POST" });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || "Sync failed");
      if (body.status && body.status !== "ok") throw new Error(body.message || "The sheet synced with errors");
      return body;
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["sheets-data"] }),
  });

  const st = statusQ.data;
  const single = stores.length === 1 ? stores[0] : null;
  let text = lastSyncedAt ? `Daily Tracker sheet last synced ${timeAgo(lastSyncedAt)}` : "The Daily Tracker sheet hasn't been synced yet";
  if (scope.can_sync && st && !st.configured) text = "The Daily Tracker sheet isn't set up as a sync source (Settings → Data Sync)";

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 bg-[var(--bg-card)] border border-[var(--border-subtle)] p-3 rounded-2xl">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[var(--text-muted)] min-w-0">
        <FileSpreadsheet size={16} className="shrink-0 text-emerald-400" />
        <span title={lastSyncedAt ? fmtDateTime(lastSyncedAt) : undefined}>{text}</span>
        {st?.configured && st.enabled && st.interval_minutes ? (
          <span className="hidden sm:inline">· auto-syncs every {st.interval_minutes} min</span>
        ) : st?.configured && !st.enabled ? (
          <span className="text-amber-400">· auto-sync is turned off</span>
        ) : null}
        {single && (
          <span className="inline-flex items-center gap-1.5">
            · {single.store} last updated the sheet
            <b className="text-white">{fmtDateTime(single.lastUpdatedAt)}</b>
            <i className="inline-block h-2 w-2 rounded-full" style={{ background: STATUS_COLOR[freshnessStatus(single.lastUpdatedAt)] }} />
          </span>
        )}
        {st?.last_status === "error" && !sync.isPending && <span className="text-rose-400">· last sync had errors</span>}
        {sync.isError && <span className="text-rose-400">· {(sync.error as Error).message}</span>}
        {sync.isSuccess && !sync.isPending && <span className="text-emerald-400">· synced {sync.data?.rows_synced ?? 0} rows</span>}
      </div>
      {scope.can_sync && (
        <button
          onClick={() => sync.mutate()}
          disabled={sync.isPending || (st && !st.configured)}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-[var(--accent-blue)] text-white hover:opacity-90 transition disabled:opacity-50"
        >
          <RefreshCw size={14} className={sync.isPending ? "animate-spin" : ""} />
          {sync.isPending ? "Syncing..." : "Sync Sheet Now"}
        </button>
      )}
    </div>
  );
}

function UpdateStatusModal({ open, onClose, stores, showTl }: { open: boolean; onClose: () => void; stores: SocialStore[]; showTl: boolean }) {
  const rows = [...stores].sort((a, b) => {
    if (!a.lastUpdatedAt) return b.lastUpdatedAt ? -1 : a.store.localeCompare(b.store);
    if (!b.lastUpdatedAt) return 1;
    return a.lastUpdatedAt.localeCompare(b.lastUpdatedAt);
  });
  const counts: Record<Status, number> = { good: 0, warn: 0, crit: 0, none: 0 };
  stores.forEach((s) => counts[freshnessStatus(s.lastUpdatedAt)]++);
  return (
    <Modal open={open} onClose={onClose} wide title="Sheet update status">
      <p className="text-xs text-[var(--text-muted)] mb-3">
        When each store last changed its row in the Daily Tracker sheet (checked on every sync), oldest first.
        Up to date = within a day · few days old = within {STALE_DAYS} days · stale = older.
      </p>
      <div className="mb-4 flex flex-wrap gap-3 text-xs">
        {(["good", "warn", "crit", "none"] as Status[]).map((s) => (
          <span key={s} className="inline-flex items-center gap-1.5 text-[var(--text-secondary)]">
            <i className="inline-block h-2 w-2 rounded-full" style={{ background: STATUS_COLOR[s] }} />
            <b className="text-white">{counts[s]}</b> {FRESH_LABEL[s].toLowerCase()}
          </span>
        ))}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs border-collapse min-w-[520px]">
          <thead>
            <tr className="border-b border-[var(--border-subtle)] text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
              <th className="py-2 pr-2 text-left font-semibold">Store</th>
              {showTl && <th className="py-2 px-2 text-left font-semibold">Team leader</th>}
              <th className="py-2 px-2 text-left font-semibold">Last updated in sheet</th>
              <th className="py-2 px-2 text-left font-semibold">Data up to</th>
              <th className="py-2 pl-2 text-right font-semibold">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border-subtle)]">
            {rows.map((s) => {
              const f = freshnessStatus(s.lastUpdatedAt);
              return (
                <tr key={s.storeId}>
                  <td className="py-2 pr-2 font-medium text-white whitespace-nowrap">{s.store}</td>
                  {showTl && <td className="py-2 px-2 text-[var(--text-secondary)] whitespace-nowrap">{s.teamLeader || "—"}</td>}
                  <td className="py-2 px-2 whitespace-nowrap">
                    <span className="text-white">{fmtDateTime(s.lastUpdatedAt)}</span>
                    {s.lastUpdatedAt && <span className="text-[var(--text-muted)]"> · {timeAgo(s.lastUpdatedAt)}</span>}
                  </td>
                  <td className="py-2 px-2 text-[var(--text-secondary)] whitespace-nowrap">{fmtPeriod(s.lastPeriod)}</td>
                  <td className="py-2 pl-2 text-right"><StatusPill status={f} label={FRESH_LABEL[f]} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Modal>
  );
}

function Content({ stores, t, scope }: { stores: SocialStore[]; t: SocialTotals; scope: SocialScope }) {
  const multi = stores.length > 1;
  const shownPlatforms: Platform[] = t.activePlatforms.length ? t.activePlatforms : ["instagram"];
  const single = multi ? null : stores[0];

  const kpis: { label: string; value: string; sub: string; meter?: number; icon: React.ReactNode; color: string }[] = [
    ...shownPlatforms.map((p) => ({
      label: `${PLATFORM_LABEL[p]} views`,
      value: fmtCompact(t.platforms[p].views),
      sub: `${Math.round(t.platforms[p].pct)}% of ${fmtCompact(t.platforms[p].target)} target`,
      meter: t.platforms[p].pct / 100,
      icon: <Eye size={18} />,
      color: PLATFORM_COLOR[p],
    })),
    { label: "Videos posted", value: String(t.videos), sub: multi ? `${t.storesPosted} of ${t.stores} stores posted` : `${single!.posts} posts published`, icon: <Video size={18} />, color: "#a855f7" },
    { label: "New followers", value: `+${fmtCompact(t.newFollowers)}`, sub: `${fmtCompact(t.followers)} total on Instagram`, icon: <UserPlus size={18} />, color: "#8b5cf6" },
    { label: "Instagram DMs", value: fmtCompact(t.dms), sub: `${fmtCompact(t.manychat)} handled by Manychat`, icon: <MessageCircle size={18} />, color: "#06b6d4" },
    { label: "Walk-ins booked", value: fmtCompact(t.walkins), sub: "all sources (WhatsApp, phone, in-store)", icon: <Footprints size={18} />, color: "#10b981" },
    multi
      ? { label: "Avg Google rating", value: t.avgRating ? `${t.avgRating.toFixed(2)} ★` : "—", sub: `${t.ratingGood} stores ≥ ${RATING_GOOD} · ${t.ratingCrit} below ${RATING_WARN}`, icon: <Star size={18} />, color: "#f59e0b" }
      : { label: "Google rating", value: single!.rating ? `${single!.rating.toFixed(1)} ★` : "—", sub: `target ≥ ${RATING_GOOD} ★`, icon: <Star size={18} />, color: "#f59e0b" },
    multi
      ? { label: "Reviews replied", value: `${t.repliedAll}/${t.ratedStores}`, sub: `stores replied to all · ${fmtCompact(t.reviews)} reviews`, meter: t.ratedStores ? t.repliedAll / t.ratedStores : undefined, icon: <MessageSquareReply size={18} />, color: "#f97316" }
      : { label: "Google reviews", value: String(single!.reviews), sub: `replied to all: ${single!.replied || "not filled"}`, icon: <MessageSquareReply size={18} />, color: "#f97316" },
  ];

  return (
    <>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3 min-w-0">
        {kpis.map((k) => (
          <div key={k.label} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 relative overflow-hidden min-w-0">
            <div className="absolute top-0 left-0 right-0 h-0.5" style={{ background: k.color }} />
            <div className="flex items-center gap-2 mb-2">
              <div className="p-1.5 rounded-lg" style={{ background: `${k.color}20`, color: k.color }}>{k.icon}</div>
              <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] leading-tight">{k.label}</p>
            </div>
            <p className="text-xl font-extrabold text-white">{k.value}</p>
            <p className="text-[11px] text-[var(--text-muted)] mt-0.5 leading-snug">{k.sub}</p>
            {k.meter !== undefined && (
              <div className="mt-2 h-1.5 rounded-full bg-[var(--border-subtle)] overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${Math.min(100, k.meter * 100)}%`, background: k.color }} />
              </div>
            )}
          </div>
        ))}
      </div>

      <TargetsCard t={t} scope={scope} stores={stores} />

      {multi && <HealthRow stores={stores} t={t} />}

      <div className={`grid grid-cols-1 ${multi ? "xl:grid-cols-[1.3fr_1fr]" : "lg:grid-cols-2"} gap-6 min-w-0`}>
        {multi && <ViewsCard stores={stores} platforms={shownPlatforms} />}
        <div className="space-y-6 min-w-0">
          <FunnelCard t={t} />
          {multi && <EngagementCard stores={stores} />}
        </div>
        {!multi && <EngagementBreakdown s={single!} />}
      </div>

      {multi && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 min-w-0">
          <RatingCard stores={stores} />
          <ReviewsCard stores={stores} />
        </div>
      )}

      {multi && <CoverageCard stores={stores} />}
      {multi && <ScorecardTable stores={stores} platforms={shownPlatforms} showTl={scope.kind === "company"} />}
    </>
  );
}

/** Views against target per platform for everything in view — for a team
 * leader that's the sum of their stores' targets. */
function TargetsCard({ t, scope, stores }: { t: SocialTotals; scope: SocialScope; stores: SocialStore[] }) {
  const shown: Platform[] = t.activePlatforms.length ? t.activePlatforms : ["instagram"];
  const hidden = PLATFORMS.filter((p) => !shown.includes(p));
  const who = scope.kind === "team_leader"
    ? `Your target is the sum of your ${stores.length} stores' targets`
    : stores.length === 1
      ? `${stores[0].store}'s monthly targets`
      : scope.kind === "store" ? `Sum of your ${stores.length} stores' targets` : `Sum of all ${stores.length} stores' targets`;
  return (
    <Card title="Views vs target" subtitle={`${who} · set by admin in Settings → Social Targets`} right={<Target size={18} className="text-blue-400 shrink-0" />}>
      <div className="space-y-4">
        {shown.map((p) => {
          const pt = t.platforms[p];
          const st = viewsStatus(pt.pct);
          return (
            <div key={p}>
              <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs mb-1.5">
                <span className="font-semibold text-white flex items-center gap-2">
                  <i className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: PLATFORM_COLOR[p] }} />
                  {PLATFORM_LABEL[p]}
                  {stores.length > 1 && <span className="font-normal text-[var(--text-muted)]">· {pt.storesReporting} of {stores.length} stores reporting</span>}
                </span>
                <span className="tabular-nums text-[var(--text-secondary)]">
                  <b className="text-white">{fmtCompact(pt.views)}</b> of {fmtCompact(pt.target)} · <b className="text-white">{STATUS_ICON[st]} {Math.round(pt.pct)}%</b>
                </span>
              </div>
              <Tip content={`${PLATFORM_LABEL[p]}: ${pt.views.toLocaleString("en-IN")} of ${pt.target.toLocaleString("en-IN")} views`}>
                <div className="relative h-3 rounded-full bg-[var(--border-subtle)] overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${Math.min(100, pt.pct)}%`, background: STATUS_COLOR[st] }} />
                </div>
              </Tip>
            </div>
          );
        })}
      </div>
      {hidden.length > 0 && (
        <p className="text-[11px] text-[var(--text-muted)] mt-4">
          {hidden.map((p) => PLATFORM_LABEL[p]).join(" and ")} will appear here once the sheet has views for {hidden.length === 1 ? "it" : "them"}.
        </p>
      )}
    </Card>
  );
}

function HealthRow({ stores, t }: { stores: SocialStore[]; t: SocialTotals }) {
  const attention = useMemo(
    () => stores
      .map((s) => ({ s, st: overallStatus(s), why: attentionReasons(s) }))
      .filter((x) => x.st === "crit" || x.st === "warn")
      .sort((a, b) => statusRank(b.st) - statusRank(a.st) || b.why.length - a.why.length
        || (a.s.platforms.instagram.pct ?? 999) - (b.s.platforms.instagram.pct ?? 999))
      .slice(0, 6),
    [stores],
  );
  const best = useMemo(
    () => stores.filter((s) => s.platforms.instagram.pct !== null)
      .sort((a, b) => b.platforms.instagram.pct! - a.platforms.instagram.pct!).slice(0, 5),
    [stores],
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 min-w-0">
      <Card title="Store health" subtitle="Each store's worst signal: views vs target, Google rating or review replies">
        <StatusBar counts={t.statusCounts} />
        <p className="text-[11px] text-[var(--text-muted)] mt-4 leading-relaxed">
          On track: views ≥ 90% of target, rating ≥ {RATING_GOOD} ★, replying to every review.
          Critical: views below 65%, rating below {RATING_WARN} ★, or not replying.
        </p>
      </Card>
      <Card title="Needs attention" subtitle="Worst first, with the reason" right={<AlertTriangle size={18} className="text-rose-400 shrink-0" />}>
        {attention.length ? (
          <ul className="space-y-2">
            {attention.map(({ s, st, why }) => (
              <li key={s.storeId} className="flex items-start gap-2 text-xs">
                <i className="mt-1 inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: STATUS_COLOR[st] }} />
                <div className="min-w-0">
                  <span className="font-semibold text-white">{s.store}</span>
                  <span className="text-[var(--text-muted)]"> · {why.slice(0, 2).join(" · ")}</span>
                </div>
              </li>
            ))}
          </ul>
        ) : <p className="text-xs text-[var(--text-muted)]">No store is at risk. 🎉</p>}
      </Card>
      <Card title="Top performers" subtitle="Highest Instagram views against target" right={<Trophy size={18} className="text-amber-400 shrink-0" />}>
        {best.length ? (
          <ol className="space-y-2">
            {best.map((s, i) => (
              <li key={s.storeId} className="flex items-center gap-3 text-xs">
                <span className="w-4 shrink-0 text-right font-bold text-[var(--text-muted)]">{i + 1}</span>
                {/* Name on its own line so narrow cards (3-up layout) don't squeeze it away */}
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-semibold text-white" title={s.store}>{s.store}</span>
                  <span className="block tabular-nums text-[11px] text-[var(--text-muted)]">{fmtCompact(s.platforms.instagram.views)} views</span>
                </span>
                <span className="shrink-0 text-right font-bold tabular-nums text-white">{Math.round(s.platforms.instagram.pct!)}%</span>
              </li>
            ))}
          </ol>
        ) : <p className="text-xs text-[var(--text-muted)]">No store reported views.</p>}
      </Card>
    </div>
  );
}

function ViewsCard({ stores, platforms }: { stores: SocialStore[]; platforms: Platform[] }) {
  const [platform, setPlatform] = useState<Platform>(platforms[0]);
  const p = platforms.includes(platform) ? platform : platforms[0];
  const rows = stores.filter((s) => s.platforms[p].pct !== null).sort((a, b) => b.platforms[p].pct! - a.platforms[p].pct!);
  const missing = stores.filter((s) => s.platforms[p].pct === null);
  return (
    <Card
      title="Views vs target by store"
      subtitle="Achieved ÷ the store's own target. Dashed line = 100%. Bars stop at 300%; the label shows the real value."
      right={platforms.length > 1 ? (
        <div className="flex gap-1 rounded-lg border border-[var(--border-subtle)] p-0.5">
          {platforms.map((x) => (
            <button key={x} onClick={() => setPlatform(x)}
              className={`rounded-md px-2 py-1 text-[11px] font-semibold ${x === p ? "bg-blue-500/20 text-blue-300" : "text-[var(--text-muted)] hover:text-white"}`}>
              {PLATFORM_LABEL[x]}
            </button>
          ))}
        </div>
      ) : undefined}
    >
      <div className="space-y-0.5">
        {rows.map((s) => {
          const pv = s.platforms[p];
          return (
            <BarRow
              key={s.storeId}
              label={s.store}
              pct={Math.max(0.6, (Math.min(pv.pct!, VIEWS_CAP) / VIEWS_CAP) * 100)}
              color={STATUS_COLOR[viewsStatus(pv.pct)]}
              refPct={(100 / VIEWS_CAP) * 100}
              value={`${Math.round(pv.pct!)}%`}
              tip={<><b className="text-white">{s.store}</b> · {fmtCompact(pv.views)} of {fmtCompact(pv.target)} {PLATFORM_LABEL[p]} views{p === "instagram" ? ` · ${s.videos} videos` : ""}</>}
            />
          );
        })}
      </div>
      {missing.length > 0 && (
        <Tip content={<span className="whitespace-normal block w-72">{missing.map((s) => s.store).join(", ")}</span>}>
          <p className="mt-3 rounded-lg border border-dashed border-[var(--border-subtle)] px-3 py-2 text-[11px] text-[var(--text-muted)]">
            <b className="text-white">{missing.length} store{missing.length === 1 ? "" : "s"}</b> haven't entered {PLATFORM_LABEL[p]} data. Hover to see which.
          </p>
        </Tip>
      )}
      <StatusLegend items={[["good", "≥ 90% on track"], ["warn", "65–89% at risk"], ["crit", "< 65% critical"]]} />
    </Card>
  );
}

function FunnelCard({ t }: { t: SocialTotals }) {
  const stages = [
    { label: "Instagram views", value: t.platforms.instagram.views, color: "#93c5fd" },
    { label: "Engagements", value: t.engagement, color: "#60a5fa" },
    { label: "Instagram DMs", value: t.dms, color: "#3b82f6" },
    { label: "Manychat handled", value: t.manychat, color: "#1d4ed8" },
  ];
  const top = Math.log10(Math.max(10, stages[0].value));
  return (
    <Card title="Social → lead funnel" subtitle={t.stores > 1 ? `Totals across ${t.socialStores} stores reporting Instagram activity` : "Instagram activity this month"}>
      <div className="space-y-1">
        {stages.map((s, i) => {
          const prev = i > 0 ? stages[i - 1].value : 0;
          const conv = i > 0 && prev ? (s.value / prev) * 100 : null;
          return (
            <div key={s.label}>
              {conv !== null && (
                <div className="pl-[124px] text-[10px] text-[var(--text-muted)]">
                  ↓ {conv < 1 ? conv.toFixed(2) : conv.toFixed(1)}% of previous step
                </div>
              )}
              <Tip content={`${s.label}: ${s.value.toLocaleString("en-IN")}`}>
                <div className="grid grid-cols-[116px_1fr_64px] items-center gap-2 text-xs">
                  <span className="text-[var(--text-secondary)]">{s.label}</span>
                  <span className="relative h-6">
                    <b className="absolute inset-y-0 left-0 rounded-r" style={{ width: `${s.value > 0 ? Math.max(4, (Math.log10(s.value) / top) * 100) : 0}%`, background: s.color }} />
                  </span>
                  <span className="text-right font-bold tabular-nums text-white">{fmtCompact(s.value)}</span>
                </div>
              </Tip>
            </div>
          );
        })}
      </div>
      <p className="text-[11px] text-[var(--text-muted)] mt-3 leading-relaxed">
        Bars use a log scale so small steps stay visible next to large view counts. Walk-ins ({fmtCompact(t.walkins)}) aren't
        part of this funnel because the sheet doesn't record how many came from Instagram.
      </p>
    </Card>
  );
}

/** Single-store view: what the store's Instagram engagement is made of. */
function EngagementBreakdown({ s }: { s: SocialStore }) {
  const parts = [
    { label: "Likes", value: s.likes },
    { label: "Comments", value: s.comments },
    { label: "Saves", value: s.saves },
    { label: "Shares", value: s.shares },
    { label: "Reposts", value: s.reposts },
  ];
  const max = Math.max(1, ...parts.map((x) => x.value));
  return (
    <Card title="Instagram engagement" subtitle={`${fmtCompact(s.engagement)} engagements · ${s.followers.toLocaleString("en-IN")} followers (+${s.newFollowers} this month)`}>
      {parts.map((x) => (
        <BarRow key={x.label} label={x.label} pct={(x.value / max) * 100} color="#3b82f6" value={fmtCompact(x.value)} tip={`${x.label}: ${x.value.toLocaleString("en-IN")}`} />
      ))}
      <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
        <div className="rounded-xl border border-[var(--border-subtle)] p-3">
          <p className="text-[var(--text-muted)]">Google rating</p>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-lg font-extrabold text-white">
            {s.rating ? `${s.rating.toFixed(1)} ★` : "—"} <StatusPill status={ratingStatus(s.rating)} />
          </p>
        </div>
        <div className="rounded-xl border border-[var(--border-subtle)] p-3">
          <p className="text-[var(--text-muted)]">Replied to reviews</p>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-lg font-extrabold text-white">
            {s.replied || "—"} <StatusPill status={repliedStatus(s.replied)} />
          </p>
        </div>
      </div>
    </Card>
  );
}

function EngagementCard({ stores }: { stores: SocialStore[] }) {
  const rows = stores.filter((s) => s.engagement > 0).sort((a, b) => b.engagement - a.engagement).slice(0, 6);
  const max = rows[0]?.engagement || 1;
  return (
    <Card title="Top stores by Instagram engagement" subtitle="Likes + comments + saves + shares + reposts">
      {rows.length ? rows.map((s) => (
        <BarRow
          key={s.storeId}
          label={s.store}
          pct={(s.engagement / max) * 100}
          color="#3b82f6"
          value={fmtCompact(s.engagement)}
          tip={<><b className="text-white">{s.store}</b> · {fmtCompact(s.likes)} likes · {fmtCompact(s.comments)} comments · {fmtCompact(s.saves)} saves · {fmtCompact(s.shares)} shares · {fmtCompact(s.reposts)} reposts</>}
        />
      )) : <p className="text-xs text-[var(--text-muted)]">No engagement reported.</p>}
    </Card>
  );
}

function RatingCard({ stores }: { stores: SocialStore[] }) {
  const rated = stores.filter((s) => s.rating !== null).sort((a, b) => a.rating! - b.rating!);
  if (!rated.length) return <Card title="Google rating by store"><p className="text-xs text-[var(--text-muted)]">No Google ratings for this selection.</p></Card>;
  const lo = Math.min(3.8, Math.floor((rated[0].rating! - 0.1) * 10) / 10);
  const hi = 5.05;
  const y = (v: number) => ((v - lo) / (hi - lo)) * 100;
  const ticks = [4.0, 4.5, 4.8, 5.0].filter((v) => v >= lo);
  return (
    <Card title="Google rating by store" subtitle={`Green band = target ≥ ${RATING_GOOD} ★ · amber ${RATING_WARN}–${RATING_GOOD} · below ${RATING_WARN} needs action. Hover a dot.`}>
      <div className="relative ml-8 mr-1 mb-1 h-64 border-l border-b border-[var(--border-subtle)]">
        <div className="absolute inset-x-0 top-0" style={{ bottom: `${y(RATING_GOOD)}%`, background: STATUS_COLOR.good, opacity: 0.1 }} />
        <div className="absolute inset-x-0" style={{ bottom: `${y(RATING_WARN)}%`, height: `${y(RATING_GOOD) - y(RATING_WARN)}%`, background: STATUS_COLOR.warn, opacity: 0.1 }} />
        {ticks.map((v) => (
          <div key={v} className="absolute inset-x-0 border-t border-[var(--border-subtle)]" style={{ bottom: `${y(v)}%` }}>
            <span className="absolute -left-8 -top-2 text-[10px] tabular-nums text-[var(--text-muted)]">{v.toFixed(1)}</span>
          </div>
        ))}
        {rated.map((s, i) => (
          <div
            key={s.storeId}
            className="absolute"
            style={{ left: `${((i + 0.5) / rated.length) * 100}%`, bottom: `${y(s.rating!)}%`, transform: "translate(-50%, 50%)" }}
          >
            <Tip content={<><b className="text-white">{s.store}</b> · {s.rating!.toFixed(1)} ★ · {s.reviews} reviews · replied: {s.replied || "—"}</>}>
              <span className="block h-3 w-3 rounded-full border-2 border-[var(--bg-card)]" style={{ background: STATUS_COLOR[ratingStatus(s.rating)] }} />
            </Tip>
          </div>
        ))}
      </div>
      <p className="text-[11px] text-[var(--text-muted)] mt-2">Stores sorted from lowest to highest rating, left to right.</p>
    </Card>
  );
}

function ReviewsCard({ stores }: { stores: SocialStore[] }) {
  const rows = stores.filter((s) => s.rating !== null).sort((a, b) => b.reviews - a.reviews);
  const max = rows[0]?.reviews || 1;
  return (
    <Card title="Review volume & replies" subtitle="Reviews recorded this month, coloured by whether the store replied to all of them">
      {rows.length ? rows.map((s) => {
        const st = repliedStatus(s.replied);
        return (
          <BarRow
            key={s.storeId}
            label={s.store}
            pct={(s.reviews / max) * 100}
            color={STATUS_COLOR[st]}
            value={<>{s.reviews} <span className="text-[var(--text-muted)]">{STATUS_ICON[st]}</span></>}
            tip={<><b className="text-white">{s.store}</b> · {s.reviews} reviews · {s.rating!.toFixed(1)} ★ · replied to all: {s.replied || "not filled"}</>}
          />
        );
      }) : <p className="text-xs text-[var(--text-muted)]">No review data.</p>}
      <StatusLegend items={[["good", "Replied to all"], ["warn", "Partial"], ["crit", "No replies"], ["none", "Not filled"]]} />
    </Card>
  );
}

const CHANNELS: { label: string; has: (s: SocialStore) => boolean }[] = [
  { label: "Instagram", has: (s) => s.hasSocial },
  { label: "YouTube", has: (s) => s.platforms.youtube.hasData },
  { label: "Facebook", has: (s) => s.platforms.facebook.hasData },
  { label: "WhatsApp", has: (s) => s.waChats > 0 },
  { label: "Walk-ins", has: (s) => s.walkins > 0 },
  { label: "Google", has: (s) => s.rating !== null },
];

function CoverageCard({ stores }: { stores: SocialStore[] }) {
  const empty = CHANNELS.filter((c) => !stores.some(c.has)).map((c) => c.label);
  return (
    <Card
      title="Channel coverage"
      subtitle={empty.length
        ? `Which channels each store fills in. ${empty.join(", ")} ${empty.length === 1 ? "has" : "have"} no data from any store yet.`
        : "Which channels each store fills in."}
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[600px] border-separate border-spacing-[2px] text-xs">
          <thead>
            <tr>
              <th className="text-left font-semibold text-[var(--text-muted)] pb-1">Store</th>
              {CHANNELS.map((c) => (
                <th key={c.label} className="font-semibold text-[var(--text-muted)] pb-1">
                  {c.label}
                  <div className="text-[10px] font-normal">{stores.filter(c.has).length}/{stores.length}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {stores.map((s) => (
              <tr key={s.storeId}>
                <td className="pr-3 whitespace-nowrap text-[var(--text-secondary)]">{s.store}</td>
                {CHANNELS.map((c) => {
                  const on = c.has(s);
                  return (
                    <td key={c.label} className="p-0">
                      <Tip content={`${s.store} · ${c.label}: ${on ? "reporting" : "no data"}`}>
                        <div className="h-4 rounded-[3px]" style={{ background: on ? "#3b82f6" : "var(--border-subtle)" }} />
                      </Tip>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

interface Column {
  key: string;
  label: string;
  sort: (s: SocialStore) => number | string | null;
  render: (s: SocialStore) => React.ReactNode;
  left?: boolean;
}

function ScorecardTable({ stores, platforms, showTl }: { stores: SocialStore[]; platforms: Platform[]; showTl: boolean }) {
  const [sortKey, setSortKey] = useState("status");
  const [dir, setDir] = useState<1 | -1>(-1);
  const [q, setQ] = useState("");

  const columns: Column[] = useMemo(() => [
    { key: "store", label: "Store", left: true, sort: (s) => s.store, render: (s) => <span className="font-medium text-white">{s.store}</span> },
    ...(showTl ? [{ key: "tl", label: "Team leader", left: true, sort: (s: SocialStore) => s.teamLeader || null, render: (s: SocialStore) => s.teamLeader || null }] : []),
    ...platforms.flatMap((p): Column[] => [
      { key: `${p}-views`, label: `${PLATFORM_LABEL[p]} views`, sort: (s) => (s.platforms[p].hasData ? s.platforms[p].views : null), render: (s) => (s.platforms[p].hasData ? fmtCompact(s.platforms[p].views) : null) },
      { key: `${p}-pct`, label: "% target", sort: (s) => s.platforms[p].pct, render: (s) => (s.platforms[p].pct === null ? null : <span title={`Target ${s.platforms[p].target.toLocaleString("en-IN")}`}>{Math.round(s.platforms[p].pct!)}%</span>) },
    ]),
    { key: "followers", label: "Followers", sort: (s) => (s.hasSocial ? s.followers : null), render: (s) => (s.hasSocial ? fmtCompact(s.followers) : null) },
    { key: "engagement", label: "Engagement", sort: (s) => (s.hasSocial ? s.engagement : null), render: (s) => (s.hasSocial ? fmtCompact(s.engagement) : null) },
    { key: "dms", label: "DMs", sort: (s) => (s.hasSocial ? s.dms : null), render: (s) => (s.hasSocial ? fmtCompact(s.dms) : null) },
    { key: "walkins", label: "Walk-ins", sort: (s) => s.walkins || null, render: (s) => (s.walkins ? fmtCompact(s.walkins) : null) },
    { key: "rating", label: "Google ★", sort: (s) => s.rating, render: (s) => (s.rating === null ? null : s.rating.toFixed(1)) },
    { key: "reviews", label: "Reviews", sort: (s) => (s.rating === null ? null : s.reviews), render: (s) => (s.rating === null ? null : s.reviews) },
    { key: "replied", label: "Replied", sort: (s) => s.replied || null, render: (s) => s.replied || null },
    {
      key: "updated", label: "Last updated", sort: (s) => s.lastUpdatedAt,
      render: (s) => (
        <span className="inline-flex items-center gap-1.5" title={fmtDateTime(s.lastUpdatedAt)}>
          <i className="inline-block h-2 w-2 rounded-full" style={{ background: STATUS_COLOR[freshnessStatus(s.lastUpdatedAt)] }} />
          {s.lastUpdatedAt ? timeAgo(s.lastUpdatedAt) : "never"}
        </span>
      ),
    },
    { key: "status", label: "Status", sort: (s) => statusRank(overallStatus(s)), render: (s) => <StatusPill status={overallStatus(s)} /> },
  ], [platforms, showTl]);

  const rows = useMemo(() => {
    const col = columns.find((c) => c.key === sortKey) || columns[columns.length - 1];
    return stores
      .filter((s) => `${s.store} ${s.teamLeader}`.toLowerCase().includes(q.trim().toLowerCase()))
      .sort((a, b) => {
        const x = col.sort(a), y = col.sort(b);
        if (x === y) return 0;
        if (x === null || x === "") return 1;
        if (y === null || y === "") return -1;
        return (x > y ? 1 : -1) * dir;
      });
  }, [stores, columns, sortKey, dir, q]);

  return (
    <Card
      title="Store scorecard"
      subtitle="Click a column to sort · each store is measured against its own target"
      right={
        <label className="flex items-center gap-2 rounded-lg border border-[var(--border-subtle)] px-2.5 py-1.5">
          <Search size={14} className="text-[var(--text-muted)]" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={showTl ? "Find a store or TL" : "Find a store"}
            className="w-36 bg-transparent text-xs text-white outline-none placeholder:text-[var(--text-muted)]"
          />
        </label>
      }
    >
      <div className="overflow-x-auto w-full">
        <table className="w-full min-w-[1000px] text-xs border-collapse">
          <thead>
            <tr className="border-b border-[var(--border-subtle)] text-[var(--text-muted)] uppercase tracking-wider text-[10px]">
              {columns.map((c) => (
                <th
                  key={c.key}
                  onClick={() => { setDir(sortKey === c.key ? (dir === 1 ? -1 : 1) : -1); setSortKey(c.key); }}
                  className={`py-2.5 px-2 font-semibold cursor-pointer select-none whitespace-nowrap hover:text-white ${c.left ? "text-left" : "text-right"}`}
                >
                  {c.label}{sortKey === c.key ? (dir === 1 ? " ▲" : " ▼") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border-subtle)]">
            {rows.map((s) => (
              <tr key={s.storeId} className="hover:bg-[var(--bg-card-hover)] transition-colors">
                {columns.map((c) => {
                  const v = c.render(s);
                  return (
                    <td key={c.key} className={`py-2 px-2 whitespace-nowrap tabular-nums ${c.left ? "text-left" : "text-right"} text-[var(--text-secondary)]`}>
                      {v === null || v === "" ? <span className="text-[var(--text-muted)]">—</span> : v}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
