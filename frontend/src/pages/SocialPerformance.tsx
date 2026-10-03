import { useMemo, useState } from "react";
import { Eye, Video, UserPlus, MessageCircle, Footprints, Star, MessageSquareReply, Search, AlertTriangle, Trophy } from "lucide-react";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { EmptyState } from "@/components/shared/EmptyState";
import { useSocketRefresh } from "@/hooks/useSocketRefresh";
import {
  useSocialPerformance, totalsOf, overallStatus, statusRank, attentionReasons,
  viewsStatus, ratingStatus, repliedStatus, fmtCompact, monthLabel,
  COUNTRY_LABEL, STATUS_COLOR, STATUS_ICON, RATING_GOOD, RATING_WARN, SocialStore,
} from "@/features/social/socialData";
import { Card, Tip, StatusPill, StatusLegend, BarRow, StatusBar } from "@/features/social/ui";

const VIEWS_CAP = 300; // bars stop at 300% of target; the label shows the real value

export default function SocialPerformance() {
  useSocketRefresh(["sheets-data"]);
  const [month, setMonth] = useState<string | undefined>();
  const [country, setCountry] = useState("ALL");
  const { months, month: active, stores: allStores, isLoading, error, empty } = useSocialPerformance(month);

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
            <h2 className="text-lg font-bold text-white">Social Performance</h2>
            <p className="text-xs text-[var(--text-muted)]">
              Reach, engagement, leads and Google reviews per store · from the BP Store Daily Tracker sheet
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
          </div>
        </div>

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
            <EmptyState title="No social data yet" description="Nothing has been synced from the Daily Input tab of the tracker sheet for this selection." />
          </div>
        ) : (
          <Content stores={stores} t={t} />
        )}
      </div>
    </ErrorBoundary>
  );
}

function Content({ stores, t }: { stores: SocialStore[]; t: ReturnType<typeof totalsOf> }) {
  const viewsPctAll = t.viewsTarget ? (t.views / t.viewsTarget) * 100 : 0;
  const kpis = [
    { label: "Video views", value: fmtCompact(t.views), sub: `${Math.round(viewsPctAll)}% of ${fmtCompact(t.viewsTarget)} target`, meter: viewsPctAll / 100, icon: <Eye size={18} />, color: "#3b82f6" },
    { label: "Videos posted", value: String(t.videos), sub: `${t.storesPosted} of ${t.stores} stores posted`, icon: <Video size={18} />, color: "#E1306C" },
    { label: "New followers", value: `+${fmtCompact(t.newFollowers)}`, sub: `${fmtCompact(t.followers)} total on Instagram`, icon: <UserPlus size={18} />, color: "#a855f7" },
    { label: "Instagram DMs", value: fmtCompact(t.dms), sub: `${fmtCompact(t.manychat)} handled by Manychat`, icon: <MessageCircle size={18} />, color: "#06b6d4" },
    { label: "Walk-ins booked", value: fmtCompact(t.walkins), sub: "all sources (WhatsApp, phone, in-store)", icon: <Footprints size={18} />, color: "#10b981" },
    { label: "Avg Google rating", value: t.avgRating ? `${t.avgRating.toFixed(2)} ★` : "—", sub: `${t.ratingGood} stores ≥ ${RATING_GOOD} · ${t.ratingCrit} below ${RATING_WARN}`, icon: <Star size={18} />, color: "#f59e0b" },
    { label: "Reviews replied", value: `${t.repliedAll}/${t.ratedStores}`, sub: `stores replied to all · ${fmtCompact(t.reviews)} reviews`, meter: t.ratedStores ? t.repliedAll / t.ratedStores : undefined, icon: <MessageSquareReply size={18} />, color: "#f97316" },
  ];

  return (
    <>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 gap-3 min-w-0">
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

      <HealthRow stores={stores} t={t} />

      <div className="grid grid-cols-1 xl:grid-cols-[1.3fr_1fr] gap-6 min-w-0">
        <ViewsCard stores={stores} />
        <div className="space-y-6 min-w-0">
          <FunnelCard t={t} />
          <EngagementCard stores={stores} />
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6 min-w-0">
        <RatingCard stores={stores} />
        <ReviewsCard stores={stores} />
      </div>

      <CoverageCard stores={stores} />
      <ScorecardTable stores={stores} />
    </>
  );
}

