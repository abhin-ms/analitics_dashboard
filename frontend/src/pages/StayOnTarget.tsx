import { Fragment, useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, Eye, Flame, Gauge, Lightbulb, Star, Target, UserCheck, Users } from "lucide-react";
import { STATUS_COLOR, Status } from "@/features/social/socialData";

// ── API shape (store-portfolio → funnel) ───────────────────────────
type PaceStatus = "achieved" | "ahead" | "on_track" | "behind" | "at_risk" | "no_target" | "no_data";
interface StagePace {
  target: number; achieved: number; pct: number | null; remaining: number; expected_to_date: number;
  days_remaining: number; required_daily: number | null; current_daily: number; status: PaceStatus;
}
type StageKey = "visibility" | "leads" | "hot" | "customers";
export interface FunnelStage {
  key: StageKey; title: string; unit: string; value: number | null; not_recorded: boolean;
  target_monthly: number | null; stretch_monthly: number | null; proposed: boolean;
  pace: StagePace | null; stretch_pace: StagePace | null; ratio: number | null; status: PaceStatus;
  quality: "good" | "warn" | "bad"; source: string;
  followers?: { total: number; new: number };
  breakdown?: { total: number; website: number; marked: number };
}
interface SlipRow {
  key: StageKey; title: string; status: PaceStatus; next_step: string;
  kind: "not_measured" | "reached" | "short" | "pace";
  note?: string; achieved?: number; target?: number; short?: number; pct?: number | null;
  behind?: number; need_more?: number; need_more_stretch?: number | null;
  per_day_needed?: number | null; per_day_stretch?: number | null; per_day_now?: number;
}
export interface Funnel {
  closed: boolean;
  stages: FunnelStage[];
  ratios: { label: string; pct: number | null }[];
  slipping: SlipRow[];
  bottleneck: { key: StageKey; title: string; pct: number | null }[];
  not_measured: string[];
  run_rate: Record<StageKey | "revenue", number | null> | null;
  actions: { who: string; text: string }[];
}
interface Reviews { rating: number | null; rating_as_of: string | null; rating_previous: number | null; new_reviews: number; total_reviews: number | null; negative: number | null; unanswered: number | null; response: string }

const RATING_TARGET = 4.8;
const num = (n: number | null | undefined) => (n === null || n === undefined ? "—" : Math.round(n).toLocaleString("en-IN"));
const compact = (n: number | null | undefined) => {
  if (n === null || n === undefined) return "—";
  const a = Math.abs(n);
  return a >= 1e7 ? `${(n / 1e7).toFixed(1)}Cr` : a >= 1e5 ? `${(n / 1e5).toFixed(1)}L` : a >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : num(n);
};
const fmtFor = (key: StageKey) => (key === "visibility" ? compact : num);
const perDay = (key: StageKey, n: number | null | undefined) => (n === null || n === undefined ? "—" : key === "visibility" ? compact(n) : n < 10 ? n.toFixed(1) : num(n));

const TONE: Record<PaceStatus, Status> = { achieved: "good", ahead: "good", on_track: "good", behind: "warn", at_risk: "crit", no_target: "none", no_data: "none" };
const STAGE_ICON: Record<StageKey, typeof Eye> = { visibility: Eye, leads: Users, hot: Flame, customers: UserCheck };
const STAGE_COLOR: Record<StageKey, string> = { visibility: "#2f6fed", leads: "#7c3aed", hot: "#f97316", customers: "#e5484d" };
const QUALITY_COLOR = { good: STATUS_COLOR.good, warn: STATUS_COLOR.warn, bad: STATUS_COLOR.crit };

/** "Close **3.2 sales a day** …" → the starred part in bold, nothing else interpreted. */
function Rich({ text }: { text: string }) {
  return <>{text.split("**").map((part, i) => (i % 2 ? <b key={i} className="font-semibold text-white">{part}</b> : <Fragment key={i}>{part}</Fragment>))}</>;
}

