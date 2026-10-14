import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { RefreshCw, Database, Loader2 } from "lucide-react";

interface LeadTab { name: string; tab: string; leads: number; last_synced_at: string | null; ok: boolean; error: string | null }
interface BackgroundSheets {
  lead_sheets: { team_leader: string; spreadsheet_id: string; tabs: LeadTab[]; leads: number; last_synced_at: string | null; status: "ok" | "error" | "never" }[];
  other: { key: string; label: string; spreadsheet_id: string; every: string; rows: number; rows_label: string; last_synced_at: string | null; latest_data: string | null; status: "ok" | "never"; unmatched: string[] }[];
}

const STATUS_PILL: Record<string, string> = {
  ok: "bg-blue-500/10 text-blue-400 border border-blue-500/20",
  error: "bg-rose-500/10 text-rose-400 border border-rose-500/20",
  never: "bg-zinc-500/10 text-zinc-400 border border-zinc-500/20",
};
const SYNC_BTN = "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-semibold shadow-md disabled:opacity-50 transition-all cursor-pointer";
const titleCase = (name: string) => name.charAt(0) + name.slice(1).toLowerCase();
// What each sheet is, shown under its name.
const ABOUT_SOURCE: [string, string][] = [
  ["daily store tracker", "Social media, WhatsApp chats and Google rating per store"],
  ["dashboard sheet", "Store list, store staff and Google reviews"],
  ["operations sheet", "Older daily store form, used only for days the new form lacks"],
];
const about = (label: string) => ABOUT_SOURCE.find(([k]) => label.toLowerCase().includes(k))?.[1];
const ABOUT_STORE_SHEET: Record<string, string> = {
  walkins: "Daily walk-in count per store",
  "daily-form": "What each store fills in every day: calls, appointments, walk-ins, sales",
};
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "Never synced");