function HealthRow({ stores, t }: { stores: SocialStore[]; t: ReturnType<typeof totalsOf> }) {
  const attention = useMemo(
    () => stores
      .map((s) => ({ s, st: overallStatus(s), why: attentionReasons(s) }))
      .filter((x) => x.st === "crit" || x.st === "warn")
      .sort((a, b) => statusRank(b.st) - statusRank(a.st) || b.why.length - a.why.length || (a.s.viewsPct ?? 999) - (b.s.viewsPct ?? 999))
      .slice(0, 6),
    [stores],
  );
  const best = useMemo(
    () => stores.filter((s) => s.viewsPct !== null).sort((a, b) => b.viewsPct! - a.viewsPct!).slice(0, 5),
    [stores],
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 min-w-0">
      <Card title="Store health" subtitle="Each store's worst signal: video views, Google rating or review replies">
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
              <li key={s.store} className="flex items-start gap-2 text-xs">
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
      <Card title="Top performers" subtitle="Highest video views against target" right={<Trophy size={18} className="text-amber-400 shrink-0" />}>
        {best.length ? (
          <ol className="space-y-2">
            {best.map((s, i) => (
              <li key={s.store} className="flex items-center gap-3 text-xs">
                <span className="w-4 text-right font-bold text-[var(--text-muted)]">{i + 1}</span>
                <span className="flex-1 truncate font-semibold text-white">{s.store}</span>
                <span className="tabular-nums text-[var(--text-secondary)]">{fmtCompact(s.views)} views</span>
                <span className="w-12 text-right font-bold tabular-nums text-white">{Math.round(s.viewsPct!)}%</span>
              </li>
            ))}
          </ol>
        ) : <p className="text-xs text-[var(--text-muted)]">No store reported video views.</p>}
      </Card>
    </div>
  );
}

function ViewsCard({ stores }: { stores: SocialStore[] }) {
  const rows = stores.filter((s) => s.viewsPct !== null).sort((a, b) => b.viewsPct! - a.viewsPct!);
  const missing = stores.filter((s) => s.viewsPct === null);
  return (
    <Card title="Influencer video views vs target" subtitle="Achieved ÷ target per store. Dashed line = 100%. Bars stop at 300%; the label shows the real value.">
      <div className="space-y-0.5">
        {rows.map((s) => (
          <BarRow
            key={s.store}
            label={s.store}
            pct={Math.max(0.6, (Math.min(s.viewsPct!, VIEWS_CAP) / VIEWS_CAP) * 100)}
            color={STATUS_COLOR[viewsStatus(s.viewsPct)]}
            refPct={(100 / VIEWS_CAP) * 100}
            value={`${Math.round(s.viewsPct!)}%`}
            tip={<><b className="text-white">{s.store}</b> · {fmtCompact(s.views)} of {fmtCompact(s.viewsTarget)} views · {s.videos} videos</>}
          />
        ))}
      </div>
      {missing.length > 0 && (
        <Tip content={<span className="whitespace-normal block w-72">{missing.map((s) => s.store).join(", ")}</span>}>
          <p className="mt-3 rounded-lg border border-dashed border-[var(--border-subtle)] px-3 py-2 text-[11px] text-[var(--text-muted)]">
            <b className="text-white">{missing.length} stores</b> haven't entered any video or Instagram data. Hover to see which.
          </p>
        </Tip>
      )}
      <StatusLegend items={[["good", "≥ 90% on track"], ["warn", "65–89% at risk"], ["crit", "< 65% critical"]]} />
    </Card>
  );
}

