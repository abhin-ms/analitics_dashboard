import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { PhoneCall, Plus, Trash2, Users } from "lucide-react";

export default function SheetAssignments() {
  const [form, setForm] = useState({ user_id: "", sheet_tl_name: "" });
  const queryClient = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["sheet-assignments"],
    queryFn: () => api.get<any>("/tele-call-leads/sheet-assignments"),
  });
  const { data: users } = useQuery({ queryKey: ["users"], queryFn: () => api.get<any[]>("/users/") });

  const assignableUsers = (users || []).filter(
    (u: any) => u.role_name === "Team Leader" || u.role_name === "Telecaller"
  );

  const createMutation = useMutation({
    mutationFn: (body: { user_id: number; sheet_tl_name: string }) =>
      api.post("/tele-call-leads/sheet-assignments", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sheet-assignments"] });
      setForm({ user_id: "", sheet_tl_name: "" });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.del(`/tele-call-leads/sheet-assignments/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sheet-assignments"] }),
  });

  const assignments = data?.assignments || [];
  const sheets = data?.sheets || [];

  return (
    <ErrorBoundary>
      <div className="space-y-6">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
            <PhoneCall className="text-[var(--accent-blue)]" size={22} />
            Sheet Assignments
          </h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            Assign a Team Leader or Telecaller to a store's lead sheet (e.g. "Kochi", "Hitech City") —
            required before they can see or update any tele-calling leads at all.
          </p>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!form.user_id || !form.sheet_tl_name) return;
            createMutation.mutate({ user_id: Number(form.user_id), sheet_tl_name: form.sheet_tl_name });
          }}
          className="bg-[var(--bg-card)] border border-[var(--border-subtle)] rounded-2xl p-5 grid grid-cols-1 sm:grid-cols-3 gap-3"
        >
          <select
            value={form.user_id}
            onChange={(e) => setForm((p) => ({ ...p, user_id: e.target.value }))}
            required
            className="px-3.5 py-2.5 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none"
          >
            <option value="">Select Team Leader / Telecaller *</option>
            {assignableUsers.map((u: any) => (
              <option key={u.id} value={u.id}>{u.name} ({u.role_name})</option>
            ))}
          </select>
          <select
            value={form.sheet_tl_name}
            onChange={(e) => setForm((p) => ({ ...p, sheet_tl_name: e.target.value }))}
            required
            className="px-3.5 py-2.5 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none"
          >
            <option value="">Select Sheet *</option>
            {sheets.map((s: any) => (
              <option key={s.tl_name} value={s.tl_name}>{s.tl_name}{s.team_leader ? ` · ${s.team_leader}'s sheet` : ""}</option>
            ))}
          </select>
          <button
            type="submit"
            disabled={createMutation.isPending}
            className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-semibold shadow-lg shadow-blue-500/20 transition-all disabled:opacity-50"
          >
            <Plus size={16} />
            {createMutation.isPending ? "Assigning..." : "Assign"}
          </button>
        </form>

        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 sm:p-6 overflow-hidden">
          {isLoading ? (
            <TableSkeleton />
          ) : assignments.length === 0 ? (
            <div className="text-center py-10 text-sm text-[var(--text-muted)]">
              <Users size={28} className="mx-auto mb-2 opacity-50" />
              No sheet assignments yet
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left border-collapse">
                <thead>
                  <tr className="text-[var(--text-muted)] text-xs uppercase tracking-wider border-b border-[var(--border-subtle)]">
                    <th className="py-3 px-4 font-semibold">User</th>
                    <th className="py-3 px-4 font-semibold">Role</th>
                    <th className="py-3 px-4 font-semibold">Sheet</th>
                    <th className="py-3 px-4 font-semibold text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border-subtle)]">
                  {assignments.map((a: any) => (
                    <tr key={a.id} className="hover:bg-[var(--bg-card-hover)] transition-colors">
                      <td className="py-3 px-4">
                        <div className="font-medium text-white">{a.user_name}</div>
                        <div className="text-xs text-[var(--text-muted)]">{a.user_email}</div>
                      </td>
                      <td className="py-3 px-4">
                        <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] border border-[var(--accent-blue)]/20">
                          {a.role_name}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-[var(--text-secondary)]">{a.sheet_tl_name}</td>
                      <td className="py-3 px-4 text-right">
                        <button
                          onClick={() => deleteMutation.mutate(a.id)}
                          disabled={deleteMutation.isPending}
                          className="p-1.5 rounded-lg text-rose-400 hover:bg-rose-500/10 transition-colors disabled:opacity-50"
                          title="Remove assignment"
                        >
                          <Trash2 size={15} />
                        </button>
                      </td>
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