export default function DataSync() {
  const queryClient = useQueryClient();
  const { data: sources, isLoading } = useQuery({ queryKey: ["sync-sources"], queryFn: () => api.get<any[]>("/sync/sources") });

  // Sheets that sync on their own schedule: team leaders' lead sheets, walk-ins, the stores' daily form.
  const { data: background } = useQuery({ queryKey: ["sync-background"], queryFn: () => api.get<BackgroundSheets>("/sync/background-sheets"), refetchInterval: 60_000 });
  const backgroundSync = useMutation({
    mutationFn: (key: string) => api.post<{ ok: boolean; message?: string | null }>(`/sync/background-sheets/${key}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sync-background"] }),
  });

  // All six lead sheets sync together, so `row` marks which button shows the spinner.
  const [syncingRow, setSyncingRow] = useState<string | null>(null);
  const syncButton = (key: string, row: string) => (
    <button onClick={() => { setSyncingRow(row); backgroundSync.mutate(key); }} disabled={backgroundSync.isPending} className={SYNC_BTN}>
      {backgroundSync.isPending && syncingRow === row ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
      <span>Sync Now</span>
    </button>
  );

  const syncMutation = useMutation({
    mutationFn: (id: number) => api.post(`/sync/manual/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sync-sources"] }),
  });

  return (
    <ErrorBoundary>
      <div className="space-y-6">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <Database className="text-[var(--accent-blue)]" size={22} />
            Google Sheets Data Sync
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            Manage live spreadsheet synchronization sources and automated data pipelines
          </p>
        </div>

        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 space-y-4">
          <div className="p-3.5 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] flex items-center gap-3">
            <Database size={20} className="text-[var(--accent-blue)] shrink-0" />
            <p className="text-xs text-[var(--text-muted)]">
              Automated sheet syncing runs on background schedules. You can manually trigger an instant sync using the action buttons below.
            </p>
          </div>

          {isLoading ? (
            <TableSkeleton rows={3} cols={4} />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left border-collapse">
                <thead>
                  <tr className="text-[var(--text-muted)] text-xs uppercase tracking-wider border-b border-[var(--border-subtle)]">
                    <th className="py-3 px-4 font-semibold">Sheet Source</th>
                    <th className="py-3 px-4 font-semibold">Sync Status</th>
                    <th className="py-3 px-4 font-semibold">Last Synced</th>
                    <th className="py-3 px-4 font-semibold text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border-subtle)]">
                  {(!sources || sources.length === 0) ? (
                    <tr>
                      <td colSpan={4} className="py-8 text-center text-xs text-[var(--text-muted)]">
                        No Google Sheets sources configured yet.
                      </td>
                    </tr>
                  ) : (
                    sources.map((s: any) => (
                      <tr key={s.id} className="hover:bg-[var(--bg-card-hover)] transition-colors">
                        <td className="py-3.5 px-4">
                          <p className="font-semibold text-white">{s.label}</p>
                          {about(s.label) && <p className="text-xs text-[var(--text-secondary)]">{about(s.label)}</p>}
                          <p className="text-xs text-[var(--text-muted)] font-mono truncate max-w-xs">{s.spreadsheet_id}</p>
                        </td>
                        <td className="py-3.5 px-4">
                          <div className="flex items-center gap-2">
                            <span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${
                              s.is_enabled ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-zinc-500/10 text-zinc-400 border border-zinc-500/20"
                            }`}>
                              {s.is_enabled ? "Active" : "Disabled"}
                            </span>
                            {s.last_sync_status && (
                              <span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${
                                s.last_sync_status === "error" ? "bg-rose-500/10 text-rose-400 border border-rose-500/20" : "bg-blue-500/10 text-blue-400 border border-blue-500/20"
                              }`}>
                                {s.last_sync_status}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="py-3.5 px-4 text-xs text-[var(--text-secondary)] font-medium">
                          {s.last_synced_at ? new Date(s.last_synced_at).toLocaleString() : "Never Synced"}
                        </td>
                        <td className="py-3.5 px-4 text-right">
                          <button
                            onClick={() => syncMutation.mutate(s.id)}
                            disabled={syncMutation.isPending}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-semibold shadow-md disabled:opacity-50 transition-all cursor-pointer"
                          >
                            {syncMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                            <span>Sync Now</span>
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                  {background?.lead_sheets.map((sh) => (
                    <tr key={sh.spreadsheet_id} className="hover:bg-[var(--bg-card-hover)] transition-colors">
                      <td className="py-3.5 px-4">
                        <p className="font-semibold text-white">Lead sheet · {titleCase(sh.team_leader)}</p>
                        <p className="text-xs text-[var(--text-secondary)]">
                          Team leader's leads for {sh.tabs.map((t) => t.name).join(", ")} · {sh.leads.toLocaleString("en-IN")} leads
                        </p>
                        <p className="text-xs text-[var(--text-muted)] font-mono truncate max-w-xs">{sh.spreadsheet_id}</p>
                      </td>
                      <td className="py-3.5 px-4"><span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${STATUS_PILL[sh.status]}`}>{sh.status === "never" ? "not synced yet" : sh.status}</span></td>
                      <td className="py-3.5 px-4 text-xs text-[var(--text-secondary)] font-medium">{when(sh.last_synced_at)}</td>
                      <td className="py-3.5 px-4 text-right">{syncButton("leads", sh.spreadsheet_id)}</td>
                    </tr>
                  ))}
                  {background?.other.map((o) => (
                    <tr key={o.key} className="hover:bg-[var(--bg-card-hover)] transition-colors">
                      <td className="py-3.5 px-4">
                        <p className="font-semibold text-white">{o.label}</p>
                        <p className="text-xs text-[var(--text-secondary)]">{ABOUT_STORE_SHEET[o.key]}</p>
                        <p className="text-xs text-[var(--text-muted)] font-mono truncate max-w-xs">{o.spreadsheet_id}</p>
                        {o.unmatched.length > 0 && <p className="text-xs text-rose-400">No store for: {o.unmatched.join(", ")}</p>}
                      </td>
                      <td className="py-3.5 px-4"><span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${STATUS_PILL[o.status]}`}>{o.status === "never" ? "not synced yet" : o.status}</span></td>
                      <td className="py-3.5 px-4 text-xs text-[var(--text-secondary)] font-medium">{when(o.last_synced_at)}</td>
                      <td className="py-3.5 px-4 text-right">{syncButton(o.key, o.key)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

      </div>
    </ErrorBoundary>
  );
}