function pill(stage: FunnelStage, closed: boolean): { label: string; tone: Status } {
  if (stage.not_recorded) return { label: "No source recorded", tone: "crit" };
  const p = stage.pace;
  if (!p) return { label: "Not measured", tone: "none" };
  if (p.achieved >= p.target) return { label: "Target reached", tone: "good" };
  if (closed) return { label: `${Math.round(p.pct ?? 0)}% of target`, tone: (p.pct ?? 0) >= 90 ? "good" : (p.pct ?? 0) >= 75 ? "warn" : "crit" };
  const label = { ahead: "Ahead of pace", on_track: "On pace", behind: "Slightly behind", at_risk: "Below pace" }[p.status as string] ?? "On pace";
  return { label: `${label} · ${Math.round(p.pct ?? 0)}%`, tone: TONE[p.status] };
}

function StageCard({ stage, closed, metric }: { stage: FunnelStage; closed: boolean; metric: "views" | "followers" }) {
  const Icon = STAGE_ICON[stage.key];
  const fmt = fmtFor(stage.key);
  const showFollowers = stage.key === "visibility" && metric === "followers";
  const p = stage.pace;
  const { label, tone } = showFollowers ? { label: "No follower target set", tone: "none" as Status } : pill(stage, closed);
  const fill = showFollowers || !p ? 0 : Math.min(100, (p.achieved / Math.max(p.target, 1)) * 100);
  const range = stage.stretch_monthly ? `${num(stage.target_monthly)}–${num(stage.stretch_monthly)}` : num(stage.target_monthly);
  return (
    <div className="relative min-w-0 rounded-xl border border-[var(--border-subtle)] p-3.5 space-y-2"
      style={{ background: `color-mix(in srgb, ${STATUS_COLOR[tone]} 7%, var(--bg-card))` }}>
      <div className="flex items-center gap-2 text-[13px] font-semibold text-white">
        <span className="h-8 w-8 rounded-lg flex items-center justify-center" style={{ background: `${STAGE_COLOR[stage.key]}1a` }}>
          <Icon size={17} style={{ color: STAGE_COLOR[stage.key] }} />
        </span>
        {stage.title}
      </div>
      <p className="text-2xl font-extrabold text-white tabular-nums leading-tight">
        {showFollowers ? num(stage.followers?.total ?? 0) : stage.not_recorded ? "Not recorded" : stage.value === null ? "—" : fmt(stage.value)}
        {!stage.not_recorded && <span className="ml-1 text-xs font-semibold text-[var(--text-secondary)]">{showFollowers ? "followers" : stage.unit}</span>}
      </p>
      <p className="text-[11px] text-[var(--text-secondary)] tabular-nums">
        {showFollowers ? `${num(stage.followers?.new ?? 0)} new this period`
          : stage.target_monthly ? `Target ${stage.key === "visibility" ? compact(stage.target_monthly) : range} / month${stage.proposed ? " · proposed" : ""}` : "No target"}
      </p>
      <div className="h-2 rounded-full bg-[var(--border-subtle)] overflow-hidden" role="img" aria-label={`${Math.round(fill)}% of target`}>
        <div className="h-full rounded-full" style={{ width: `${fill}%`, background: STATUS_COLOR[tone] }} />
      </div>
      <span className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] font-semibold text-[var(--text-primary)]"
        style={{ background: `color-mix(in srgb, ${STATUS_COLOR[tone]} 16%, transparent)` }}>
        {tone === "good" ? <CheckCircle2 size={12} /> : tone !== "none" ? <AlertTriangle size={12} /> : null}
        {label}
      </span>
      {!showFollowers && (
        <p className="flex items-start gap-1.5 text-[10.5px] leading-snug text-[var(--text-muted)]">
          <i className="mt-1 inline-block h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: QUALITY_COLOR[stage.quality] }} />
          {stage.source}
        </p>
      )}
    </div>
  );
}

