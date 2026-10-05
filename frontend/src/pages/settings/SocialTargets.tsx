import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Target, Save, Search, RotateCcw } from "lucide-react";
import { api } from "@/lib/apiClient";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { fmtCompact, PLATFORMS, PLATFORM_LABEL, PLATFORM_COLOR, Platform } from "@/features/social/socialData";

interface TargetsResponse {
  platforms: Platform[];
  defaults: Record<Platform, number>;
  stores: { store_id: number; store: string; team_leader: string; in_tracker: boolean; overrides: Record<Platform, number | null> }[];
}

const key = (storeId: number, p: Platform) => `${storeId}:${p}`;
const parse = (v: string) => (v.trim() === "" ? null : Math.max(0, Math.round(Number(v.replace(/,/g, "")))));
const inputCls = "w-full px-2.5 py-1.5 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white text-right tabular-nums focus:outline-none focus:border-blue-500 placeholder:text-[var(--text-muted)]";

/** Admin: monthly social-media views target per store and platform. Blank
 * means "use the company default". A team leader's target is the sum of
 * their stores' targets, shown live below. */
export default function SocialTargets() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["social-targets"],
    queryFn: () => api.get<TargetsResponse>("/social/targets"),
  });
  const [defaults, setDefaults] = useState<Record<Platform, string>>({ instagram: "", youtube: "", facebook: "" });
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [q, setQ] = useState("");
  const [trackerOnly, setTrackerOnly] = useState(true);

  useEffect(() => {
    if (!data) return;
    setDefaults(Object.fromEntries(PLATFORMS.map((p) => [p, String(data.defaults[p])])) as Record<Platform, string>);
    const o: Record<string, string> = {};
    data.stores.forEach((s) => PLATFORMS.forEach((p) => { o[key(s.store_id, p)] = s.overrides[p] === null ? "" : String(s.overrides[p]); }));
    setOverrides(o);
  }, [data]);

  const changes = useMemo(() => {
    if (!data) return { defaults: {}, overrides: [] as { store_id: number; platform: Platform; monthly_target: number | null }[] };
    const d: Partial<Record<Platform, number>> = {};
    PLATFORMS.forEach((p) => {
      const v = parse(defaults[p]);
      if (v !== null && v !== data.defaults[p]) d[p] = v;
    });
    const o: { store_id: number; platform: Platform; monthly_target: number | null }[] = [];
    data.stores.forEach((s) => PLATFORMS.forEach((p) => {
      const v = parse(overrides[key(s.store_id, p)] ?? "");
      if (v !== s.overrides[p]) o.push({ store_id: s.store_id, platform: p, monthly_target: v });
    }));
    return { defaults: d, overrides: o };
  }, [data, defaults, overrides]);
  const dirty = Object.keys(changes.defaults).length + changes.overrides.length;

  const save = useMutation({
    mutationFn: () => api.put("/social/targets", changes),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["social-targets"] });
      qc.invalidateQueries({ queryKey: ["sheets-data"] });
    },
  });

  const effective = (storeId: number, p: Platform) =>
    parse(overrides[key(storeId, p)] ?? "") ?? parse(defaults[p]) ?? 0;

  const stores = (data?.stores || []).filter((s) =>
    (!trackerOnly || s.in_tracker) && `${s.store} ${s.team_leader}`.toLowerCase().includes(q.trim().toLowerCase()));

  const tlTotals = useMemo(() => {
    const m = new Map<string, { stores: number; totals: Record<Platform, number> }>();
    (data?.stores || []).filter((s) => s.in_tracker || !trackerOnly).forEach((s) => {
      const tl = s.team_leader || "Unassigned";
      const row = m.get(tl) || { stores: 0, totals: { instagram: 0, youtube: 0, facebook: 0 } };
      row.stores++;
      PLATFORMS.forEach((p) => { row.totals[p] += effective(s.store_id, p); });
      m.set(tl, row);
    });
    return [...m.entries()].sort((a, b) => b[1].stores - a[1].stores);
  }, [data, defaults, overrides, trackerOnly]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ErrorBoundary>
      <div className="space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
              <Target className="text-[var(--accent-blue)]" size={22} />
              Social Media Targets
            </h2>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              Monthly views target per store for each platform. A team leader's target is the sum of their stores'.
            </p>
          </div>
          <div className="flex items-center gap-3">
            {save.isError && <span className="text-xs text-rose-400">{(save.error as Error).message || "Save failed"}</span>}
            {save.isSuccess && !dirty && <span className="text-xs text-emerald-400">Saved</span>}
            <button
              onClick={() => save.mutate()}
              disabled={!dirty || save.isPending}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-[var(--accent-blue)] text-white hover:opacity-90 transition disabled:opacity-40"
            >
              <Save size={14} />
              {save.isPending ? "Saving..." : dirty ? `Save ${dirty} change${dirty === 1 ? "" : "s"}` : "Saved"}
            </button>
          </div>
        </div>

        {isLoading || !data ? (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-6"><TableSkeleton /></div>
        ) : (
          <>
            <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6">
              <h3 className="text-base font-bold text-white tracking-tight">Default target per store</h3>
              <p className="text-xs text-[var(--text-muted)] mt-0.5 mb-4">Used for every store that has no target of its own below.</p>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {PLATFORMS.map((p) => (
                  <label key={p} className="block rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-3">
                    <span className="flex items-center gap-2 text-xs font-semibold text-white mb-2">
                      <i className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: PLATFORM_COLOR[p] }} />
                      {PLATFORM_LABEL[p]} views / month
                    </span>
                    <input
                      type="number" min={0} step={10000} value={defaults[p]}
                      onChange={(e) => setDefaults((d) => ({ ...d, [p]: e.target.value }))}
                      className={inputCls}
                    />
                    <span className="mt-1 block text-right text-[11px] text-[var(--text-muted)]">{fmtCompact(parse(defaults[p]) ?? 0)}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6">
              <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                <div>
                  <h3 className="text-base font-bold text-white tracking-tight">Store targets</h3>
                  <p className="text-xs text-[var(--text-muted)] mt-0.5">Leave a box empty to use the default (shown in grey).</p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <label className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)] cursor-pointer">
                    <input type="checkbox" checked={trackerOnly} onChange={(e) => setTrackerOnly(e.target.checked)} />
                    Only stores in the tracker sheet
                  </label>
                  <label className="flex items-center gap-2 rounded-lg border border-[var(--border-subtle)] px-2.5 py-1.5">
                    <Search size={14} className="text-[var(--text-muted)]" />
                    <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a store or TL"
                      className="w-40 bg-transparent text-xs text-white outline-none placeholder:text-[var(--text-muted)]" />
                  </label>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-[var(--border-subtle)] text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                      <th className="py-2 pr-2 text-left font-semibold">Store</th>
                      <th className="py-2 px-2 text-left font-semibold">Team leader</th>
                      {PLATFORMS.map((p) => <th key={p} className="py-2 px-2 text-right font-semibold w-40">{PLATFORM_LABEL[p]}</th>)}
                      <th className="w-8" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border-subtle)]">
                    {stores.map((s) => {
                      const custom = PLATFORMS.some((p) => (overrides[key(s.store_id, p)] ?? "") !== "");
                      return (
                        <tr key={s.store_id}>
                          <td className="py-1.5 pr-2 font-medium text-white whitespace-nowrap">{s.store}</td>
                          <td className="py-1.5 px-2 text-[var(--text-secondary)] whitespace-nowrap">{s.team_leader || "—"}</td>
                          {PLATFORMS.map((p) => (
                            <td key={p} className="py-1.5 px-2">
                              <input
                                type="number" min={0} step={10000}
                                value={overrides[key(s.store_id, p)] ?? ""}
                                placeholder={defaults[p] ? `${Number(defaults[p]).toLocaleString("en-IN")}` : ""}
                                onChange={(e) => setOverrides((o) => ({ ...o, [key(s.store_id, p)]: e.target.value }))}
                                className={inputCls}
                                aria-label={`${s.store} ${PLATFORM_LABEL[p]} target`}
                              />
                            </td>
                          ))}
                          <td className="py-1.5 pl-1">
                            {custom && (
                              <button
                                title="Back to default"
                                onClick={() => setOverrides((o) => ({ ...o, ...Object.fromEntries(PLATFORMS.map((p) => [key(s.store_id, p), ""])) }))}
                                className="text-[var(--text-muted)] hover:text-white"
                              >
                                <RotateCcw size={14} />
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6">
              <h3 className="text-base font-bold text-white tracking-tight">Team leader targets</h3>
              <p className="text-xs text-[var(--text-muted)] mt-0.5 mb-4">Worked out automatically: the sum of each leader's stores. Updates as you edit above.</p>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-[var(--border-subtle)] text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                      <th className="py-2 pr-2 text-left font-semibold">Team leader</th>
                      <th className="py-2 px-2 text-right font-semibold">Stores</th>
                      {PLATFORMS.map((p) => <th key={p} className="py-2 px-2 text-right font-semibold">{PLATFORM_LABEL[p]}</th>)}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border-subtle)]">
                    {tlTotals.map(([tl, row]) => (
                      <tr key={tl}>
                        <td className="py-2 pr-2 font-medium text-white">{tl}</td>
                        <td className="py-2 px-2 text-right tabular-nums text-[var(--text-secondary)]">{row.stores}</td>
                        {PLATFORMS.map((p) => (
                          <td key={p} className="py-2 px-2 text-right tabular-nums text-white" title={row.totals[p].toLocaleString("en-IN")}>
                            {fmtCompact(row.totals[p])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </div>
    </ErrorBoundary>
  );
}
