import { useMemo } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Share2 } from "lucide-react";
import {
  useSocialPerformance, totalsOf, overallStatus, attentionReasons,
  fmtCompact, monthLabel, STATUS_COLOR, RATING_GOOD,
} from "@/features/social/socialData";
import { StatusBar, Tip } from "@/features/social/ui";

/** Dashboard overview block: the month's social + Google reputation in one
 * card, linking to the full Social Performance page. Always shows the latest
 * month the tracker sheet has data for, independent of the dashboard's date
 * filter (the sheet is filled monthly, so a "this week" range is usually empty). */
export default function SocialSnapshotCard() {
  const { month, stores, isLoading, empty } = useSocialPerformance();
  const t = useMemo(() => totalsOf(stores), [stores]);

  const attention = useMemo(
    () => stores
      .map((s) => ({ s, st: overallStatus(s), why: attentionReasons(s) }))
      .filter((x) => x.st === "crit")
      .sort((a, b) => b.why.length - a.why.length || (a.s.viewsPct ?? 999) - (b.s.viewsPct ?? 999))
      .slice(0, 3),
    [stores],
  );
  const best = useMemo(
    () => stores.filter((s) => s.viewsPct !== null).sort((a, b) => b.viewsPct! - a.viewsPct!).slice(0, 3),
    [stores],
  );

  if (isLoading) return <div className="h-72 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] animate-pulse" />;
  if (empty || !stores.length) return null;

  const viewsPct = t.viewsTarget ? (t.views / t.viewsTarget) * 100 : 0;
  const stats = [
    { label: "Video views", value: fmtCompact(t.views), sub: `${Math.round(viewsPct)}% of target`, meter: viewsPct / 100, color: "#3b82f6" },
    { label: "New followers", value: `+${fmtCompact(t.newFollowers)}`, sub: `${t.videos} videos posted`, color: "#a855f7" },
    { label: "Instagram DMs", value: fmtCompact(t.dms), sub: `${fmtCompact(t.walkins)} walk-ins booked`, color: "#06b6d4" },
    { label: "Google rating", value: t.avgRating ? `${t.avgRating.toFixed(2)} ★` : "—", sub: `${t.ratingGood} of ${t.ratedStores} stores ≥ ${RATING_GOOD}`, color: "#f59e0b" },
    { label: "Reviews replied", value: `${t.repliedAll}/${t.ratedStores}`, sub: `${fmtCompact(t.reviews)} reviews`, meter: t.ratedStores ? t.repliedAll / t.ratedStores : 0, color: "#f97316" },
  ];

  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
        <div className="flex items-center gap-2">
          <div className="p-2 rounded-lg bg-pink-500/10 text-[#E1306C]"><Share2 size={18} /></div>
          <div>
            <h3 className="text-base font-bold text-white tracking-tight">Social &amp; Reputation</h3>
            <p className="text-xs text-[var(--text-muted)]">{month ? monthLabel(month) : ""} · {t.stores} stores · Instagram, WhatsApp &amp; Google reviews</p>
          </div>
        </div>
        <Link
          to="/social-performance"
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border-subtle)] px-3 py-1.5 text-xs font-semibold text-blue-300 hover:bg-[var(--bg-card-hover)]"
        >
          Full report <ArrowRight size={14} />
        </Link>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 mb-6">
        {stats.map((s) => (
          <div key={s.label} className="min-w-0 border-l-2 pl-3" style={{ borderColor: s.color }}>
            <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">{s.label}</p>
            <p className="text-xl font-extrabold text-white leading-tight mt-0.5">{s.value}</p>
            <p className="text-[11px] text-[var(--text-muted)]">{s.sub}</p>
            {s.meter !== undefined && (
              <div className="mt-1.5 h-1 rounded-full bg-[var(--border-subtle)] overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${Math.min(100, s.meter * 100)}%`, background: s.color }} />
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div>
          <p className="text-xs font-semibold text-white mb-2">Store health</p>
          <StatusBar counts={t.statusCounts} />
        </div>
        <div>
          <p className="text-xs font-semibold text-white mb-2">Top video views vs target</p>
          <ul className="space-y-1.5">
            {best.map((s) => (
              <li key={s.store}>
                <Tip content={`${s.store}: ${fmtCompact(s.views)} views · ${s.videos} videos`}>
                  <div className="flex items-center justify-between text-xs">
                    <span className="truncate text-[var(--text-secondary)]">{s.store}</span>
                    <span className="font-bold tabular-nums text-white">{Math.round(s.viewsPct!)}%</span>
                  </div>
                  <div className="mt-1 h-1.5 rounded-full bg-[var(--border-subtle)] overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${Math.min(100, (s.viewsPct! / Math.max(100, best[0].viewsPct!)) * 100)}%`, background: STATUS_COLOR.good }} />
                  </div>
                </Tip>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <p className="text-xs font-semibold text-white mb-2">Needs attention</p>
          {attention.length ? (
            <ul className="space-y-2">
              {attention.map(({ s, st, why }) => (
                <li key={s.store} className="flex items-start gap-2 text-xs">
                  <i className="mt-1 inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: STATUS_COLOR[st] }} />
                  <span className="min-w-0">
                    <span className="font-semibold text-white">{s.store}</span>
                    <span className="text-[var(--text-muted)]"> · {why[0]}</span>
                  </span>
                </li>
              ))}
              {t.statusCounts.crit > attention.length && (
                <li className="text-[11px] text-[var(--text-muted)]">
                  +{t.statusCounts.crit - attention.length} more critical · <Link to="/social-performance" className="text-blue-300 hover:underline">see all</Link>
                </li>
              )}
            </ul>
          ) : <p className="text-xs text-[var(--text-muted)]">No critical stores.</p>}
        </div>
      </div>
    </div>
  );
}