function SlipCell({ row, stage }: { row: SlipRow; stage: FunnelStage }) {
  const fmt = fmtFor(row.key);
  if (row.kind === "not_measured") return <><p className="font-semibold text-[var(--text-secondary)]">Not measured</p><p className="text-[var(--text-muted)]">{row.note}</p></>;
  if (row.kind === "reached") return <><p className="font-semibold" style={{ color: STATUS_COLOR.good }}>Target reached</p><p className="text-[var(--text-muted)] tabular-nums">{fmt(row.achieved)} of {fmt(row.target)}</p></>;
  if (row.kind === "short") return <><p className="font-semibold" style={{ color: STATUS_COLOR.crit }}>{fmt(row.short)} {stage.unit} short</p><p className="text-[var(--text-muted)]">{Math.round(row.pct ?? 0)}% of target</p></>;
  const behind = row.behind ?? 0;
  const need = row.need_more_stretch ? `${fmt(row.need_more)}–${fmt(row.need_more_stretch)}` : fmt(row.need_more);
  const needDay = row.per_day_stretch ? `${perDay(row.key, row.per_day_needed)}–${perDay(row.key, row.per_day_stretch)}` : perDay(row.key, row.per_day_needed);
  return (
    <>
      <p className="font-semibold" style={{ color: behind > 0 ? STATUS_COLOR.crit : STATUS_COLOR.good }}>
        {behind > 0 ? `${fmt(behind)} ${stage.unit} behind pace` : `${fmt(-behind)} ahead of pace`}
      </p>
      <p className="text-[var(--text-muted)] tabular-nums">{need} more needed · {needDay}/day vs {perDay(row.key, row.per_day_now)}/day now</p>
    </>
  );
}

