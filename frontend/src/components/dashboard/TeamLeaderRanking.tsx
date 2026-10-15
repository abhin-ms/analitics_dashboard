import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { formatMoney } from "@/lib/formatMoney";
import { PeriodFilter, PeriodKey, periodRange } from "@/features/crm/components/shared";
import { Trophy, BarChart3, X, ArrowUp, ArrowDown, Loader2 } from "lucide-react";

// Rank of team leaders on one score: the team leader's own position and
// neighbours (team leader dashboard), or the full table (admin dashboard).
// Scoring rules: backend/app/services/tl_ranking.py.

type AreaKey = "sales" | "tele" | "leads" | "conv";
interface StoreSales { name: string; currency: string; revenue: number; target: number; pct: number | null }
interface Details {
  sales: { stores: StoreSales[]; with_target: number; on_target: number };
  tele: { leads_due: number; called: number; called_pct: number | null; attempted: number; connected: number;
    connected_pct: number | null; followups_due: number; followups_on_time: number; followups_pct: number | null };
  leads: { leads: number; entries: number; target: number; short_by: number; sheet_tabs: string[] };
  conv: { converted: number; lead_conv_pct: number | null; conv_target_pct: number | null; walkins: number;
    walkin_bills: number; walkin_buy_pct: number | null; walkin_target_pct: number };
}
interface Row {
  team_leader_id: number; name: string; stores: string[]; rank: number | null; score: number | null;
  rating: string | null; previous_score: number | null; change: number | null;
  areas: Record<AreaKey, number | null> | null; weakest: AreaKey | null; details: Details | null;
}
interface Ranking {
  period: { start: string; end: string; counted_to: string; previous: { start: string; end: string; label: string } };
  viewer: { is_admin: boolean; team_leader_id: number | null };
  areas: { key: AreaKey; label: string; weight: number }[];
  team_average: { score: number | null; areas: Record<AreaKey, number | null> };
  rows: Row[];
}

const RATING_STEPS = ["Poor", "Needs work", "Average", "Good", "Excellent"];
const tone = (v: number | null) => (v == null ? "text-[var(--text-muted)]" : v >= 75 ? "text-emerald-400" : v >= 55 ? "text-amber-400" : "text-rose-400");
const toneBg = (v: number | null) => (v == null ? "bg-zinc-500/10" : v >= 75 ? "bg-emerald-500/10" : v >= 55 ? "bg-amber-500/10" : "bg-rose-500/10");
const toneBar = (v: number | null) => (v == null ? "bg-zinc-500" : v >= 75 ? "bg-emerald-500" : v >= 55 ? "bg-amber-500" : "bg-rose-500");
const MEDAL = ["text-yellow-400", "text-zinc-300", "text-orange-400"];
// Sheet-made accounts are in capitals ("DEVIAHH"): show them as names.
const displayName = (n: string) => (n === n.toUpperCase() ? n.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()) : n);
const ordinal = (n: number) => { const s = ["th", "st", "nd", "rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); };
const fmtDate = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });
const num = (n: number) => n.toLocaleString("en-IN");
const pctText = (v: number | null) => (v == null ? "No data" : `${Math.round(v)}%`);

