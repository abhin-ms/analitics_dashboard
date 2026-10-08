import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Target, Save, Search, RotateCcw } from "lucide-react";
import { api } from "@/lib/apiClient";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";

type Field = "leads_monthly" | "conversion_pct";
const FIELDS: { key: Field; label: string; step: number; suffix: string }[] = [
  { key: "leads_monthly", label: "Leads / month", step: 100, suffix: "leads" },
  { key: "conversion_pct", label: "Conversion target", step: 0.5, suffix: "%" },
];

interface TargetsResponse {
  defaults: Record<Field, number>;
  stores: { store_id: number; store: string; country: string; team_leader: string; overrides: Record<Field, number | null> }[];
}

const key = (storeId: number, f: Field) => `${storeId}:${f}`;
const parse = (v: string) => (v.trim() === "" ? null : Math.max(0, Number(v.replace(/,/g, ""))));
const inputCls = "w-full px-2.5 py-1.5 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white text-right tabular-nums focus:outline-none focus:border-blue-500 placeholder:text-[var(--text-muted)]";

/** Admin: monthly lead and conversion targets the store portfolio measures
 * against. Blank means "use the company default". */
export default function LeadTargets() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["lead-targets"],
    queryFn: () => api.get<TargetsResponse>("/store-portfolio/lead-targets"),
  });
  const [defaults, setDefaults] = useState<Record<Field, string>>({ leads_monthly: "", conversion_pct: "" });
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [q, setQ] = useState("");

  useEffect(() => {
    if (!data) return;
    setDefaults({ leads_monthly: String(data.defaults.leads_monthly), conversion_pct: String(data.defaults.conversion_pct) });
    const o: Record<string, string> = {};
    data.stores.forEach((s) => FIELDS.forEach(({ key: f }) => { o[key(s.store_id, f)] = s.overrides[f] === null ? "" : String(s.overrides[f]); }));
    setOverrides(o);
  }, [data]);

  const changes = useMemo(() => {
    const d: Partial<Record<Field, number>> = {};
    const o: ({ store_id: number } & Record<Field, number | null>)[] = [];
    if (!data) return { defaults: d, overrides: o };
    FIELDS.forEach(({ key: f }) => {
      const v = parse(defaults[f]);
      if (v !== null && v !== data.defaults[f]) d[f] = v;
    });
    data.stores.forEach((s) => {
      const vals = Object.fromEntries(FIELDS.map(({ key: f }) => [f, parse(overrides[key(s.store_id, f)] ?? "")])) as Record<Field, number | null>;
      if (FIELDS.some(({ key: f }) => vals[f] !== s.overrides[f])) o.push({ store_id: s.store_id, ...vals });
    });
    return { defaults: d, overrides: o };
  }, [data, defaults, overrides]);
  const dirty = Object.keys(changes.defaults).length + changes.overrides.length;

  const save = useMutation({
    mutationFn: () => api.put("/store-portfolio/lead-targets", changes),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["lead-targets"] });
      qc.invalidateQueries({ queryKey: ["store-portfolio"] });
    },
  });

  const stores = (data?.stores || []).filter((s) =>
    `${s.store} ${s.team_leader} ${s.country}`.toLowerCase().includes(q.trim().toLowerCase()));

  return (
    <ErrorBoundary>
      <div className="space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
              <Target className="text-[var(--accent-blue)]" size={22} />
              Lead Targets
            </h2>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              Monthly leads and conversion % per store, used by each store's performance portfolio.
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
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-xl">
                {FIELDS.map((f) => (
                  <label key={f.key} className="block rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-3">
                    <span className="block text-xs font-semibold text-white mb-2">{f.label} ({f.suffix})</span>
                    <input type="number" min={0} step={f.step} max={f.key === "conversion_pct" ? 100 : undefined}
                      value={defaults[f.key]} onChange={(e) => setDefaults((d) => ({ ...d, [f.key]: e.target.value }))}
                      className={inputCls} />
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
                <label className="flex items-center gap-2 rounded-lg border border-[var(--border-subtle)] px-2.5 py-1.5">
                  <Search size={14} className="text-[var(--text-muted)]" />
                  <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a store or TL"
                    className="w-40 bg-transparent text-xs text-white outline-none placeholder:text-[var(--text-muted)]" />
                </label>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-[var(--border-subtle)] text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                      <th className="py-2 pr-2 text-left font-semibold">Store</th>
                      <th className="py-2 px-2 text-left font-semibold">Team leader</th>
                      {FIELDS.map((f) => <th key={f.key} className="py-2 px-2 text-right font-semibold w-40">{f.label}</th>)}
                      <th className="w-8" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border-subtle)]">
                    {stores.map((s) => {
                      const custom = FIELDS.some((f) => (overrides[key(s.store_id, f.key)] ?? "") !== "");
                      return (
                        <tr key={s.store_id}>
                          <td className="py-1.5 pr-2 font-medium text-white whitespace-nowrap">{s.store}</td>
                          <td className="py-1.5 px-2 text-[var(--text-secondary)] whitespace-nowrap">{s.team_leader || "—"}</td>
                          {FIELDS.map((f) => (
                            <td key={f.key} className="py-1.5 px-2">
                              <input
                                type="number" min={0} step={f.step} max={f.key === "conversion_pct" ? 100 : undefined}
                                value={overrides[key(s.store_id, f.key)] ?? ""}
                                placeholder={defaults[f.key]}
                                onChange={(e) => setOverrides((o) => ({ ...o, [key(s.store_id, f.key)]: e.target.value }))}
                                className={inputCls}
                                aria-label={`${s.store} ${f.label}`}
                              />
                            </td>
                          ))}
                          <td className="py-1.5 pl-1">
                            {custom && (
                              <button
                                title="Back to default"
                                onClick={() => setOverrides((o) => ({ ...o, ...Object.fromEntries(FIELDS.map((f) => [key(s.store_id, f.key), ""])) }))}
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
          </>
        )}
      </div>
    </ErrorBoundary>
  );
}