function Reputation({ reviews }: { reviews: Reviews }) {
  const r = reviews.rating;
  if (r === null) {
    return <p className="text-xs text-[var(--text-secondary)]">No Google rating reported yet. Fill the Google rating column in the Daily Tracker sheet.</p>;
  }
  const tone: Status = r >= RATING_TARGET ? "good" : r >= 4.5 ? "warn" : "crit";
  const label = { good: "On target", warn: "Needs improvement", crit: "Poor", none: "" }[tone];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-3">
        <span className="text-4xl font-extrabold tabular-nums" style={{ color: STATUS_COLOR[tone] }}>{r.toFixed(1)}<Star size={22} className="inline ml-1 -mt-1.5" fill="currentColor" /></span>
        <span className="text-xs text-[var(--text-secondary)]">Target <b className="text-white">{RATING_TARGET}★</b>
          {reviews.rating_previous !== null && reviews.rating_previous !== r && ` · was ${reviews.rating_previous.toFixed(1)}`}</span>
        <span className="ml-auto rounded-lg px-2 py-1 text-[11px] font-semibold text-[var(--text-primary)]"
          style={{ background: `color-mix(in srgb, ${STATUS_COLOR[tone]} 16%, transparent)` }}>{label}</span>
      </div>
      <div className="flex flex-wrap gap-3 text-[11px] text-[var(--text-secondary)]">
        {([["good", "4.8+ good"], ["warn", "4.5–4.7 needs work"], ["crit", "below 4.5 poor"]] as const).map(([t, l]) => (
          <span key={t} className="flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ background: STATUS_COLOR[t] }} />{l}</span>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        {/* Not in any sheet yet: the cards are ready for when the counts arrive. */}
        {([["Negative this month", reviews.negative], ["Unanswered", reviews.unanswered]] as const).map(([l, v]) => (
          <div key={l} className="rounded-lg border border-[var(--border-subtle)] p-2.5">
            <p className="text-[var(--text-muted)]">{l}</p>
            <p className="text-lg font-bold text-white tabular-nums">{v === null ? "—" : num(v)}</p>
            {v === null && <p className="text-[10.5px] text-[var(--text-muted)]">Coming soon</p>}
          </div>
        ))}
      </div>
      <div className="flex items-start gap-2 rounded-lg bg-[var(--accent-blue-glow)] px-3 py-2.5 text-xs text-[var(--text-primary)]">
        <Lightbulb size={14} className="mt-0.5 shrink-0 text-[var(--accent-blue)]" />
        <p><b>Action:</b>{" "}
          {tone === "good" ? "Keep replying to every review."
            : `Ask every happy customer for a review at billing${reviews.unanswered ? ` and reply to the ${reviews.unanswered} unanswered reviews` : ""}${reviews.response === "Partial" || reviews.response === "No" ? "; reply to every review, not only some" : ""}.`}
        </p>
      </div>
      {reviews.rating_as_of && <p className="text-[10.5px] text-[var(--text-muted)]">Rating as of {reviews.rating_as_of.slice(0, 10)}{reviews.total_reviews !== null && ` · ${num(reviews.total_reviews)} reviews in total`}</p>}
    </div>
  );
}

/** "What should you do now to stay on target?" — the store's funnel, where
 *  it's slipping, Google reputation and the next steps for the team. */
export function StayOnTarget({ funnel, reviews, money, period }: {
  funnel: Funnel; reviews: Reviews; money: (n: number | null | undefined) => string;
  period: { days_total: number; days_remaining: number };
}) {
  const [metric, setMetric] = useState<"views" | "followers">("views");
  const byKey = Object.fromEntries(funnel.stages.map((s) => [s.key, s])) as Record<StageKey, FunnelStage>;
  const elapsed = period.days_total - period.days_remaining;
  return (
    <div className="space-y-4">
      <section className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 sm:p-6 space-y-4" aria-labelledby="stay-h">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 id="stay-h" className="flex items-center gap-2.5 text-base sm:text-lg font-bold text-white tracking-tight">
              <Target size={22} style={{ color: "#e5484d" }} />
              What should you do now to stay on target?
            </h2>
            <p className="mt-0.5 text-xs text-[var(--text-muted)]">Visibility → Leads → Hot leads → Customers · priorities and next steps for this period</p>
          </div>
          <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
            Visibility metric
            <select id="visibility-metric" value={metric} onChange={(e) => setMetric(e.target.value as "views" | "followers")}
              className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-primary)] px-2 py-1 text-xs text-white focus:outline-none focus:border-blue-500">
              <option value="views">Views</option>
              <option value="followers">Followers</option>
            </select>
          </label>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] items-stretch gap-3">
          {funnel.stages.map((s, i) => (
            <Fragment key={s.key}>
              {i > 0 && <ArrowRight size={18} className="hidden xl:block self-center text-[var(--text-muted)]" aria-hidden />}
              <StageCard stage={s} closed={funnel.closed} metric={metric} />
            </Fragment>
          ))}
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-subtle)] text-center">
          {funnel.ratios.map((r, i) => (
            <div key={r.label} className={`px-3 py-2.5 ${i ? "border-l border-[var(--border-subtle)]" : ""}`}>
              <p className="text-[11px] text-[var(--text-secondary)]">{r.label}</p>
              <p className="text-base font-bold text-white tabular-nums">{r.pct === null ? "—" : `${r.pct}%`}</p>
            </div>
          ))}
        </div>

        <div>
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">Do this now</p>
          {funnel.actions.length === 0 ? (
            <p className="rounded-xl border border-[var(--border-subtle)] p-3 text-xs text-[var(--text-secondary)]">Every stage is on pace. Keep the daily rhythm.</p>
          ) : (
            <ol className="space-y-2">
              {funnel.actions.map((a, i) => (
                <li key={i} className="flex items-start gap-3 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-card)] px-3 py-2.5">
                  <span className="mt-0.5 h-5 w-5 shrink-0 rounded-full bg-[var(--accent-blue)] text-[11px] font-bold text-white flex items-center justify-center">{i + 1}</span>
                  <div className="text-xs text-[var(--text-primary)]">
                    <p><Rich text={a.text} /></p>
                    <p className="mt-0.5 text-[10.5px] text-[var(--text-muted)]">{a.who}</p>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4 items-start">
        <section className="lg:col-span-3 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 sm:p-5 space-y-3" aria-labelledby="slip-h">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 id="slip-h" className="flex items-center gap-2 text-sm sm:text-base font-bold text-white"><Gauge size={18} className="text-[var(--accent-blue)]" />Where is performance slipping?</h3>
            <span className="text-[11px] text-[var(--text-muted)]">{funnel.closed ? `Period closed (${period.days_total} days)` : `Based on ${elapsed} of ${period.days_total} days (${Math.round(elapsed / period.days_total * 100)}%)`}</span>
          </div>
          <div className="overflow-x-auto rounded-xl border border-[var(--border-subtle)]">
            <table className="w-full min-w-[520px] text-xs">
              <thead>
                <tr className="border-b border-[var(--border-subtle)] bg-[var(--bg-subtle)] text-[10px] uppercase tracking-wider text-[var(--text-secondary)]">
                  <th className="py-2.5 px-3 text-left font-semibold">Stage</th>
                  <th className="py-2.5 px-3 text-left font-semibold">Gap &amp; pace needed</th>
                  <th className="py-2.5 px-3 text-left font-semibold">Next step</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-subtle)]">
                {funnel.slipping.map((row) => {
                  const Icon = STAGE_ICON[row.key];
                  return (
                    <tr key={row.key}>
                      <td className="py-2.5 px-3 font-semibold text-white whitespace-nowrap"><span className="inline-flex items-center gap-2"><Icon size={15} style={{ color: STAGE_COLOR[row.key] }} />{row.title}</span></td>
                      <td className="py-2.5 px-3"><SlipCell row={row} stage={byKey[row.key]} /></td>
                      <td className="py-2.5 px-3 text-[var(--text-secondary)]">{row.kind === "not_measured" ? "Get this measured first." : row.next_step}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {funnel.bottleneck.length > 0 ? (
            <p className="flex items-start gap-2 rounded-lg px-3 py-2 text-xs text-[var(--text-primary)]" style={{ background: `color-mix(in srgb, ${STATUS_COLOR.crit} 12%, transparent)` }}>
              <AlertTriangle size={14} className="mt-0.5 shrink-0" style={{ color: STATUS_COLOR.crit }} />
              <span><b style={{ color: STATUS_COLOR.crit }}>Main bottleneck:</b> {funnel.bottleneck.map((b) => `${b.title.toLowerCase()} (${Math.round(b.pct ?? 0)}% of target)`).join(" and ")}.</span>
            </p>
          ) : (
            <p className="rounded-lg px-3 py-2 text-xs text-[var(--text-primary)]" style={{ background: `color-mix(in srgb, ${STATUS_COLOR.good} 12%, transparent)` }}>Every measured stage is on pace.</p>
          )}
          {funnel.not_measured.length > 0 && (
            <p className="rounded-lg bg-[var(--accent-blue-glow)] px-3 py-2 text-xs text-[var(--text-primary)]">Not measured yet: {funnel.not_measured.join(", ").toLowerCase()}.</p>
          )}
        </section>
        <section className="lg:col-span-2 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 sm:p-5 space-y-3" aria-labelledby="rep-h">
          <h3 id="rep-h" className="flex items-center gap-2 text-sm sm:text-base font-bold text-white"><Star size={18} className="text-amber-500" />Google reputation</h3>
          <Reputation reviews={reviews} />
        </section>
      </div>

      {funnel.run_rate && (
        <section className="flex flex-wrap items-baseline gap-x-5 gap-y-1.5 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] px-4 sm:px-6 py-3.5 text-sm tabular-nums" aria-label="Run-rate estimate">
          <span className="font-bold text-white">Period-end at today's pace:</span>
          {funnel.stages.map((s) => (
            <span key={s.key}><b className="text-white">{fmtFor(s.key)(funnel.run_rate![s.key])}</b> <span className="text-[var(--text-secondary)]">{s.unit}</span></span>
          ))}
          <span className="text-[var(--text-secondary)]">· {money(funnel.run_rate.revenue)} revenue</span>
          <span className="ml-auto text-[11px] text-[var(--text-muted)]">An estimate, not a promise.</span>
        </section>
      )}
    </div>
  );
}
