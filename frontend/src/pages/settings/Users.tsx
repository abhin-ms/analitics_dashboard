import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useToast } from "@/components/shared/Toast";
import { useMemo, useState } from "react";
import { Users, Plus, Trash2, ShieldCheck, UserCheck, Edit3, Save, X, Eye, EyeOff, KeyRound, AlertTriangle, Search } from "lucide-react";

const NONE = "none"; // filter value: store / team leader not set
const EMPTY_FILTERS = { q: "", role: "", store: "", tl: "", status: "" };
const ctl = "px-3 py-2 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none focus:border-[var(--accent-blue)]";

const EMPTY_FORM = { name: "", email: "", password: "", role_id: "", store_ids: [] as number[], store_id: "", team_leader_id: "" };

// Which store/manager control (if any) a role should show in the create/edit form.
function roleFieldKind(roleName: string): "none" | "tl-note" | "rm-multi" | "single" {
  if (roleName === "Regional Manager" || roleName === "Store Owner") return "rm-multi";
  if (roleName === "Telecaller" || roleName === "Salesperson" || roleName === "Store Staff") return "single";
  if (roleName === "Team Leader") return "tl-note";
  return "none";
}

export default function UserManagement() {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState({ name: "", email: "", role_id: 0, is_active: true, store_ids: [] as number[], store_id: "", team_leader_id: "" });
  const [resetModalId, setResetModalId] = useState<number | null>(null);
  const [resetModalName, setResetModalName] = useState("");
  const [resetPassword, setResetPassword] = useState("");
  const [showResetPw, setShowResetPw] = useState(false);
  const [resetSuccess, setResetSuccess] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState<{ id: number; name: string } | null>(null);
  const queryClient = useQueryClient();
  const toast = useToast();

  const { data: users, isLoading } = useQuery({ queryKey: ["users"], queryFn: () => api.get<any[]>("/users/") });
  const { data: roles } = useQuery({ queryKey: ["roles"], queryFn: () => api.get<any[]>("/roles/") });
  const { data: stores } = useQuery({ queryKey: ["stores"], queryFn: () => api.get<any[]>("/stores/") });

  const roleNameById = (id: number | string) => (roles || []).find((r: any) => r.id === Number(id))?.name || "";
  const teamLeaders = (users || []).filter((u: any) => u.role_name === "Team Leader");
  const storeName = (id: number) => stores?.find((s: any) => s.id === id)?.name || `Store #${id}`;
  const userName = (id: number) => (users || []).find((x: any) => x.id === id)?.name || "";

  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const setF = (k: keyof typeof EMPTY_FILTERS, v: string) => setFilters((p) => ({ ...p, [k]: v }));
  const filtering = Object.values(filters).some(Boolean);
  const storesOf = (u: any): number[] =>
    [...(u.store_id ? [u.store_id] : []), ...((u.store_ids || []) as number[]).filter((x) => x !== u.store_id)];
  const filtered = useMemo(() => {
    const q = filters.q.trim().toLowerCase();
    return (users || []).filter((u: any) => {
      if (q && !`${u.name} ${u.email}`.toLowerCase().includes(q)) return false;
      if (filters.role && u.role_name !== filters.role) return false;
      if (filters.status && (filters.status === "active") !== !!u.is_active) return false;
      if (filters.store) {
        const ids = storesOf(u);
        if (filters.store === NONE ? ids.length > 0 : !ids.includes(Number(filters.store))) return false;
      }
      if (filters.tl && (filters.tl === NONE ? !!u.team_leader_id : u.team_leader_id !== Number(filters.tl))) return false;
      return true;
    });
  }, [users, filters]);
  const roleCounts = useMemo(() => {
    const c: Record<string, number> = {};
    (users || []).forEach((u: any) => { c[u.role_name] = (c[u.role_name] || 0) + 1; });
    return Object.entries(c).sort((a, b) => b[1] - a[1]);
  }, [users]);

  // What the Stores column says for a user.
  const storeSummary = (u: any) => {
    const ids = storesOf(u);
    if (u.role_name === "Team Leader") return "See Branch Assignment";
    if (u.role_name === "Regional Manager" || u.role_name === "Store Owner") return ids.length ? `${ids.length} store${ids.length > 1 ? "s" : ""}` : "—";
    if (!ids.length) return "—";
    return storeName(ids[0]) + (ids.length > 1 ? ` +${ids.length - 1} more` : "");
  };

  const createMutation = useMutation({
    mutationFn: (data: any) => api.post("/users/", data),
    onSuccess: (_: any, vars: any) => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setShowForm(false);
      setForm(EMPTY_FORM);
      toast.success(`User "${vars.name}" created`);
    },
    onError: (err: any) => toast.error(err.message || "Failed to create user"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: any }) => api.put(`/users/${id}`, data),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["users"] }); setEditingId(null); toast.success("User updated"); },
    onError: (err: any) => toast.error(err.message || "Failed to update user"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.del(`/users/${id}`),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["users"] }); setDeleteConfirm(null); toast.success("User deleted"); },
    onError: (err: any) => { toast.error(err.message || "Failed to delete user"); setDeleteConfirm(null); },
  });

  const resetPwMutation = useMutation({
    mutationFn: ({ id, password }: { id: number; password: string }) =>
      api.post(`/users/${id}/reset-password`, { new_password: password }),
    onSuccess: (_: any, vars: { id: number; password: string }) => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setResetSuccess(`Password updated for ${resetModalName}`);
      setResetPassword("");
      setShowResetPw(false);
      setTimeout(() => { setResetModalId(null); setResetSuccess(""); }, 1500);
    },
  });

  const startEdit = (u: any) => {
    setEditingId(u.id);
    setEditForm({
      name: u.name,
      email: u.email,
      role_id: u.role_id,
      is_active: u.is_active,
      store_ids: u.store_ids || [],
      store_id: u.store_id ? String(u.store_id) : "",
      team_leader_id: u.team_leader_id ? String(u.team_leader_id) : "",
    });
  };

  const openResetModal = (u: any) => {
    setResetModalId(u.id);
    setResetModalName(u.name);
    setResetPassword("");
    setShowResetPw(false);
    setResetSuccess("");
  };

  const handleUpdate = () => {
    if (!editingId) return;
    const kind = roleFieldKind(roleNameById(editForm.role_id));
    updateMutation.mutate({
      id: editingId,
      data: {
        name: editForm.name,
        email: editForm.email,
        role_id: editForm.role_id,
        is_active: editForm.is_active,
        store_ids: kind === "rm-multi" || roleNameById(editForm.role_id) === "Telecaller" ? editForm.store_ids : [],
        store_id: kind === "single" && editForm.store_id ? Number(editForm.store_id) : null,
        team_leader_id: kind === "single" && editForm.team_leader_id ? Number(editForm.team_leader_id) : null,
      },
    });
  };

  return (
    <ErrorBoundary>
      <div className="space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-white tracking-tight flex items-center gap-2">
              <Users className="text-[var(--accent-blue)]" size={22} />
              User Management
            </h2>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              Manage system access accounts, roles, and assigned stores
            </p>
          </div>

          <button
            onClick={() => setShowForm(!showForm)}
            className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-semibold shadow-lg shadow-blue-500/20 transition-all cursor-pointer shrink-0"
          >
            <Plus size={16} />
            <span>{showForm ? "Cancel" : "Create User"}</span>
          </button>
        </div>

        {showForm && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const kind = roleFieldKind(roleNameById(form.role_id));
              createMutation.mutate({
                name: form.name, email: form.email, password: form.password,
                role_id: Number(form.role_id),
                store_ids: kind === "rm-multi" || roleNameById(form.role_id) === "Telecaller" ? form.store_ids : [],
                store_id: kind === "single" && form.store_id ? Number(form.store_id) : null,
                team_leader_id: kind === "single" && form.team_leader_id ? Number(form.team_leader_id) : null,
              });
            }}
            className="bg-[var(--bg-card)] border border-[var(--border-subtle)] rounded-2xl p-5 shadow-xl space-y-3"
          >
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              <input
                placeholder="Name *"
                value={form.name}
                onChange={(e) => setForm(p => ({...p, name: e.target.value}))}
                required
                className="px-3.5 py-2.5 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none"
              />
              <input
                type="email"
                placeholder="Email *"
                // not the admin's own saved login: this is a new user
                autoComplete="off"
                name="new-user-email"
                value={form.email}
                onChange={(e) => setForm(p => ({...p, email: e.target.value}))}
                required
                className="px-3.5 py-2.5 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none"
              />
              <input
                type="password"
                placeholder="Password *"
                autoComplete="new-password"
                name="new-user-password"
                value={form.password}
                onChange={(e) => setForm(p => ({...p, password: e.target.value}))}
                required
                className="px-3.5 py-2.5 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none"
              />
              <select
                value={form.role_id}
                onChange={(e) => setForm(p => ({...p, role_id: e.target.value, store_ids: [], store_id: "", team_leader_id: ""}))}
                required
                className="px-3.5 py-2.5 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none"
              >
                <option value="">Select Role *</option>
                {(roles || []).map((r: any) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </div>

            <RoleScopedFields
              roleName={roleNameById(form.role_id)}
              stores={stores || []}
              teamLeaders={teamLeaders}
              storeIds={form.store_ids}
              storeId={form.store_id}
              teamLeaderId={form.team_leader_id}
              onStoreIdsChange={(ids) => setForm(p => ({...p, store_ids: ids}))}
              onStoreIdChange={(id) => setForm(p => ({...p, store_id: id}))}
              onTeamLeaderIdChange={(id) => setForm(p => ({...p, team_leader_id: id}))}
            />

            <button
              type="submit"
              disabled={createMutation.isPending}
              className="w-full px-4 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold transition-all disabled:opacity-50 cursor-pointer"
            >
              {createMutation.isPending ? "Creating..." : "Create User Account"}
            </button>
          </form>
        )}

        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-3 sm:p-4 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-[minmax(0,1.6fr)_repeat(4,minmax(0,1fr))] gap-2">
            <div className="relative sm:col-span-2 lg:col-span-1">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input id="user-search" value={filters.q} onChange={(e) => setF("q", e.target.value)} placeholder="Search name or email"
                aria-label="Search users" className={`${ctl} w-full pl-8`} />
            </div>
            <select id="user-role" aria-label="Role" value={filters.role} onChange={(e) => setF("role", e.target.value)} className={ctl}>
              <option value="">All roles</option>
              {(roles || []).map((r: any) => <option key={r.id} value={r.name}>{r.name}</option>)}
            </select>
            <select id="user-store" aria-label="Store" value={filters.store} onChange={(e) => setF("store", e.target.value)} className={ctl}>
              <option value="">All stores</option>
              <option value={NONE}>No store set</option>
              {(stores || []).map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <select id="user-tl" aria-label="Reports to" value={filters.tl} onChange={(e) => setF("tl", e.target.value)} className={ctl}>
              <option value="">Any team leader</option>
              <option value={NONE}>No team leader</option>
              {teamLeaders.map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            <select id="user-status" aria-label="Status" value={filters.status} onChange={(e) => setF("status", e.target.value)} className={ctl}>
              <option value="">Active and inactive</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {roleCounts.map(([name, n]) => (
              <button key={name} type="button" onClick={() => setF("role", filters.role === name ? "" : name)}
                className={`px-2.5 py-1 rounded-full text-[11px] font-semibold border cursor-pointer transition-colors ${filters.role === name
                  ? "bg-[var(--accent-blue)] border-[var(--accent-blue)] text-white"
                  : "bg-[var(--bg-primary)] border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-white"}`}>
                {name} <span className="opacity-70">{n}</span>
              </button>
            ))}
            <span className="ml-auto text-xs text-[var(--text-muted)]">
              {filtered.length} of {users?.length || 0} users
              {filtering && (
                <button type="button" onClick={() => setFilters(EMPTY_FILTERS)} className="ml-2 text-[var(--accent-blue)] hover:underline cursor-pointer">
                  Clear filters
                </button>
              )}
            </span>
          </div>
        </div>

        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-2 sm:p-4 overflow-hidden">
          {isLoading ? (
            <TableSkeleton />
          ) : filtered.length === 0 ? (
            <p className="py-10 text-center text-sm text-[var(--text-muted)]">
              No users match these filters.{" "}
              <button type="button" onClick={() => setFilters(EMPTY_FILTERS)} className="text-[var(--accent-blue)] hover:underline cursor-pointer">Clear filters</button>
            </p>
          ) : (
            <>
            {/* Phones and tablets: one card per user; editing opens inside the card */}
            <div className="lg:hidden divide-y divide-[var(--border-subtle)]">
              {filtered.map((u: any) => (
                <div key={u.id} className="p-3">
                  {editingId === u.id ? (
                    <div className="space-y-2">
                      <input aria-label="Name" value={editForm.name} onChange={(e) => setEditForm(p => ({...p, name: e.target.value}))} className={`${ctl} w-full`} />
                      <input aria-label="Email" type="email" value={editForm.email} onChange={(e) => setEditForm(p => ({...p, email: e.target.value}))} className={`${ctl} w-full`} />
                      <select aria-label="Role" value={editForm.role_id}
                        onChange={(e) => setEditForm(p => ({...p, role_id: Number(e.target.value), store_ids: [], store_id: "", team_leader_id: ""}))}
                        className={`${ctl} w-full`}>
                        {(roles || []).map((r: any) => <option key={r.id} value={r.id}>{r.name}</option>)}
                      </select>
                      <RoleScopedFields
                        compact
                        roleName={roleNameById(editForm.role_id)}
                        stores={stores || []}
                        teamLeaders={teamLeaders}
                        storeIds={editForm.store_ids}
                        storeId={editForm.store_id}
                        teamLeaderId={editForm.team_leader_id}
                        onStoreIdsChange={(ids) => setEditForm(p => ({...p, store_ids: ids}))}
                        onStoreIdChange={(id) => setEditForm(p => ({...p, store_id: id}))}
                        onTeamLeaderIdChange={(id) => setEditForm(p => ({...p, team_leader_id: id}))}
                      />
                      <div className="flex items-center gap-2 pt-1">
                        <button type="button" aria-label="Active" onClick={() => setEditForm(p => ({...p, is_active: !p.is_active}))}
                          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors cursor-pointer ${editForm.is_active ? "bg-emerald-500" : "bg-zinc-600"}`}>
                          <span className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${editForm.is_active ? "translate-x-4.5" : "translate-x-0.5"}`} />
                        </button>
                        <span className="text-xs text-[var(--text-secondary)]">{editForm.is_active ? "Active" : "Inactive"}</span>
                        <div className="ml-auto flex gap-2">
                          <button onClick={() => setEditingId(null)}
                            className="px-3 py-2 rounded-lg text-xs font-semibold border border-[var(--border-subtle)] text-[var(--text-secondary)] cursor-pointer">Cancel</button>
                          <button onClick={handleUpdate} disabled={updateMutation.isPending}
                            className="px-3 py-2 rounded-lg text-xs font-semibold bg-emerald-600 text-white cursor-pointer disabled:opacity-50">
                            {updateMutation.isPending ? "Saving..." : "Save"}
                          </button>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-start gap-3">
                      <div className="h-9 w-9 rounded-full bg-[var(--accent-blue)]/15 border border-[var(--accent-blue)]/30 flex items-center justify-center text-[var(--accent-blue)] font-bold text-xs shrink-0">
                        {u.name ? u.name.charAt(0).toUpperCase() : <UserCheck size={15} />}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="font-semibold text-white truncate">{u.name}</span>
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] border border-[var(--accent-blue)]/20">{u.role_name}</span>
                          {!u.is_active && <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-zinc-500/10 text-zinc-400 border border-zinc-500/20">Inactive</span>}
                        </div>
                        <p className="text-xs text-[var(--text-secondary)] truncate mt-0.5">{u.email}</p>
                        <p className="text-[11px] text-[var(--text-muted)] mt-0.5">
                          {storeSummary(u)}{u.team_leader_id ? ` · Reports to ${userName(u.team_leader_id)}` : ""}
                        </p>
                      </div>
                      <div className="flex items-center gap-0.5 shrink-0">
                        <button onClick={() => openResetModal(u)} className="p-2 rounded-lg text-amber-400 hover:bg-amber-500/10 cursor-pointer" title="Reset Password" aria-label="Reset password"><KeyRound size={16} /></button>
                        <button onClick={() => startEdit(u)} className="p-2 rounded-lg text-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/10 cursor-pointer" title="Edit User" aria-label="Edit user"><Edit3 size={16} /></button>
                        <button onClick={() => setDeleteConfirm({ id: u.id, name: u.name })} className="p-2 rounded-lg text-rose-400 hover:bg-rose-500/10 cursor-pointer" title="Delete User" aria-label="Delete user"><Trash2 size={16} /></button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>

            {/* Laptops: the table, edited in place */}
            <div className="hidden lg:block overflow-x-auto">
              <table className="w-full text-sm text-left border-collapse">
                <thead>
                  <tr className="text-[var(--text-muted)] text-xs uppercase tracking-wider border-b border-[var(--border-subtle)]">
                    <th className="py-3 px-4 font-semibold">User</th>
                    <th className="py-3 px-4 font-semibold">Email</th>
                    <th className="py-3 px-4 font-semibold">Role</th>
                    <th className="py-3 px-4 font-semibold text-right">Stores</th>
                    <th className="py-3 px-4 font-semibold">Status</th>
                    <th className="py-3 px-4 font-semibold text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border-subtle)]">
                  {filtered.map((u: any) => (
                    <tr key={u.id} className="hover:bg-[var(--bg-card-hover)] transition-colors">
                      <td className="py-3 px-4 font-semibold text-white">
                        {editingId === u.id ? (
                          <input
                            value={editForm.name}
                            onChange={(e) => setEditForm(p => ({...p, name: e.target.value}))}
                            className="w-full px-2.5 py-1.5 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none focus:border-[var(--accent-blue)]"
                          />
                        ) : (
                          <div className="flex items-center gap-2.5">
                            <div className="h-8 w-8 rounded-full bg-[var(--accent-blue)]/15 border border-[var(--accent-blue)]/30 flex items-center justify-center text-[var(--accent-blue)] font-bold text-xs shrink-0">
                              {u.name ? u.name.charAt(0).toUpperCase() : <UserCheck size={15} />}
                            </div>
                            <span>{u.name}</span>
                          </div>
                        )}
                      </td>

                      <td className="py-3 px-4 text-xs text-[var(--text-secondary)]">
                        {editingId === u.id ? (
                          <input
                            type="email"
                            value={editForm.email}
                            onChange={(e) => setEditForm(p => ({...p, email: e.target.value}))}
                            className="w-full px-2.5 py-1.5 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none focus:border-[var(--accent-blue)]"
                          />
                        ) : (
                          u.email
                        )}
                      </td>

                      <td className="py-3 px-4">
                        {editingId === u.id ? (
                          <select
                            value={editForm.role_id}
                            onChange={(e) => setEditForm(p => ({...p, role_id: Number(e.target.value), store_ids: [], store_id: "", team_leader_id: ""}))}
                            className="w-full px-2.5 py-1.5 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none focus:border-[var(--accent-blue)]"
                          >
                            {(roles || []).map((r: any) => <option key={r.id} value={r.id}>{r.name}</option>)}
                          </select>
                        ) : (
                          <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] border border-[var(--accent-blue)]/20 capitalize">
                            {u.role_name}
                          </span>
                        )}
                      </td>

                      <td className="py-3 px-4 text-xs font-medium text-[var(--text-secondary)] min-w-[200px]">
                        {editingId === u.id ? (
                          <RoleScopedFields
                            compact
                            roleName={roleNameById(editForm.role_id)}
                            stores={stores || []}
                            teamLeaders={teamLeaders}
                            storeIds={editForm.store_ids}
                            storeId={editForm.store_id}
                            teamLeaderId={editForm.team_leader_id}
                            onStoreIdsChange={(ids) => setEditForm(p => ({...p, store_ids: ids}))}
                            onStoreIdChange={(id) => setEditForm(p => ({...p, store_id: id}))}
                            onTeamLeaderIdChange={(id) => setEditForm(p => ({...p, team_leader_id: id}))}
                          />
                        ) : (
                          <span className="block text-right">
                            {storeSummary(u)}
                            {u.team_leader_id ? <span className="block text-[11px] text-[var(--text-muted)]">Reports to {userName(u.team_leader_id)}</span> : null}
                          </span>
                        )}
                      </td>

                      <td className="py-3 px-4">
                        {editingId === u.id ? (
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={() => setEditForm(p => ({...p, is_active: !p.is_active}))}
                              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors cursor-pointer ${
                                editForm.is_active ? "bg-emerald-500" : "bg-zinc-600"
                              }`}
                            >
                              <span className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
                                editForm.is_active ? "translate-x-4.5" : "translate-x-0.5"
                              }`} />
                            </button>
                            <span className="text-xs text-[var(--text-secondary)]">{editForm.is_active ? "Active" : "Inactive"}</span>
                          </div>
                        ) : (
                          <span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${
                            u.is_active ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-zinc-500/10 text-zinc-400 border border-zinc-500/20"
                          }`}>
                            {u.is_active ? "Active" : "Inactive"}
                          </span>
                        )}
                      </td>

                      <td className="py-3 px-4 text-right">
                        {editingId === u.id ? (
                          <div className="flex items-center justify-end gap-1">
                            <button
                              onClick={handleUpdate}
                              disabled={updateMutation.isPending}
                              className="p-1.5 rounded-lg bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-colors cursor-pointer disabled:opacity-50"
                              title="Save"
                            >
                              <Save size={15} />
                            </button>
                            <button
                              onClick={() => setEditingId(null)}
                              className="p-1.5 rounded-lg bg-red-500/15 text-red-400 hover:bg-red-500/25 transition-colors cursor-pointer"
                              title="Cancel"
                            >
                              <X size={15} />
                            </button>
                          </div>
                        ) : (
                          <div className="flex items-center justify-end gap-1">
                            <button
                              onClick={() => openResetModal(u)}
                              className="p-1.5 rounded-lg text-amber-400 hover:bg-amber-500/10 transition-colors cursor-pointer"
                              title="Reset Password"
                            >
                              <KeyRound size={15} />
                            </button>
                            <button
                              onClick={() => startEdit(u)}
                              className="p-1.5 rounded-lg text-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/10 transition-colors cursor-pointer"
                              title="Edit User"
                            >
                              <Edit3 size={15} />
                            </button>
                            <button
                              onClick={() => setDeleteConfirm({ id: u.id, name: u.name })}
                              className="p-1.5 rounded-lg text-rose-400 hover:bg-rose-500/10 transition-colors cursor-pointer"
                              title="Delete User"
                            >
                              <Trash2 size={15} />
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            </>
          )}
        </div>

        {resetModalId && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ backgroundColor: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)" }}
            onClick={(e) => { if (e.target === e.currentTarget) { setResetModalId(null); setResetSuccess(""); } }}
          >
            <div
              className="w-full max-w-md rounded-2xl border border-[var(--border-subtle)] shadow-2xl overflow-hidden"
              style={{ background: "var(--bg-card)" }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center gap-3 px-6 py-4 border-b border-[var(--border-subtle)]">
                <div className="h-10 w-10 rounded-xl bg-amber-500/15 border border-amber-500/25 flex items-center justify-center">
                  <KeyRound size={20} className="text-amber-400" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white">Reset Password</h3>
                  <p className="text-xs text-[var(--text-muted)]">for {resetModalName}</p>
                </div>
                <button
                  onClick={() => { setResetModalId(null); setResetSuccess(""); }}
                  className="ml-auto p-1.5 rounded-lg hover:bg-white/5 text-[var(--text-muted)] hover:text-white transition-colors cursor-pointer"
                >
                  <X size={16} />
                </button>
              </div>

              <div className="px-6 py-5">
                {resetSuccess ? (
                  <div className="text-center py-4">
                    <div className="h-12 w-12 rounded-full bg-emerald-500/15 border border-emerald-500/25 flex items-center justify-center mx-auto mb-3">
                      <ShieldCheck size={24} className="text-emerald-400" />
                    </div>
                    <p className="text-sm font-semibold text-emerald-400">{resetSuccess}</p>
                  </div>
                ) : (
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (resetPassword.length < 6) return;
                      resetPwMutation.mutate({ id: resetModalId, password: resetPassword });
                    }}
                  >
                    <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-2">
                      New Password
                    </label>
                    <div className="relative mb-1">
                      <KeyRound size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
                      <input
                        type={showResetPw ? "text" : "password"}
                        // "new-password": without it the browser fills in the admin's own saved
                        // password here, and the user's password becomes that + what was typed
                        autoComplete="new-password"
                        name="reset-new-password"
                        value={resetPassword}
                        onChange={(e) => setResetPassword(e.target.value)}
                        placeholder="Enter new password (min 6 chars)"
                        required
                        minLength={6}
                        autoFocus
                        className="w-full pl-9 pr-10 py-2.5 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent-blue)]"
                      />
                      <button
                        type="button"
                        onClick={() => setShowResetPw(!showResetPw)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-white cursor-pointer"
                      >
                        {showResetPw ? <EyeOff size={15} /> : <Eye size={15} />}
                      </button>
                    </div>
                    {resetPassword && resetPassword.length < 6 && (
                      <p className="text-xs text-amber-400 mt-1">Must be at least 6 characters</p>
                    )}

                    {resetPwMutation.isError && (
                      <p className="text-xs text-red-400 mt-2">
                        {(resetPwMutation.error as any)?.detail || "Failed to reset password"}
                      </p>
                    )}

                    <div className="flex gap-2 mt-5">
                      <button
                        type="button"
                        onClick={() => { setResetModalId(null); setResetSuccess(""); }}
                        className="flex-1 px-4 py-2.5 rounded-xl border border-[var(--border-subtle)] text-xs font-semibold text-[var(--text-secondary)] hover:bg-white/5 transition-colors cursor-pointer"
                      >
                        Cancel
                      </button>
                      <button
                        type="submit"
                        disabled={resetPwMutation.isPending || resetPassword.length < 6}
                        className="flex-1 px-4 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-white text-xs font-semibold shadow-lg shadow-amber-500/20 transition-all disabled:opacity-40 cursor-pointer"
                      >
                        {resetPwMutation.isPending ? "Updating..." : "Update Password"}
                      </button>
                    </div>
                  </form>
                )}
              </div>
            </div>
          </div>
        )}

        {deleteConfirm && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ backgroundColor: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)" }}
            onClick={(e) => { if (e.target === e.currentTarget) setDeleteConfirm(null); }}
          >
            <div
              className="w-full max-w-md rounded-2xl border border-[var(--border-subtle)] shadow-2xl overflow-hidden"
              style={{ background: "var(--bg-card)" }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center gap-3 px-6 py-4 border-b border-[var(--border-subtle)]">
                <div className="h-10 w-10 rounded-xl bg-rose-500/15 border border-rose-500/25 flex items-center justify-center">
                  <AlertTriangle size={20} className="text-rose-400" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white">Delete User</h3>
                  <p className="text-xs text-[var(--text-muted)]">{deleteConfirm.name}</p>
                </div>
                <button
                  onClick={() => setDeleteConfirm(null)}
                  className="ml-auto p-1.5 rounded-lg hover:bg-white/5 text-[var(--text-muted)] hover:text-white transition-colors cursor-pointer"
                >
                  <X size={16} />
                </button>
              </div>
              <div className="px-6 py-5">
                <p className="text-sm text-[var(--text-secondary)]">
                  Are you sure you want to delete <span className="font-semibold text-white">{deleteConfirm.name}</span>?
                  Any stores they lead will be reassigned to "Unassigned", and their other activity records will be kept
                  but detached from their account. This cannot be undone.
                </p>
                <div className="flex gap-2 mt-5">
                  <button
                    type="button"
                    onClick={() => setDeleteConfirm(null)}
                    className="flex-1 px-4 py-2.5 rounded-xl border border-[var(--border-subtle)] text-xs font-semibold text-[var(--text-secondary)] hover:bg-white/5 transition-colors cursor-pointer"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteMutation.mutate(deleteConfirm.id)}
                    disabled={deleteMutation.isPending}
                    className="flex-1 px-4 py-2.5 rounded-xl bg-rose-600 hover:bg-rose-500 text-white text-xs font-semibold shadow-lg shadow-rose-500/20 transition-all disabled:opacity-50 cursor-pointer"
                  >
                    {deleteMutation.isPending ? "Deleting..." : "Delete User"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
}

function RoleScopedFields({
  roleName, stores, teamLeaders, storeIds, storeId, teamLeaderId,
  onStoreIdsChange, onStoreIdChange, onTeamLeaderIdChange, compact,
}: {
  roleName: string;
  stores: any[];
  teamLeaders: any[];
  storeIds: number[];
  storeId: string;
  teamLeaderId: string;
  onStoreIdsChange: (ids: number[]) => void;
  onStoreIdChange: (id: string) => void;
  onTeamLeaderIdChange: (id: string) => void;
  compact?: boolean;
}) {
  const kind = roleFieldKind(roleName);
  const inputCls = "px-2.5 py-1.5 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none focus:border-[var(--accent-blue)]";

  if (kind === "none") return null;

  if (kind === "tl-note") {
    return (
      <p className="text-xs text-[var(--text-muted)] italic">
        Assign this leader's branches from Settings &rarr; Team Leaders &amp; Branches after creating.
      </p>
    );
  }

  if (kind === "rm-multi") {
    const toggle = (id: number) => {
      onStoreIdsChange(storeIds.includes(id) ? storeIds.filter(x => x !== id) : [...storeIds, id]);
    };
    return (
      <div>
        <label className="block text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-1">
          Assigned Stores ({storeIds.length})
        </label>
        <div className={`grid ${compact ? "grid-cols-1" : "grid-cols-2 sm:grid-cols-3"} gap-1 max-h-32 overflow-y-auto p-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)]`}>
          {stores.map((s: any) => (
            <label key={s.id} className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)] cursor-pointer">
              <input type="checkbox" checked={storeIds.includes(s.id)} onChange={() => toggle(s.id)} />
              <span className="truncate">{s.name}</span>
            </label>
          ))}
        </div>
      </div>
    );
  }

  // kind === "single" (Telecaller / Salesperson / Store Staff)
  const extraStores = roleName === "Telecaller" ? stores.filter((s: any) => String(s.id) !== storeId) : [];
  return (
    <div className={compact ? "flex flex-col gap-1" : "space-y-2"}>
      <div className={compact ? "flex flex-col gap-1" : "grid grid-cols-1 sm:grid-cols-2 gap-3"}>
        <select value={storeId} onChange={(e) => {
          onStoreIdChange(e.target.value);
          onStoreIdsChange(storeIds.filter(x => String(x) !== e.target.value));
        }} className={inputCls}>
          <option value="">Store (optional)</option>
          {stores.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <select value={teamLeaderId} onChange={(e) => onTeamLeaderIdChange(e.target.value)} className={inputCls}>
          <option value="">Reports to (optional)</option>
          {teamLeaders.map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>
      {/* A telecaller who covers more stores gets (and sees) their leads too — never other stores' */}
      {extraStores.length > 0 && storeId && (
        <div>
          <label className="block text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-1">
            Also covers ({storeIds.length})
          </label>
          <div className={`grid ${compact ? "grid-cols-1" : "grid-cols-2 sm:grid-cols-3"} gap-1 max-h-28 overflow-y-auto p-2 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)]`}>
            {extraStores.map((s: any) => (
              <label key={s.id} className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)] cursor-pointer">
                <input type="checkbox" checked={storeIds.includes(s.id)}
                  onChange={() => onStoreIdsChange(storeIds.includes(s.id) ? storeIds.filter(x => x !== s.id) : [...storeIds, s.id])} />
                <span className="truncate">{s.name}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
