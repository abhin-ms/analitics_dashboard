import { useMemo } from "react";
import { BrandIcon, type Brand } from "@/components/shared/BrandIcon";
import { Link } from "react-router-dom";
import { ArrowRight, Clock, Share2 } from "lucide-react";
import {
  useSocialPerformance, totalsOf, overallStatus, attentionReasons, viewsStatus, freshnessStatus,
  fmtCompact, fmtDateTime, monthLabel, timeAgo, STATUS_COLOR, RATING_GOOD, PLATFORM_LABEL, PLATFORM_COLOR, Platform,
} from "@/features/social/socialData";
import { StatusBar, Tip } from "@/features/social/ui";

/** Dashboard block: the month's social + Google reputation in one card,
 * linking to the full Social Performance page. Scoped by the server to the
 * viewer — every store for admins, a team leader's own stores (with their
 * targets summed), or a store account's store. Always shows the latest month
 * the tracker sheet has data for, independent of the dashboard's date filter. */
export default function SocialSnapshotCard() {
  const { scope, month, stores, isLoading, empty } = useSocialPerformance();
  const t = useMemo(() => totalsOf(stores), [stores]);
  const platforms: Platform[] = t.activePlatforms.length ? t.activePlatforms : ["instagram"];

  const attention = useMemo(
    () => stores
      .map((s) => ({ s, st: overallStatus(s), why: attentionReasons(s) }))
      .filter((x) => x.st === "crit")
      .sort((a, b) => b.why.length - a.why.length || (a.s.platforms.instagram.pct ?? 999) - (b.s.platforms.instagram.pct ?? 999))
      .slice(0, 3),
    [stores],
  );
  const best = useMemo(
    () => stores.filter((s) => s.platforms.instagram.pct !== null)
      .sort((a, b) => b.platforms.instagram.pct! - a.platforms.instagram.pct!).slice(0, 3),
    [stores],
  );

  if (isLoading) return <div className="h-72 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] animate-pulse" />;
  if (empty || !stores.length) return null;

  const single = stores.length === 1 ? stores[0] : null;
  const stats: { label: string; value: string; sub: string; meter?: number; color: string; brand?: Brand }[] = [
    ...platforms.map((p) => ({
      brand: p as Brand,
      label: `${PLATFORM_LABEL[p]} views`,
      value: fmtCompact(t.platforms[p].views),
      sub: `${Math.round(t.platforms[p].pct)}% of ${fmtCompact(t.platforms[p].target)} target`,
      meter: t.platforms[p].pct / 100,
      color: PLATFORM_COLOR[p],
    })),
    { label: "New followers", value: `+${fmtCompact(t.newFollowers)}`, sub: `${t.videos} videos posted`, color: "#a855f7" },
    { label: "Instagram DMs", value: fmtCompact(t.dms), sub: `${fmtCompact(t.walkins)} walk-ins booked`, color: "#06b6d4", brand: "instagram" as Brand },
    single
      ? { label: "Google rating", value: single.rating ? `${single.rating.toFixed(1)} ★` : "—", sub: `${single.reviews} reviews · replied: ${single.replied || "—"}`, color: "#f59e0b" }
      : { label: "Google rating", value: t.avgRating ? `${t.avgRating.toFixed(2)} ★` : "—", sub: `${t.ratingGood} of ${t.ratedStores} stores ≥ ${RATING_GOOD}`, color: "#f59e0b" },
    ...(single ? [] : [{ label: "Reviews replied", value: `${t.repliedAll}/${t.ratedStores}`, sub: `${fmtCompact(t.reviews)} reviews`, meter: t.ratedStores ? t.repliedAll / t.ratedStores : 0, color: "#f97316" }]),
  ];
  const stale = t.freshCounts.crit + t.freshCounts.none;

  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
        <div className="flex items-center gap-2">
          <div className="p-2 rounded-lg bg-pink-500/10 text-[#E1306C]"><Share2 size={18} /></div>
          <div>
            <h3 className="text-base font-bold text-white tracking-tight">Social &amp; Reputation</h3>
            <p className="text-xs text-[var(--text-muted)]">
              {month ? monthLabel(month) : ""} · {scope?.kind === "company" ? `${t.stores} stores` : scope?.label} · social media, WhatsApp &amp; Google reviews
            </p>
          </div>
        </div>
        <Link
          to="/social-performance"
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border-subtle)] px-3 py-1.5 text-xs font-semibold text-blue-300 hover:bg-[var(--bg-card-hover)]"
        >
          Full report <ArrowRight size={14} />
        </Link>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-4 mb-6">
        {stats.map((s) => (
          <div key={s.label} className="min-w-0 border-l-2 pl-3" style={{ borderColor: s.color }}>
            <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] flex items-center gap-1.5">
              {s.brand ? <BrandIcon brand={s.brand} size={12} /> : s.label.startsWith("Google") ? <BrandIcon brand="google" size={12} /> : null}
              {s.label}
            </p>
            <p className="text-xl font-extrabold text-white leading-tight mt-0.5">{s.value}</p>
            <p className="text-[11px] text-[var(--text-muted)]">{s.sub}</p>
            {s.meter !== undefined && (
              <div className="mt-1.5 h-1 rounded-full bg-[var(--border-subtle)] overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${Math.min(100, s.meter * 100)}%`, background: STATUS_COLOR[viewsStatus(s.meter * 100)] }} />
              </div>
            )}
          </div>
        ))}
      </div>

      {single ? (
        <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--text-muted)]">
          <Clock size={14} />
          Last updated in sheet: <b className="text-white">{fmtDateTime(single.lastUpdatedAt)}</b>
          {single.lastUpdatedAt && <span>({timeAgo(single.lastUpdatedAt)})</span>}
          <i className="inline-block h-2 w-2 rounded-full" style={{ background: STATUS_COLOR[freshnessStatus(single.lastUpdatedAt)] }} />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div>
            <p className="text-xs font-semibold text-white mb-2">Store health</p>
            <StatusBar counts={t.statusCounts} />
            <p className="mt-3 flex items-center gap-1.5 text-[11px] text-[var(--text-muted)]">
              <Clock size={12} />
              {t.freshCounts.good} of {t.stores} stores updated the sheet in the last day
              {stale > 0 && <span className="text-rose-300">· {stale} stale or never</span>}
            </p>
          </div>
          <div>
            <p className="text-xs font-semibold text-white mb-2">Top Instagram views vs target</p>
            <ul className="space-y-1.5">
              {best.map((s) => {
                const pv = s.platforms.instagram;
                return (
                  <li key={s.storeId}>
                    <Tip content={`${s.store}: ${fmtCompact(pv.views)} of ${fmtCompact(pv.target)} views · ${s.videos} videos`}>
                      <div className="flex items-center justify-between text-xs">
                        <span className="min-w-0 truncate text-[var(--text-secondary)]" title={s.store}>{s.store}</span>
                        <span className="font-bold tabular-nums text-white">{Math.round(pv.pct!)}%</span>
                      </div>
                      <div className="mt-1 h-1.5 rounded-full bg-[var(--border-subtle)] overflow-hidden">
                        <div className="h-full rounded-full" style={{ width: `${Math.min(100, (pv.pct! / Math.max(100, best[0].platforms.instagram.pct!)) * 100)}%`, background: STATUS_COLOR[viewsStatus(pv.pct)] }} />
                      </div>
                    </Tip>
                  </li>
                );
              })}
              {!best.length && <li className="text-xs text-[var(--text-muted)]">No views reported yet.</li>}
            </ul>
          </div>
          <div>
            <p className="text-xs font-semibold text-white mb-2">Needs attention</p>
            {attention.length ? (
              <ul className="space-y-2">
                {attention.map(({ s, st, why }) => (
                  <li key={s.storeId} className="flex items-start gap-2 text-xs">
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
      )}
    </div>
  );
}