function FunnelCard({ t }: { t: ReturnType<typeof totalsOf> }) {
  const stages = [
    { label: "Video views", value: t.views, color: "#93c5fd" },
    { label: "Engagements", value: t.engagement, color: "#60a5fa" },
    { label: "Instagram DMs", value: t.dms, color: "#3b82f6" },
    { label: "Manychat handled", value: t.manychat, color: "#1d4ed8" },
  ];
  const top = Math.log10(Math.max(10, stages[0].value));
  return (
    <Card title="Social → lead funnel" subtitle={`Totals across ${t.socialStores} stores reporting Instagram activity`}>
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
        Bars use a log scale so small steps stay visible next to crores of views. Walk-ins ({fmtCompact(t.walkins)}) aren't
        part of this funnel because the sheet doesn't record how many came from Instagram.
      </p>
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
          key={s.store}
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
            key={s.store}
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
            key={s.store}
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
  { label: "YouTube", has: (s) => s.ytViews > 0 },
  { label: "TikTok", has: (s) => s.ttViews > 0 },
  { label: "Snapchat", has: (s) => s.scViews > 0 },
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
        <table className="w-full min-w-[640px] border-separate border-spacing-[2px] text-xs">
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
              <tr key={s.store}>
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

type SortKey = keyof SocialStore | "status";
const COLUMNS: { key: SortKey; label: string; render: (s: SocialStore) => React.ReactNode }[] = [
  { key: "store", label: "Store", render: (s) => <span className="font-medium text-white">{s.store}</span> },
  { key: "country", label: "Country", render: (s) => COUNTRY_LABEL[s.country] || s.country },
  { key: "videos", label: "Videos", render: (s) => (s.hasSocial ? s.videos : null) },
  { key: "views", label: "Views", render: (s) => (s.hasSocial ? fmtCompact(s.views) : null) },
  { key: "viewsPct", label: "Views %", render: (s) => (s.viewsPct === null ? null : `${Math.round(s.viewsPct)}%`) },
  { key: "followers", label: "Followers", render: (s) => (s.hasSocial ? fmtCompact(s.followers) : null) },
  { key: "newFollowers", label: "New foll.", render: (s) => (s.hasSocial ? `+${fmtCompact(s.newFollowers)}` : null) },
  { key: "engagement", label: "Engagement", render: (s) => (s.hasSocial ? fmtCompact(s.engagement) : null) },
  { key: "dms", label: "DMs", render: (s) => (s.hasSocial ? fmtCompact(s.dms) : null) },
  { key: "walkins", label: "Walk-ins", render: (s) => (s.walkins ? fmtCompact(s.walkins) : null) },
  { key: "rating", label: "Google ★", render: (s) => (s.rating === null ? null : s.rating.toFixed(1)) },
  { key: "reviews", label: "Reviews", render: (s) => (s.rating === null ? null : s.reviews) },
  { key: "replied", label: "Replied", render: (s) => s.replied || null },
  { key: "status", label: "Status", render: (s) => <StatusPill status={overallStatus(s)} /> },
];

function ScorecardTable({ stores }: { stores: SocialStore[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("status");
  const [dir, setDir] = useState<1 | -1>(-1);
  const [q, setQ] = useState("");

  const rows = useMemo(() => {
    const val = (s: SocialStore) => (sortKey === "status" ? statusRank(overallStatus(s)) : s[sortKey]);
    return stores
      .filter((s) => s.store.toLowerCase().includes(q.trim().toLowerCase()))
      .sort((a, b) => {
        const x = val(a), y = val(b);
        if (x === y) return 0;
        if (x === null || x === "") return 1;
        if (y === null || y === "") return -1;
        return (x > y ? 1 : -1) * dir;
      });
  }, [stores, sortKey, dir, q]);

  return (
    <Card
      title="Store scorecard"
      subtitle="Click a column to sort"
      right={
        <label className="flex items-center gap-2 rounded-lg border border-[var(--border-subtle)] px-2.5 py-1.5">
          <Search size={14} className="text-[var(--text-muted)]" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Find a store"
            className="w-36 bg-transparent text-xs text-white outline-none placeholder:text-[var(--text-muted)]"
          />
        </label>
      }
    >
      <div className="overflow-x-auto w-full">
        <table className="w-full min-w-[1000px] text-xs border-collapse">
          <thead>
            <tr className="border-b border-[var(--border-subtle)] text-[var(--text-muted)] uppercase tracking-wider text-[10px]">
              {COLUMNS.map((c, i) => (
                <th
                  key={c.key}
                  onClick={() => { setDir(sortKey === c.key ? (dir === 1 ? -1 : 1) : -1); setSortKey(c.key); }}
                  className={`py-2.5 px-2 font-semibold cursor-pointer select-none whitespace-nowrap hover:text-white ${i < 2 ? "text-left" : "text-right"}`}
                >
                  {c.label}{sortKey === c.key ? (dir === 1 ? " ▲" : " ▼") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border-subtle)]">
            {rows.map((s) => (
              <tr key={s.store} className="hover:bg-[var(--bg-card-hover)] transition-colors">
                {COLUMNS.map((c, i) => {
                  const v = c.render(s);
                  return (
                    <td key={c.key} className={`py-2 px-2 whitespace-nowrap tabular-nums ${i < 2 ? "text-left" : "text-right"} text-[var(--text-secondary)]`}>
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
