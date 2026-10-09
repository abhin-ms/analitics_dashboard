import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { Fragment, useState, useEffect } from "react";
import { Shield, Save, Check, Loader2 } from "lucide-react";

/** Permissions in menu order, with the page each one controls. View = the
 * page is in the person's menu; the data on it is always limited to the
 * stores they're responsible for. Anything not listed shows under "Other". */
const GROUPS: { title: string; items: [string, string][] }[] = [
  { title: "Pages", items: [
    ["dashboard", "Dashboard"], ["store_overview", "Store Overview & store portfolio"], ["operations", "Operations"],
    ["team_leaders", "Team Leaders"], ["leads", "Leads & Leads Update"], ["campaigns", "Campaigns"], ["tasks", "Tasks"],
    ["investments", "Investments"], ["performance", "Performance"], ["social_performance", "Social Performance"],
    ["reports", "Reports"], ["stock_position", "Stock Position"], ["country_comparison", "Country Comparison"],
    ["sales_reports", "Sales Reports"], ["instagram", "Instagram (all Instagram pages)"],
  ] },
  { title: "Settings & administration", items: [
    ["users", "Users"], ["settings", "Settings pages (roles, branches, targets, currency…)"],
    ["sheet_assignments", "Sheet Assignments"], ["sheet_sync", "Data Sync"], ["roles", "Roles"],
    ["ai_analytics", "AI Analytics"],
  ] },
];
const ACTIONS = ["view", "create", "edit", "delete", "export", "manage"];

export default function RolesPermissions() {
  const [selectedRole, setSelectedRole] = useState<number | null>(null);
  const [permMap, setPermMap] = useState<Record<string, boolean>>({});
  const queryClient = useQueryClient();

  const { data: roles } = useQuery({ queryKey: ["roles"], queryFn: () => api.get<any[]>("/roles/") });
  const { data: allPerms } = useQuery({ queryKey: ["all-permissions"], queryFn: () => api.get<any[]>("/roles/permissions/all") });
  const { data: rolePerms, isLoading } = useQuery({
    queryKey: ["role-perms", selectedRole],
    queryFn: () => api.get<any[]>(`/roles/${selectedRole}/permissions`),
    enabled: !!selectedRole,
  });

  useEffect(() => {
    if (roles && roles.length > 0 && selectedRole === null) {
      setSelectedRole(roles[0].id);
    }
  }, [roles]);

  useEffect(() => {
    if (rolePerms) {
      const map: Record<string, boolean> = {};
      rolePerms.forEach((p: any) => { map[`${p.resource}:${p.action}`] = true; });
      setPermMap(map);
    }
  }, [rolePerms]);

  const saveMutation = useMutation({
    mutationFn: (ids: number[]) => api.put(`/roles/${selectedRole}/permissions`, { permission_ids: ids }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["role-perms"] }),
  });

  const toggle = (resource: string, action: string) => {
    setPermMap(prev => ({ ...prev, [`${resource}:${action}`]: !prev[`${resource}:${action}`] }));
  };

  // Rows come from the permissions that exist, so a new page shows up here
  // as soon as its permission does.
  const available = new Set((allPerms || []).map((p: any) => `${p.resource}:${p.action}`));
  const known = new Set(GROUPS.flatMap((g) => g.items.map(([r]) => r)));
  const others = [...new Set((allPerms || []).map((p: any) => p.resource as string))].filter((r) => !known.has(r)).sort();
  const groups = [
    ...GROUPS.map((g) => ({ ...g, items: g.items.filter(([r]) => ACTIONS.some((a) => available.has(`${r}:${a}`))) })),
    ...(others.length ? [{ title: "Other", items: others.map((r): [string, string] => [r, r.replace(/_/g, " ")]) }] : []),
  ].filter((g) => g.items.length);

  const save = () => {
    if (!selectedRole || !allPerms) return;
    const ids = allPerms.filter((p: any) => permMap[`${p.resource}:${p.action}`]).map((p: any) => p.id);
    saveMutation.mutate(ids);
  };

  return (
    <ErrorBoundary>
      <div className="space-y-6">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <Shield className="text-[var(--accent-blue)]" size={22} />
            Roles & Permissions Matrix
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            View puts a page in that role's menu. Whatever a page shows is limited to the person's own stores — a team
            leader's stores, a store owner's store, a regional manager's assigned stores (CEO, COO and admins see all).
          </p>
        </div>

        {/* Role Selector Pills */}
        <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-none">
          {(roles || []).map((r: any) => (
            <button
              key={r.id}
              onClick={() => setSelectedRole(r.id)}
              className={`px-4 py-2 rounded-xl text-xs font-semibold transition-all cursor-pointer whitespace-nowrap ${
                selectedRole === r.id
                  ? "bg-[var(--accent-blue)] text-white shadow-md"
                  : "bg-[var(--bg-card)] border border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-white"
              }`}
            >
              {r.name}
            </button>
          ))}
        </div>

        {selectedRole && (
          <div className="space-y-4">
            <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 sm:p-6 overflow-auto">
              {isLoading ? (
                <TableSkeleton rows={5} cols={6} />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm text-left border-collapse">
                    <thead>
                      <tr className="text-[var(--text-muted)] text-xs uppercase tracking-wider border-b border-[var(--border-subtle)]">
                        <th className="py-3 px-4 font-semibold">Page / area</th>
                        {ACTIONS.map((a) => (
                          <th key={a} className="py-3 px-4 font-semibold text-center capitalize">
                            {a}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--border-subtle)]">
                      {groups.map((g) => (
                        <Fragment key={g.title}>
                          <tr className="bg-[var(--bg-subtle)]">
                            <td colSpan={ACTIONS.length + 1} className="py-2 px-4 text-[10px] font-bold uppercase tracking-wider text-[var(--text-secondary)]">
                              {g.title}
                            </td>
                          </tr>
                          {g.items.map(([res, label]) => (
                            <tr key={res} className="hover:bg-[var(--bg-card-hover)] transition-colors">
                              <td className="py-3 px-4 text-white font-semibold text-xs">{label}</td>
                              {ACTIONS.map((act) => (
                                <td key={act} className="py-3 px-4 text-center">
                                  {available.has(`${res}:${act}`) ? (
                                    <input
                                      type="checkbox"
                                      checked={!!permMap[`${res}:${act}`]}
                                      onChange={() => toggle(res, act)}
                                      aria-label={`${label} — ${act}`}
                                      className="h-4 w-4 rounded border-[var(--border-subtle)] bg-[var(--bg-primary)] text-[var(--accent-blue)] focus:ring-0 cursor-pointer"
                                    />
                                  ) : (
                                    <span className="text-[var(--text-muted)]">—</span>
                                  )}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <button
              onClick={save}
              disabled={saveMutation.isPending}
              className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-semibold shadow-lg shadow-blue-500/20 disabled:opacity-50 transition-all cursor-pointer"
            >
              {saveMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
              <span>{saveMutation.isPending ? "Saving Permissions..." : "Save Permissions"}</span>
            </button>
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
}