function Change({ value, label }: { value: number | null; label: string }) {
  if (value == null) return <span className="text-xs text-[var(--text-muted)]">No score for the {label}</span>;
  const up = value >= 0;
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-semibold tabular-nums ${up ? "text-emerald-400" : "text-rose-400"}`}>
      {up ? <ArrowUp size={12} /> : <ArrowDown size={12} />}{Math.abs(value).toFixed(1)} points
      <span className="font-normal text-[var(--text-muted)]">vs {label}</span>
    </span>
  );
}

function RatingSteps({ rating }: { rating: string | null }) {
  const filled = rating ? RATING_STEPS.indexOf(rating) + 1 : 0;
  return (
    <span className="inline-flex gap-1" aria-label={rating ? `Rating: ${rating}` : "No rating"}>
      {RATING_STEPS.map((s, i) => <i key={s} className={`block h-3 w-3 rounded-[3px] ${i < filled ? "bg-[var(--accent-blue)]" : "bg-[var(--border-subtle)]"}`} />)}
    </span>
  );
}

export default function TeamLeaderRanking() {
  const [periodKey, setPeriodKey] = useState<PeriodKey>("month");
  const [custom, setCustom] = useState(() => periodRange("month"));
  const range = periodRange(periodKey, custom);
  const validRange = !!range.start && !!range.end && range.start <= range.end;
  const [openId, setOpenId] = useState<number | null>(null);

  const { data, isLoading, isFetching, error } = useQuery({
    queryKey: ["tl-ranking", range.start, range.end],
    queryFn: () => api.get<Ranking>(`/tl-ranking?start=${range.start}&end=${range.end}`),
    enabled: validRange,
    refetchInterval: 300000,
    placeholderData: (prev) => prev,
  });

  const header = (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <Trophy size={16} className="text-[var(--accent-blue)]" />
          {data?.viewer.is_admin ? "Team leader ranking" : "Your rank among team leaders"}
          {isFetching && <Loader2 size={13} className="animate-spin text-[var(--text-muted)]" />}
        </h3>
        {data && (
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            {fmtDate(data.period.start)} to {fmtDate(data.period.counted_to)} · targets counted for these days only
          </p>
        )}
      </div>
      <PeriodFilter value={periodKey} onChange={(k) => { setPeriodKey(k); setOpenId(null); }} custom={custom} onCustom={setCustom} />
    </div>
  );

  let body: ReactNode;
  if (!validRange) body = <p className="text-xs text-[var(--text-muted)]">Pick a start date on or before the end date.</p>;
  else if (isLoading) body = <div className="h-40 animate-pulse rounded-xl bg-[var(--bg-primary)]" />;
  else if (error || !data) body = <p className="text-xs text-rose-400">The ranking could not be loaded. {(error as Error)?.message}</p>;
  else if (data.viewer.is_admin) body = <Leaderboard data={data} openId={openId} onOpen={setOpenId} />;
  else body = <MyRank data={data} openId={openId} onOpen={setOpenId} />;

  const open = data?.rows.find((r) => r.team_leader_id === openId && r.details);
  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 space-y-4">
      {header}
      {body}
      {data && open && <Analysis data={data} row={open} self={!data.viewer.is_admin} onClose={() => setOpenId(null)} />}
    </div>
  );
}

// ── Team leader: own rank and the neighbours ────────────────────────
function MyRank({ data, openId, onOpen }: { data: Ranking; openId: number | null; onOpen: (id: number | null) => void }) {
  const me = data.rows.find((r) => r.team_leader_id === data.viewer.team_leader_id);
  if (!me) return <p className="text-xs text-[var(--text-muted)]">No stores or lead sheets are assigned to you yet, so there is no rank to show.</p>;
  const ranked = data.rows.filter((r) => r.rank != null);
  const n = ranked.length;
  const i = ranked.findIndex((r) => r.team_leader_id === me.team_leader_id);
  const prevLabel = data.period.previous.label;

  const badge = i < 0 ? null : i === 0 ? ["Top of the team", "text-yellow-400 border-yellow-400/40"]
    : i === n - 1 ? ["Last place", "text-rose-400 border-rose-400/40"]
    : i < 3 ? ["In the top 3", "text-emerald-400 border-emerald-400/40"] : ["Middle of the table", "text-amber-400 border-amber-400/40"];

  // 1st, the one above, you, the one below, last — each once.
  const shown = i < 0 ? ranked.slice(0, 3).map((_, k) => k)
    : [...new Set([0, i - 1, i, i + 1, n - 1].filter((k) => k >= 0 && k < n))].sort((a, b) => a - b);

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,300px)_minmax(0,1fr)]">
      <div className="space-y-3 lg:border-r lg:border-[var(--border-subtle)] lg:pr-5">
        {i < 0 ? (
          <p className="text-sm text-[var(--text-secondary)]">Not enough data for a score in this period yet.</p>
        ) : (
          <>
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="text-5xl font-extrabold text-white tabular-nums leading-none">{ordinal(i + 1)}</span>
              <span className="text-sm text-[var(--text-muted)] font-medium">of {n} team leaders</span>
            </div>
            {badge && <span className={`inline-block rounded-full border px-2.5 py-0.5 text-xs font-semibold ${badge[1]}`}>{badge[0]}</span>}
            <div className="flex flex-wrap gap-5">
              <div>
                <p className="text-xl font-semibold text-white tabular-nums">{me.score?.toFixed(1)}</p>
                <p className="text-[11px] text-[var(--text-muted)]">Performance score / 100</p>
              </div>
              <div>
                <p className="pt-1.5"><RatingSteps rating={me.rating} /></p>
                <p className="text-[11px] text-[var(--text-muted)] mt-1">Rating: {me.rating}</p>
              </div>
            </div>
            <Change value={me.change} label={prevLabel} />
          </>
        )}
        {me.details && (
          <button onClick={() => onOpen(openId === me.team_leader_id ? null : me.team_leader_id)}
            aria-expanded={openId === me.team_leader_id}
            className="w-full inline-flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 px-3 py-2 text-xs font-semibold text-white cursor-pointer">
            <BarChart3 size={14} />{openId === me.team_leader_id ? "Hide analysis" : "Analyse my performance"}
          </button>
        )}
      </div>

      <div className="space-y-2 min-w-0">
        <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">Where you stand · score out of 100</p>
        {shown.map((k, pos) => {
          const r = ranked[k];
          const you = k === i;
          const tag = you ? "You" : k === 0 ? "1st" : k === n - 1 ? "Last" : k === i - 1 ? "Above you" : k === i + 1 ? "Below you" : "";
          const gapBefore = pos > 0 && k - shown[pos - 1] > 1;
          return (
            <div key={r.team_leader_id} className="space-y-2">
              {gapBefore && <p className="text-center text-xs tracking-[.3em] text-[var(--text-muted)]">· · ·</p>}
              {you && i > 0 && (
                <p className="px-3 text-xs text-[var(--text-muted)]"><span className="font-semibold text-amber-400">↑ {(ranked[i - 1].score! - r.score!).toFixed(1)} points</span> to pass {displayName(ranked[i - 1].name)}</p>
              )}
              <div className={`grid grid-cols-[2.5rem_minmax(0,1fr)_auto] items-center gap-3 rounded-xl border px-3 py-2.5 ${you ? "border-[var(--accent-blue)] bg-blue-500/10" : "border-transparent bg-[var(--bg-primary)]"}`}>
                <span className={`font-mono text-sm font-semibold tabular-nums ${k < 3 ? MEDAL[k] : "text-[var(--text-muted)]"}`}>#{r.rank}</span>
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-white">
                    {displayName(r.name)}{you && " (you)"}
                    {tag && <span className={`rounded-md px-1.5 py-px text-[10px] font-bold uppercase tracking-wide ${you ? "bg-[var(--accent-blue)] text-white" : "bg-[var(--border-subtle)] text-[var(--text-secondary)]"}`}>{tag}</span>}
                    <span className="text-[11px] font-normal text-[var(--text-muted)]">{r.stores.length} store{r.stores.length === 1 ? "" : "s"}</span>
                  </p>
                  <div className="mt-1.5 h-1.5 rounded-full bg-[var(--border-subtle)] overflow-hidden">
                    <div className={`h-full rounded-full ${you ? "bg-[var(--accent-blue)]" : "bg-[var(--text-secondary)]"}`} style={{ width: `${r.score}%` }} />
                  </div>
                </div>
                <span className="font-mono text-sm font-semibold text-white tabular-nums">{r.score!.toFixed(1)}</span>
              </div>
              {you && i < n - 1 && (
                <p className="px-3 text-xs text-[var(--text-muted)]"><span className="font-semibold text-emerald-400">↓ {(r.score! - ranked[i + 1].score!).toFixed(1)} points</span> ahead of {displayName(ranked[i + 1].name)}</p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Admin: every team leader ────────────────────────────────────────
function Leaderboard({ data, openId, onOpen }: { data: Ranking; openId: number | null; onOpen: (id: number | null) => void }) {
  const ranked = data.rows.filter((r) => r.rank != null);
  if (data.rows.length === 0) return <p className="text-xs text-[var(--text-muted)]">No team leaders have stores or lead sheets assigned yet.</p>;
  const improved = [...ranked].filter((r) => r.change != null).sort((a, b) => b.change! - a.change!)[0];
  const chips: [string, string][] = [];
  if (ranked[0]) chips.push(["Top", `${displayName(ranked[0].name)} · ${ranked[0].score!.toFixed(1)}`]);
  if (improved && improved.change! > 0) chips.push(["Most improved", `${displayName(improved.name)} · ▲ ${improved.change!.toFixed(1)}`]);
  if (ranked.length > 1) chips.push(["Needs attention", `${displayName(ranked[ranked.length - 1].name)} · ${ranked[ranked.length - 1].score!.toFixed(1)}`]);
  if (data.team_average.score != null) chips.push(["Team average", data.team_average.score.toFixed(1)]);

  return (
    <div className="space-y-3">
      {chips.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {chips.map(([l, v]) => (
            <div key={l} className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] px-3 py-2">
              <p className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)]">{l}</p>
              <p className="text-sm font-semibold text-white">{v}</p>
            </div>
          ))}
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[920px] text-sm text-left border-collapse">
          <thead>
            <tr className="text-[var(--text-muted)] text-[11px] uppercase tracking-wider border-b border-[var(--border-subtle)]">
              <th className="py-2.5 px-3 font-semibold">Rank</th>
              <th className="py-2.5 px-3 font-semibold">Team leader</th>
              <th className="py-2.5 px-3 font-semibold">Score</th>
              <th className="py-2.5 px-3 font-semibold">Rating</th>
              {data.areas.map((a) => <th key={a.key} className="py-2.5 px-3 font-semibold text-center">{a.label}</th>)}
              <th className="py-2.5 px-3 font-semibold">vs {data.period.previous.label}</th>
              <th className="py-2.5 px-3 font-semibold">Weakest area</th>
              <th className="py-2.5 px-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border-subtle)]">
            {data.rows.map((r) => {
              const label = data.areas.find((a) => a.key === r.weakest)?.label;
              return (
                <tr key={r.team_leader_id} className={openId === r.team_leader_id ? "bg-blue-500/10" : "hover:bg-[var(--bg-card-hover)]"}>
                  <td className={`py-3 px-3 font-mono font-semibold tabular-nums ${r.rank && r.rank <= 3 ? MEDAL[r.rank - 1] : "text-[var(--text-muted)]"}`}>
                    {r.rank ? `#${r.rank}` : "–"}
                    {r.rank != null && r.rank === ranked.length && ranked.length > 1 && <span className="ml-1.5 font-sans text-[10px] font-semibold text-rose-400">Last</span>}
                  </td>
                  <td className="py-3 px-3">
                    <p className="font-semibold text-white">{displayName(r.name)}</p>
                    <p className="text-[11px] text-[var(--text-muted)] truncate max-w-[14rem]" title={r.stores.join(", ")}>{r.stores.length} store{r.stores.length === 1 ? "" : "s"}</p>
                  </td>
                  <td className="py-3 px-3">
                    {r.score == null ? <span className="text-xs text-[var(--text-muted)]">No data</span> : (
                      <div className="flex items-center gap-2 min-w-[8rem]">
                        <span className="w-9 font-mono font-semibold text-white tabular-nums">{r.score.toFixed(1)}</span>
                        <div className="h-1.5 flex-1 rounded-full bg-[var(--border-subtle)] overflow-hidden"><div className="h-full rounded-full bg-[var(--accent-blue)]" style={{ width: `${r.score}%` }} /></div>
                      </div>
                    )}
                  </td>
                  <td className="py-3 px-3 text-xs text-[var(--text-secondary)]">{r.rating ?? "–"}</td>
                  {data.areas.map((a) => {
                    const v = r.areas?.[a.key] ?? null;
                    return (
                      <td key={a.key} className="py-3 px-3 text-center">
                        <span className={`inline-block min-w-[2.5rem] rounded-lg px-2 py-0.5 font-mono text-xs font-semibold tabular-nums ${tone(v)} ${toneBg(v)}`}>{v == null ? "–" : Math.round(v)}</span>
                      </td>
                    );
                  })}
                  <td className="py-3 px-3 font-mono text-xs tabular-nums">
                    {r.change == null ? <span className="text-[var(--text-muted)]">–</span>
                      : <span className={r.change >= 0 ? "text-emerald-400" : "text-rose-400"}>{r.change >= 0 ? "▲" : "▼"} {Math.abs(r.change).toFixed(1)}</span>}
                  </td>
                  <td className="py-3 px-3 text-xs text-[var(--text-secondary)]">{label ?? "–"}</td>
                  <td className="py-3 px-3 text-right">
                    {r.details && (
                      <button onClick={() => onOpen(openId === r.team_leader_id ? null : r.team_leader_id)} aria-expanded={openId === r.team_leader_id}
                        className="rounded-lg bg-blue-500/10 px-2.5 py-1 text-xs font-semibold text-blue-400 hover:bg-blue-500/20 cursor-pointer">
                        {openId === r.team_leader_id ? "Close" : "Analyse"}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-[var(--text-muted)]">Area scores out of 100: green 75 and above, amber 55 to 74, red below 55. A dash means no data for that area in this period; the score then uses the other areas.</p>
    </div>
  );
}

// ── The analysis box ────────────────────────────────────────────────
function Analysis({ data, row, self, onClose }: { data: Ranking; row: Row; self: boolean; onClose: () => void }) {
  const d = row.details!;
  const areas = row.areas!;
  const who = self ? "You" : displayName(row.name);
  const lines: Record<AreaKey, [string, string][]> = {
    sales: [
      ["Stores on target", `${d.sales.on_target} of ${d.sales.with_target}`],
      ...d.sales.stores.filter((s) => s.pct != null).sort((a, b) => a.pct! - b.pct!).slice(0, 3)
        .map((s): [string, string] => [s.name, `${Math.round(s.pct!)}%`]),
    ],
    tele: [
      ["Leads called", d.tele.leads_due ? `${d.tele.called} of ${d.tele.leads_due}` : "No data"],
      ["Calls connected", pctText(d.tele.connected_pct)],
      ["Follow-ups on time", d.tele.followups_due ? `${d.tele.followups_on_time} of ${d.tele.followups_due}` : "No data"],
    ],
    leads: [["New leads", num(d.leads.leads)], ["Target for these days", num(d.leads.target)], ["Short by", num(d.leads.short_by)]],
    conv: [
      ["Leads converted", d.leads.leads ? `${d.conv.converted} (${pctText(d.conv.lead_conv_pct)})` : "No data"],
      ["Conversion target", d.conv.conv_target_pct != null ? `${d.conv.conv_target_pct}%` : "Not set"],
      ["Walk-ins who bought", d.conv.walkins ? `${num(d.conv.walkin_bills)} of ${num(d.conv.walkins)}` : "No data"],
    ],
  };

  const behind = d.sales.stores.filter((s) => s.pct != null && s.pct < 100).sort((a, b) => a.pct! - b.pct!);
  const notCalled = d.tele.leads_due - d.tele.called;
  const tips: Record<AreaKey, string[]> = {
    sales: [
      ...behind.slice(0, 2).map((s) => `${s.name} is at ${Math.round(s.pct!)}% of its target: ${formatMoney(s.target - s.revenue, s.currency)} more needed for these days.`),
      "Call back leads marked Hot, Will visit and Appointment first; they close most often.",
    ],
    tele: [
      ...(notCalled > 0 ? [`${num(notCalled)} lead${notCalled === 1 ? " is" : "s are"} more than 24 hours old with no call status. Call them first.`] : []),
      ...(d.tele.connected_pct != null && d.tele.connected_pct < 60 ? [`Only ${Math.round(d.tele.connected_pct)}% of calls connected. Retry unanswered numbers at a different time of day.`] : []),
      ...(d.tele.followups_due && d.tele.followups_pct != null && d.tele.followups_pct < 90 ? [`${d.tele.followups_due - d.tele.followups_on_time} follow-ups were late. Clear overdue follow-ups before new calls.`] : []),
      "Make sure every lead's status is updated after each call, in the sheet or the app.",
    ],
    leads: [
      `${num(d.leads.short_by)} leads short of the target for these days.`,
      "Ask the stores to log every walk-in enquiry and phone enquiry as a lead.",
      "Check that every store tab in your lead sheet is being filled daily.",
    ],
    conv: [
      ...(d.conv.lead_conv_pct != null && d.conv.conv_target_pct ? [`${Math.round(d.conv.lead_conv_pct)}% of leads became sales against a ${d.conv.conv_target_pct}% target. Book appointments instead of leaving leads at "Call back later".`] : []),
      ...(d.conv.walkin_buy_pct != null ? [`${Math.round(d.conv.walkin_buy_pct)}% of walk-ins bought against ${d.conv.walkin_target_pct}%. Go through the lost-sale reasons in the stores' daily form.`] : []),
      "Mark converted leads as Sale Conversion so the sale is counted.",
    ],
  };

  const weakKey = row.weakest;
  const weakLabel = data.areas.find((a) => a.key === weakKey)?.label;
  const withData = data.areas.filter((a) => areas[a.key] != null);
  const totalW = withData.reduce((s, a) => s + a.weight, 0);
  const ranked = data.rows.filter((r) => r.rank != null);
  const pos = ranked.findIndex((r) => r.team_leader_id === row.team_leader_id);
  let next: string[] = [];
  if (pos === 0 && ranked.length > 1) {
    next = [`${who} ${self ? "are" : "is"} ${(row.score! - ranked[1].score!).toFixed(1)} points ahead of ${displayName(ranked[1].name)}.`];
  } else if (pos > 0 && weakKey && totalW) {
    const above = ranked[pos - 1];
    // the same gap the ladder shows; the area target aims just past it
    const need = Math.round((above.score! - row.score!) * 10) / 10;
    const w = data.areas.find((a) => a.key === weakKey)!.weight / totalW;
    const target = areas[weakKey]! + (need + 0.05) / w;
    next = [`${who} need${self ? "" : "s"} ${need.toFixed(1)} more points to pass ${displayName(above.name)} for ${ordinal(pos)} place.`];
    next.push(target <= 100
      ? `The fastest way: raise ${weakLabel?.toLowerCase()} from ${Math.round(areas[weakKey]!)} to ${Math.ceil(target)}.`
      : `${weakLabel} alone can't close the gap; improve it and the next weakest area together.`);
    if (pos === ranked.length - 1 && ranked.length > 1) next.push(`${displayName(ranked[0].name)} is 1st with ${ranked[0].score!.toFixed(1)}.`);
  }

  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-4 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h4 className="text-sm font-bold text-white">{self ? "Your performance" : displayName(row.name)}: what to work on</h4>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">{fmtDate(data.period.start)} to {fmtDate(data.period.counted_to)}. Line on each bar = team leaders' average.</p>
        </div>
        <button onClick={onClose} aria-label="Close analysis" className="rounded-lg border border-[var(--border-subtle)] p-1.5 text-[var(--text-muted)] hover:text-white cursor-pointer"><X size={14} /></button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {data.areas.map((a) => {
          const v = areas[a.key];
          const avg = data.team_average.areas[a.key];
          const weak = a.key === weakKey;
          return (
            <div key={a.key} className={`rounded-xl border p-3 space-y-2 bg-[var(--bg-card)] ${weak ? "border-rose-500/60" : "border-[var(--border-subtle)]"}`}>
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-sm font-semibold text-white">{a.label}</span>
                <span className="text-[10px] text-[var(--text-muted)]">{Math.round(a.weight * 100)}% of score</span>
              </div>
              <p className={`font-mono text-2xl font-semibold tabular-nums ${tone(v)}`}>{v == null ? "–" : Math.round(v)}</p>
              <div className="relative h-2 rounded-full bg-[var(--border-subtle)]">
                {v != null && <div className={`absolute inset-y-0 left-0 rounded-full ${toneBar(v)}`} style={{ width: `${v}%` }} />}
                {avg != null && <div className="absolute -top-1 -bottom-1 w-0.5 bg-white/60" style={{ left: `${avg}%` }} title={`Team average ${Math.round(avg)}`} />}
              </div>
              {v != null && avg != null && (
                <span className={`inline-block rounded-full px-2 py-px text-[10px] font-bold ${v >= avg ? "bg-emerald-500/10 text-emerald-400" : "bg-rose-500/10 text-rose-400"}`}>
                  {weak && "Weakest area · "}{v >= avg ? "+" : ""}{Math.round(v - avg)} vs team
                </span>
              )}
              {v == null && <span className="block text-[11px] text-[var(--text-muted)]">No data in this period, so it doesn't count in the score.</span>}
              <ul className="space-y-0.5 text-xs text-[var(--text-secondary)]">
                {lines[a.key].map(([l, val]) => (
                  <li key={l} className="flex justify-between gap-2"><span className="truncate">{l}</span><b className="font-mono font-semibold text-white tabular-nums whitespace-nowrap">{val}</b></li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {weakKey && (
          <div className="rounded-xl border border-rose-500/50 p-3 space-y-2">
            <h5 className="text-sm font-bold text-rose-400">Concentrate on {weakLabel?.toLowerCase()}</h5>
            <ol className="list-decimal pl-4 space-y-1 text-xs text-[var(--text-secondary)]">
              {tips[weakKey].slice(0, 3).map((t) => <li key={t}>{t}</li>)}
            </ol>
          </div>
        )}
        {next.length > 0 && (
          <div className="rounded-xl border border-[var(--border-subtle)] p-3 space-y-2">
            <h5 className="text-sm font-bold text-white">{pos === 0 ? "Staying 1st" : `To reach ${ordinal(pos)} place`}</h5>
            <ol className="list-decimal pl-4 space-y-1 text-xs text-[var(--text-secondary)]">
              {next.map((t) => <li key={t}>{t}</li>)}
            </ol>
          </div>
        )}
      </div>
    </div>
  );
}
