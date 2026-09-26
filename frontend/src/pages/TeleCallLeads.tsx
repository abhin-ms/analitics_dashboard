import { useState, useCallback, useEffect, useMemo } from "react";
import { useAuthStore } from "@/lib/authStore";
import { api } from "@/lib/apiClient";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useSocketRefresh } from "../hooks/useSocketRefresh";
import {
  Phone, Users, ChevronDown, ChevronRight, Filter, RefreshCw,
  PhoneCall, PhoneOff, Clock, CalendarCheck, Ban,
  CheckCircle2, AlertCircle, Search, X, Save, UserPlus, Edit3,
} from "lucide-react";
import { DatePicker } from "@/components/shared/DatePicker";
import { PhoneActions } from "@/components/shared/PhoneActions";
import { STATUS_OPTIONS, STATUS_COLORS } from "@/features/crm/statusConfig";
import { openLead } from "@/features/crm/components/LeadDrawer";

interface Lead {
  id: number;
  lead_source: string;
  created_time: string;
  full_name: string;
  phone: string;
  email: string;
  person_calling: string;
  status: string;
  call_date: string;
  appointment_date: string;
  remarks: string;
  sale_amount: string;
  product: string;
  salesperson: string;
  sheet_tl_name: string;
}

interface TlGroup {
  total: number;
  status_counts: Record<string, number>;
  leads: Lead[];
}

interface Salesperson {
  id: number;
  name: string;
  email: string;
}

interface Telecaller {
  id: number;
  name: string;
  email: string;
  sheet: string;
}

// Status list and colours now come from the shared telecalling config
// (same values as before), so every page shows statuses identically.

const STATUS_ICONS: Record<string, React.ReactNode> = {
  "Call Not Connected": <PhoneOff size={14} />,
  "Call back later": <Clock size={14} />,
  "Not Interested": <Ban size={14} />,
  "Will Visit": <Phone size={14} />,
  "Appointment": <CalendarCheck size={14} />,
  "Sale Conversion": <CheckCircle2 size={14} />,
  "Wrong number": <AlertCircle size={14} />,
  "Unattended": <PhoneOff size={14} />,
};

export default function TeleCallLeads() {
  useSocketRefresh(["tele_call_leads"]);
  const { user } = useAuthStore();

  const [tlGroups, setTlGroups] = useState<Record<string, TlGroup>>({});
  const [total, setTotal] = useState(0);
  const [role, setRole] = useState("");
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [expandedTl, setExpandedTl] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [editingLead, setEditingLead] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<Partial<Lead>>({});
  const [saving, setSaving] = useState(false);
  const [salespersons, setSalespersons] = useState<Salesperson[]>([]);
  const [telecallers, setTelecallers] = useState<Telecaller[]>([]);
  const [quickUpdating, setQuickUpdating] = useState<number | null>(null);
  const [showAddTelecaller, setShowAddTelecaller] = useState(false);
  const [newTelecaller, setNewTelecaller] = useState({ name: "", email: "", password: "", sheet_tl_name: "" });
  const [addTelecallerError, setAddTelecallerError] = useState("");
  const [addingTelecaller, setAddingTelecaller] = useState(false);

  const isTL = role === "Team Leader";
  const isTelecaller = role === "Telecaller";
  const isSalesperson = role === "Salesperson";
  const isAdmin = ["SuperAdmin", "Admin", "CEO", "COO", "Regional Manager"].includes(role);
  const canEdit = isTL || isTelecaller || isAdmin;
  const canAssign = isTL || isAdmin;

  const fetchLeads = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.fetchRaw("/tele-call-leads");
      if (res.ok) {
        const d = await res.json();
        setTlGroups(d.tl_groups || {});
        setTotal(d.total || 0);
        setRole(d.role || "");
      }
    } catch {}
    setLoading(false);
  }, []);

  const fetchSalespersons = useCallback(async () => {
    if (!canAssign) return;
    try {
      const res = await api.fetchRaw("/tele-call-leads/salespersons");
      if (res.ok) {
        const d = await res.json();
        setSalespersons(d.salespersons || []);
      }
    } catch {}
  }, [canAssign]);

  const fetchTelecallers = useCallback(async () => {
    try {
      const res = await api.fetchRaw("/tele-call-leads/telecallers");
      if (res.ok) {
        const d = await res.json();
        setTelecallers(d.telecallers || []);
      }
    } catch {}
  }, []);

  useEffect(() => {
    fetchLeads();
    fetchSalespersons();
    fetchTelecallers();
  }, [fetchLeads, fetchSalespersons, fetchTelecallers]);

  const handleSync = useCallback(async () => {
    setSyncing(true);
    try {
      await api.fetchRaw("/tele-call-leads/sync", { method: "POST" });
      await fetchLeads();
    } catch {}
    setSyncing(false);
  }, [fetchLeads]);

  const handleEditStart = useCallback((lead: Lead) => {
    setEditingLead(lead.id);
    setEditForm({
      status: lead.status,
      person_calling: lead.person_calling || user?.name || "",
      remarks: lead.remarks,
      call_date: lead.call_date,
      appointment_date: lead.appointment_date,
      salesperson: lead.salesperson,
      product: lead.product,
      sale_amount: lead.sale_amount,
    });
  }, [user]);

  const handleEditCancel = useCallback(() => {
    setEditingLead(null);
    setEditForm({});
  }, []);

  const handleSave = useCallback(async (leadId: number) => {
    setSaving(true);
    try {
      const res = await api.fetchRaw(`/tele-call-leads/${leadId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(editForm),
      });
      if (res.ok) {
        await fetchLeads();
        setEditingLead(null);
        setEditForm({});
      }
    } catch {}
    setSaving(false);
  }, [editForm, fetchLeads]);

  // One-tap status update for the mobile card view — the backend only
  // touches the status field on a partial PUT, so this can't clobber a
  // lead's other fields the way sending a full form snapshot would.
  const handleQuickStatusUpdate = useCallback(async (lead: Lead, status: string) => {
    if (lead.status === status || quickUpdating !== null) return;
    setQuickUpdating(lead.id);
    try {
      const res = await api.fetchRaw(`/tele-call-leads/${lead.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (res.ok) await fetchLeads();
    } catch {}
    setQuickUpdating(null);
  }, [fetchLeads, quickUpdating]);

  const handleAssign = useCallback(async (leadId: number, salespersonName: string) => {
    try {
      const res = await api.fetchRaw(`/tele-call-leads/${leadId}/assign`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ salesperson: salespersonName }),
      });
      if (res.ok) {
        await fetchLeads();
      }
    } catch {}
  }, [fetchLeads]);

  const handleCreateTelecaller = useCallback(async () => {
    setAddTelecallerError("");
    if (!newTelecaller.name || !newTelecaller.email || !newTelecaller.password || !newTelecaller.sheet_tl_name) {
      setAddTelecallerError("All fields are required");
      return;
    }
    setAddingTelecaller(true);
    try {
      const res = await api.fetchRaw("/tele-call-leads/create-telecaller", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newTelecaller),
      });
      if (res.ok) {
        setShowAddTelecaller(false);
        setNewTelecaller({ name: "", email: "", password: "", sheet_tl_name: "" });
        await fetchTelecallers();
      } else {
        const err = await res.json().catch(() => ({}));
        setAddTelecallerError(err.detail || "Failed to create telecaller");
      }
    } catch {
      setAddTelecallerError("Failed to create telecaller");
    }
    setAddingTelecaller(false);
  }, [newTelecaller, fetchTelecallers]);

  const tlNames = useMemo(() => Object.keys(tlGroups).sort(), [tlGroups]);

  const filteredLeads = useMemo(() => {
    if (!expandedTl) return [];
    const group = tlGroups[expandedTl];
    if (!group) return [];
    let leads = group.leads;
    if (statusFilter) {
      leads = leads.filter((l) => l.status === statusFilter);
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      leads = leads.filter(
        (l) =>
          l.full_name.toLowerCase().includes(q) ||
          l.phone.includes(q) ||
          l.email.toLowerCase().includes(q) ||
          l.remarks.toLowerCase().includes(q)
      );
    }
    return leads;
  }, [expandedTl, tlGroups, statusFilter, searchQuery]);

  const allStatuses = useMemo(() => {
    const s = new Set<string>();
    for (const g of Object.values(tlGroups)) {
      Object.keys(g.status_counts).forEach((st) => s.add(st));
    }
    return Array.from(s).sort();
  }, [tlGroups]);

  // The lead currently open in the mobile edit sheet.
  const editingLeadObj = useMemo(
    () => filteredLeads.find((l) => l.id === editingLead) || null,
    [filteredLeads, editingLead]
  );

  // For telecallers and salespersons, auto-expand their single sheet
  useEffect(() => {
    if ((isTelecaller || isSalesperson) && tlNames.length === 1 && !expandedTl) {
      setExpandedTl(tlNames[0]);
    }
  }, [tlNames, isTelecaller, isSalesperson, expandedTl]);

  return (
    <ErrorBoundary>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white">
              {isTelecaller ? "My Tele Call Leads" : isSalesperson ? "My Assigned Leads" : "Leads Update"}
            </h1>
            <p className="text-sm text-[var(--text-muted)] mt-1">
              {tlNames.length > 0 && `${tlNames.length} city sheet${tlNames.length > 1 ? "s" : ""} · `}
              {total.toLocaleString()} total leads
              {isTelecaller && " · Your assigned sheet"}
              {isSalesperson && " · Leads assigned to you"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {canEdit && (
              <span className="text-[10px] font-semibold px-2.5 py-1 rounded-full bg-[var(--accent-blue)]/15 text-[var(--accent-blue)] border border-[var(--accent-blue)]/25">
                <Edit3 size={12} className="inline mr-1" />
                Edit Mode
              </span>
            )}
            {canAssign && (
              <button
                onClick={() => setShowAddTelecaller(true)}
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium bg-white/5 border border-[var(--border-subtle)] text-white hover:bg-white/10 transition"
              >
                <UserPlus size={16} />
                Add Telecaller
              </button>
            )}
            {!isSalesperson && (
              <button
                onClick={handleSync}
                disabled={syncing}
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium bg-[var(--accent-blue)] text-white hover:opacity-90 transition disabled:opacity-50"
              >
                <RefreshCw size={16} className={syncing ? "animate-spin" : ""} />
                {syncing ? "Syncing..." : "Sync Sheets"}
              </button>
            )}
          </div>
        </div>

        {/* KPI Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            { label: "Total Leads", value: total.toLocaleString(), color: "#3b82f6", icon: <Phone size={20} /> },
            {
              label: "Converted",
              value: Object.values(tlGroups)
                .reduce((s, g) => s + (g.status_counts["Sale Conversion"] || 0), 0)
                .toLocaleString(),
              color: "#10b981",
              icon: <CheckCircle2 size={20} />,
            },
            {
              label: "Appointments",
              value: Object.values(tlGroups)
                .reduce((s, g) => s + (g.status_counts["Appointment"] || 0), 0)
                .toLocaleString(),
              color: "#8b5cf6",
              icon: <CalendarCheck size={20} />,
            },
            {
              label: "Will Visit",
              value: Object.values(tlGroups)
                .reduce((s, g) => s + (g.status_counts["Will Visit"] || 0), 0)
                .toLocaleString(),
              color: "#f59e0b",
              icon: <Phone size={20} />,
            },
          ].map((k, i) => (
            <div key={i} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 relative overflow-hidden">
              <div className="absolute top-0 left-0 right-0 h-0.5" style={{ background: k.color }} />
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ backgroundColor: `${k.color}18`, color: k.color }}>
                  {k.icon}
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)]">{k.label}</p>
                  <p className="text-xl font-extrabold text-white">{k.value}</p>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Filters */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 bg-[var(--bg-card)] border border-[var(--border-subtle)] p-3 rounded-2xl">
          <Filter size={16} className="text-[var(--text-muted)] ml-1 shrink-0" />
          <div className="relative flex-1 w-full sm:max-w-xs">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input
              type="text"
              placeholder="Search name, phone, email..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-2 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none"
            />
            {searchQuery && (
              <button onClick={() => setSearchQuery("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-white">
                <X size={14} />
              </button>
            )}
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-3 py-2 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none max-w-[200px] w-full"
          >
            <option value="">All Statuses</option>
            {allStatuses.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>

        {/* TL / City Sheet Sections */}
        {loading ? (
          <TableSkeleton rows={5} cols={7} />
        ) : (
          <div className="space-y-4">
            {tlNames.map((tlName) => {
              const group = tlGroups[tlName];
              const isExpanded = expandedTl === tlName;
              const statuses = group.status_counts;
              const convRate = group.total > 0 ? Math.round(((statuses["Sale Conversion"] || 0) / group.total) * 100) : 0;

              return (
                <div key={tlName} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] overflow-hidden">
                  {/* TL/City Header */}
                  <button
                    onClick={() => setExpandedTl(isExpanded ? null : tlName)}
                    className="w-full flex items-center gap-4 p-4 sm:p-5 text-left hover:bg-white/[0.02] transition-colors"
                  >
                    <div className="w-10 h-10 rounded-xl bg-[var(--accent-blue)]/15 flex items-center justify-center text-[var(--accent-blue)] shrink-0">
                      <Users size={20} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <h3 className="text-base font-bold text-white">{tlName}</h3>
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-[var(--accent-blue)]/15 text-[var(--accent-blue)]">
                          {group.total} leads
                        </span>
                        {convRate > 0 && (
                          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400">
                            {convRate}% converted
                          </span>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-2 mt-2">
                        {Object.entries(statuses)
                          .sort((a, b) => b[1] - a[1])
                          .slice(0, 6)
                          .map(([status, count]) => (
                            <span
                              key={status}
                              className="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full"
                              style={{
                                backgroundColor: `${STATUS_COLORS[status] || "#64748b"}18`,
                                color: STATUS_COLORS[status] || "#64748b",
                              }}
                            >
                              {STATUS_ICONS[status]}
                              {status}: {count}
                            </span>
                          ))}
                      </div>
                    </div>
                    <div className="shrink-0 text-[var(--text-muted)]">
                      {isExpanded ? <ChevronDown size={20} /> : <ChevronRight size={20} />}
                    </div>
                  </button>

                  {/* Expanded Leads Table */}
                  {isExpanded && (
                    <div className="border-t border-[var(--border-subtle)]">
                      {filteredLeads.length === 0 ? (
                        <div className="p-8 text-center text-sm text-[var(--text-muted)]">
                          No leads found{statusFilter ? ` with status "${statusFilter}"` : ""}{searchQuery ? ` matching "${searchQuery}"` : ""}
                        </div>
                      ) : (
                        <>
                        {/* Mobile card list — the desktop table below is unusable on a
                            phone (13 columns, tiny inline dropdowns, needs horizontal
                            scroll while editing), so phones get one-tap status chips
                            and a full-screen edit sheet instead. */}
                        <div className="md:hidden divide-y divide-[var(--border-subtle)]">
                          {filteredLeads.map((lead) => (
                            <div key={lead.id} className="p-4 space-y-3">
                              <div className="flex items-start justify-between gap-3">
                                <div className="min-w-0">
                                  <button onClick={() => openLead(lead.id)} title="Open lead details and timeline"
                                    className="font-semibold text-white truncate hover:underline cursor-pointer text-left block max-w-full">{lead.full_name}</button>
                                  <PhoneActions phone={lead.phone} size="md" className="mt-0.5" />
                                </div>
                                <span
                                  className="shrink-0 inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-1 rounded-full"
                                  style={{
                                    backgroundColor: `${STATUS_COLORS[lead.status] || "#64748b"}18`,
                                    color: STATUS_COLORS[lead.status] || "#64748b",
                                  }}
                                >
                                  {STATUS_ICONS[lead.status]}
                                  {lead.status || "No Status"}
                                </span>
                              </div>

                              <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[var(--text-muted)]">
                                <span>Source: {lead.lead_source || "—"}</span>
                                {lead.call_date && <span>Called: {lead.call_date}</span>}
                                {lead.appointment_date && <span>Appt: {lead.appointment_date}</span>}
                                {canAssign && <span>Salesperson: {lead.salesperson || "—"}</span>}
                              </div>
                              {lead.remarks && (
                                <p className="text-xs text-[var(--text-secondary)] line-clamp-2">{lead.remarks}</p>
                              )}

                              {canEdit && (
                                <>
                                  <div className="flex gap-2 overflow-x-auto pb-1 -mx-4 px-4">
                                    {STATUS_OPTIONS.map((s) => {
                                      const active = lead.status === s;
                                      return (
                                        <button
                                          key={s}
                                          onClick={() => handleQuickStatusUpdate(lead, s)}
                                          disabled={quickUpdating === lead.id}
                                          className="shrink-0 flex items-center gap-1.5 text-xs font-semibold px-3 py-2.5 rounded-xl border transition disabled:opacity-50"
                                          style={
                                            active
                                              ? { backgroundColor: STATUS_COLORS[s], borderColor: STATUS_COLORS[s], color: "#fff" }
                                              : { backgroundColor: "rgba(255,255,255,0.05)", borderColor: "var(--border-subtle)", color: "var(--text-secondary)" }
                                          }
                                        >
                                          {STATUS_ICONS[s]} {s}
                                        </button>
                                      );
                                    })}
                                  </div>
                                  <button
                                    onClick={() => handleEditStart(lead)}
                                    className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-[var(--accent-blue)]/15 text-[var(--accent-blue)] text-sm font-semibold"
                                  >
                                    <Edit3 size={15} /> Edit Details
                                  </button>
                                </>
                              )}
                            </div>
                          ))}
                        </div>

                        <div className="hidden md:block overflow-x-auto">
                          <table className="w-full text-sm text-left border-collapse">
                            <thead>
                              <tr className="text-[var(--text-muted)] text-xs uppercase tracking-wider border-b border-[var(--border-subtle)]">
                                <th className="py-3 px-4 font-semibold">Customer</th>
                                <th className="py-3 px-4 font-semibold">Phone</th>
                                <th className="py-3 px-4 font-semibold">Person Calling</th>
                                <th className="py-3 px-4 font-semibold">Status</th>
                                <th className="py-3 px-4 font-semibold">Source</th>
                                <th className="py-3 px-4 font-semibold">Created</th>
                                <th className="py-3 px-4 font-semibold">Call Date</th>
                                <th className="py-3 px-4 font-semibold">Appointment</th>
                                <th className="py-3 px-4 font-semibold">Product</th>
                                <th className="py-3 px-4 font-semibold">Sale Amount</th>
                                <th className="py-3 px-4 font-semibold">Remarks</th>
                                {canAssign && <th className="py-3 px-4 font-semibold">Salesperson</th>}
                                {canEdit && <th className="py-3 px-4 font-semibold">Action</th>}
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-[var(--border-subtle)]">
                              {filteredLeads.map((lead) => (
                                <tr key={lead.id} className="hover:bg-[var(--bg-card-hover)] transition-colors">
                                  <td className="py-3 px-4 font-medium text-white max-w-[180px] truncate">
                                    <button onClick={() => openLead(lead.id)} title="Open lead details and timeline"
                                      className="hover:underline cursor-pointer text-left truncate max-w-full">{lead.full_name}</button>
                                  </td>
                                  <td className="py-3 px-4 text-xs text-[var(--text-secondary)] font-mono"><PhoneActions phone={lead.phone} /></td>
                                  <td className="py-3 px-4 text-xs text-[var(--text-secondary)]">
                                    {editingLead === lead.id ? (
                                      <select
                                        value={editForm.person_calling || ""}
                                        onChange={(e) => setEditForm({ ...editForm, person_calling: e.target.value })}
                                        className="w-full px-2 py-1 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none focus:border-[var(--accent-blue)]"
                                      >
                                        <option value="">Select caller</option>
                                        {telecallers
                                          .filter((tc) => tc.sheet === lead.sheet_tl_name)
                                          .map((tc) => (
                                            <option key={tc.id} value={tc.name}>{tc.name}</option>
                                          ))}
                                        {telecallers.filter((tc) => tc.sheet === lead.sheet_tl_name).length === 0 && (
                                          <option value={editForm.person_calling || ""}>
                                            {editForm.person_calling || "No telecallers assigned"}
                                          </option>
                                        )}
                                      </select>
                                    ) : (
                                      lead.person_calling || "—"
                                    )}
                                  </td>
                                  <td className="py-3 px-4">
                                    {editingLead === lead.id ? (
                                      <select
                                        value={editForm.status || ""}
                                        onChange={(e) => setEditForm({ ...editForm, status: e.target.value })}
                                        className="w-full px-2 py-1 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none focus:border-[var(--accent-blue)]"
                                      >
                                        {STATUS_OPTIONS.map((s) => (
                                          <option key={s} value={s}>{s}</option>
                                        ))}
                                      </select>
                                    ) : (
                                      <span
                                        className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full"
                                        style={{
                                          backgroundColor: `${STATUS_COLORS[lead.status] || "#64748b"}18`,
                                          color: STATUS_COLORS[lead.status] || "#64748b",
                                        }}
                                      >
                                        {STATUS_ICONS[lead.status]}
                                        {lead.status || "No Status"}
                                      </span>
                                    )}
                                  </td>
                                  <td className="py-3 px-4 text-xs text-[var(--text-secondary)]">{lead.lead_source || "—"}</td>
                                  <td className="py-3 px-4 text-xs text-[var(--text-secondary)]">{lead.created_time || "—"}</td>
                                  <td className="py-3 px-4 text-xs text-[var(--text-secondary)]">
                                    {editingLead === lead.id ? (
                                      <DatePicker
                                        value={editForm.call_date || ""}
                                        onChange={(d) => setEditForm({ ...editForm, call_date: d })}
                                      />
                                    ) : (
                                      lead.call_date || "—"
                                    )}
                                  </td>
                                  <td className="py-3 px-4 text-xs text-[var(--text-secondary)]">
                                    {editingLead === lead.id ? (
                                      <DatePicker
                                        value={editForm.appointment_date || ""}
                                        onChange={(d) => setEditForm({ ...editForm, appointment_date: d })}
                                      />
                                    ) : (
                                      lead.appointment_date || "—"
                                    )}
                                  </td>
                                  <td className="py-3 px-4 text-xs text-[var(--text-secondary)] max-w-[120px] truncate">
                                    {editingLead === lead.id ? (
                                      <input
                                        type="text"
                                        value={editForm.product || ""}
                                        onChange={(e) => setEditForm({ ...editForm, product: e.target.value })}
                                        placeholder="Optional"
                                        className="w-full px-2 py-1 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none focus:border-[var(--accent-blue)]"
                                      />
                                    ) : (
                                      lead.product || "—"
                                    )}
                                  </td>
                                  <td className="py-3 px-4 text-xs font-semibold text-emerald-400">
                                    {editingLead === lead.id ? (
                                      <input
                                        type="text"
                                        value={editForm.sale_amount || ""}
                                        onChange={(e) => setEditForm({ ...editForm, sale_amount: e.target.value })}
                                        placeholder="Optional"
                                        className="w-full px-2 py-1 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none focus:border-[var(--accent-blue)]"
                                      />
                                    ) : (
                                      lead.sale_amount || "—"
                                    )}
                                  </td>
                                  <td className="py-3 px-4 text-xs text-[var(--text-secondary)] max-w-[200px]">
                                    {editingLead === lead.id ? (
                                      <textarea
                                        value={editForm.remarks || ""}
                                        onChange={(e) => setEditForm({ ...editForm, remarks: e.target.value })}
                                        rows={2}
                                        className="w-full px-2 py-1 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none focus:border-[var(--accent-blue)] resize-none"
                                      />
                                    ) : (
                                      <span title={lead.remarks}>{lead.remarks || "—"}</span>
                                    )}
                                  </td>
                                  {canAssign && (
                                    <td className="py-3 px-4">
                                      {editingLead === lead.id ? (
                                        <select
                                          value={editForm.salesperson || ""}
                                          onChange={(e) => setEditForm({ ...editForm, salesperson: e.target.value })}
                                          className="w-full px-2 py-1 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none focus:border-[var(--accent-blue)]"
                                        >
                                          <option value="">Unassigned</option>
                                          {salespersons.map((sp) => (
                                            <option key={sp.id} value={sp.name}>{sp.name}</option>
                                          ))}
                                        </select>
                                      ) : (
                                        <span className="text-xs text-[var(--text-secondary)]">
                                          {lead.salesperson || <span className="text-[var(--text-muted)]">—</span>}
                                        </span>
                                      )}
                                    </td>
                                  )}
                                  {canEdit && (
                                    <td className="py-3 px-4">
                                      {editingLead === lead.id ? (
                                        <div className="flex items-center gap-1">
                                          <button
                                            onClick={() => handleSave(lead.id)}
                                            disabled={saving}
                                            className="p-1.5 rounded-lg bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition disabled:opacity-50"
                                            title="Save"
                                          >
                                            <Save size={14} />
                                          </button>
                                          <button
                                            onClick={handleEditCancel}
                                            className="p-1.5 rounded-lg bg-red-500/15 text-red-400 hover:bg-red-500/25 transition"
                                            title="Cancel"
                                          >
                                            <X size={14} />
                                          </button>
                                        </div>
                                      ) : (
                                        <button
                                          onClick={() => handleEditStart(lead)}
                                          className="p-1.5 rounded-lg bg-[var(--accent-blue)]/15 text-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/25 transition"
                                          title="Edit"
                                        >
                                          <Edit3 size={14} />
                                        </button>
                                      )}
                                    </td>
                                  )}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        </>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Mobile edit sheet — shares editingLead/editForm state with the
            desktop table's inline row editor above; hidden on desktop since
            that already edits inline. */}
        {editingLead !== null && editingLeadObj && (
          <div
            className="md:hidden fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-end justify-center"
            onClick={(e) => { if (e.target === e.currentTarget) handleEditCancel(); }}
          >
            <div className="w-full max-h-[92vh] overflow-y-auto bg-[#11131e] border-t border-[var(--border-subtle)] rounded-t-2xl">
              <div className="sticky top-0 bg-[#11131e] flex items-center justify-between px-4 py-3.5 border-b border-[var(--border-subtle)]">
                <div className="min-w-0">
                  <h3 className="text-sm font-bold text-white truncate">{editingLeadObj.full_name}</h3>
                  <PhoneActions phone={editingLeadObj.phone} className="mt-0.5" />
                </div>
                <button onClick={handleEditCancel} className="p-2 rounded-lg hover:bg-white/5 text-[var(--text-muted)] shrink-0">
                  <X size={18} />
                </button>
              </div>

              <div className="p-4 space-y-4">
                <div>
                  <label className="text-xs font-semibold text-[var(--text-secondary)] mb-1.5 block">Status</label>
                  <div className="flex flex-wrap gap-2">
                    {STATUS_OPTIONS.map((s) => {
                      const active = editForm.status === s;
                      return (
                        <button
                          key={s}
                          type="button"
                          onClick={() => setEditForm({ ...editForm, status: s })}
                          className="flex items-center gap-1.5 text-xs font-semibold px-3 py-2.5 rounded-xl border transition"
                          style={
                            active
                              ? { backgroundColor: STATUS_COLORS[s], borderColor: STATUS_COLORS[s], color: "#fff" }
                              : { backgroundColor: "rgba(255,255,255,0.05)", borderColor: "var(--border-subtle)", color: "var(--text-secondary)" }
                          }
                        >
                          {STATUS_ICONS[s]} {s}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div>
                  <label className="text-xs font-semibold text-[var(--text-secondary)] mb-1.5 block">Person Calling</label>
                  <select
                    value={editForm.person_calling || ""}
                    onChange={(e) => setEditForm({ ...editForm, person_calling: e.target.value })}
                    className="w-full px-3 py-3 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-base text-white focus:outline-none focus:border-[var(--accent-blue)]"
                  >
                    <option value="">Select caller</option>
                    {telecallers
                      .filter((tc) => tc.sheet === editingLeadObj.sheet_tl_name)
                      .map((tc) => (
                        <option key={tc.id} value={tc.name}>{tc.name}</option>
                      ))}
                    {telecallers.filter((tc) => tc.sheet === editingLeadObj.sheet_tl_name).length === 0 && (
                      <option value={editForm.person_calling || ""}>
                        {editForm.person_calling || "No telecallers assigned"}
                      </option>
                    )}
                  </select>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-semibold text-[var(--text-secondary)] mb-1.5 block">Call Date</label>
                    <DatePicker
                      value={editForm.call_date || ""}
                      onChange={(d) => setEditForm({ ...editForm, call_date: d })}
                    />
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-[var(--text-secondary)] mb-1.5 block">Appointment</label>
                    <DatePicker
                      value={editForm.appointment_date || ""}
                      onChange={(d) => setEditForm({ ...editForm, appointment_date: d })}
                    />
                  </div>
                </div>

                <div>
                  <label className="text-xs font-semibold text-[var(--text-secondary)] mb-1.5 block">Product</label>
                  <input
                    type="text"
                    value={editForm.product || ""}
                    onChange={(e) => setEditForm({ ...editForm, product: e.target.value })}
                    placeholder="Optional"
                    className="w-full px-3 py-3 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-base text-white focus:outline-none focus:border-[var(--accent-blue)]"
                  />
                </div>

                <div>
                  <label className="text-xs font-semibold text-[var(--text-secondary)] mb-1.5 block">Sale Amount</label>
                  <input
                    type="text"
                    value={editForm.sale_amount || ""}
                    onChange={(e) => setEditForm({ ...editForm, sale_amount: e.target.value })}
                    placeholder="Optional"
                    className="w-full px-3 py-3 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-base text-white focus:outline-none focus:border-[var(--accent-blue)]"
                  />
                </div>

                {canAssign && (
                  <div>
                    <label className="text-xs font-semibold text-[var(--text-secondary)] mb-1.5 block">Salesperson</label>
                    <select
                      value={editForm.salesperson || ""}
                      onChange={(e) => setEditForm({ ...editForm, salesperson: e.target.value })}
                      className="w-full px-3 py-3 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-base text-white focus:outline-none focus:border-[var(--accent-blue)]"
                    >
                      <option value="">Unassigned</option>
                      {salespersons.map((sp) => (
                        <option key={sp.id} value={sp.name}>{sp.name}</option>
                      ))}
                    </select>
                  </div>
                )}

                <div>
                  <label className="text-xs font-semibold text-[var(--text-secondary)] mb-1.5 block">Remarks</label>
                  <textarea
                    value={editForm.remarks || ""}
                    onChange={(e) => setEditForm({ ...editForm, remarks: e.target.value })}
                    rows={3}
                    className="w-full px-3 py-3 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-base text-white focus:outline-none focus:border-[var(--accent-blue)] resize-none"
                  />
                </div>
              </div>

              <div className="sticky bottom-0 bg-[#11131e] border-t border-[var(--border-subtle)] p-4 flex gap-2">
                <button
                  onClick={handleEditCancel}
                  className="flex-1 py-3 rounded-xl border border-[var(--border-subtle)] text-[var(--text-secondary)] font-semibold"
                >
                  Cancel
                </button>
                <button
                  onClick={() => handleSave(editingLead)}
                  disabled={saving}
                  className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl bg-[var(--accent-blue)] text-white font-semibold disabled:opacity-50"
                >
                  <Save size={16} /> {saving ? "Saving..." : "Save"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Add Telecaller modal */}
        {showAddTelecaller && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
            onClick={(e) => { if (e.target === e.currentTarget) setShowAddTelecaller(false); }}
          >
            <div className="w-full max-w-md rounded-2xl border border-[var(--border-subtle)] bg-[#11131e] p-6" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <UserPlus size={18} className="text-[var(--accent-blue)]" />
                  Add Telecaller
                </h3>
                <button onClick={() => setShowAddTelecaller(false)} className="p-1.5 rounded-lg hover:bg-white/5 text-[var(--text-muted)]">
                  <X size={16} />
                </button>
              </div>

              <p className="text-xs text-[var(--text-muted)] mb-4">
                {isTL
                  ? "Creates a Telecaller account and assigns it to one of your own sheets."
                  : "Creates a Telecaller account and assigns it to a city sheet."}
              </p>

              {addTelecallerError && (
                <div className="mb-3 p-2.5 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs">
                  {addTelecallerError}
                </div>
              )}

              <div className="space-y-3">
                <input
                  type="text"
                  placeholder="Full name"
                  value={newTelecaller.name}
                  onChange={(e) => setNewTelecaller((p) => ({ ...p, name: e.target.value }))}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white focus:outline-none focus:border-[var(--accent-blue)]"
                />
                <input
                  type="email"
                  placeholder="Email"
                  value={newTelecaller.email}
                  onChange={(e) => setNewTelecaller((p) => ({ ...p, email: e.target.value }))}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white focus:outline-none focus:border-[var(--accent-blue)]"
                />
                <input
                  type="password"
                  placeholder="Password"
                  value={newTelecaller.password}
                  onChange={(e) => setNewTelecaller((p) => ({ ...p, password: e.target.value }))}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white focus:outline-none focus:border-[var(--accent-blue)]"
                />
                <select
                  value={newTelecaller.sheet_tl_name}
                  onChange={(e) => setNewTelecaller((p) => ({ ...p, sheet_tl_name: e.target.value }))}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-sm text-white focus:outline-none focus:border-[var(--accent-blue)]"
                >
                  <option value="">Select sheet</option>
                  {tlNames.map((tl) => (
                    <option key={tl} value={tl}>{tl}</option>
                  ))}
                </select>
              </div>

              <div className="flex gap-2 mt-5">
                <button
                  onClick={() => setShowAddTelecaller(false)}
                  className="flex-1 px-4 py-2.5 rounded-xl border border-[var(--border-subtle)] text-xs font-semibold text-[var(--text-secondary)] hover:bg-white/5 transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreateTelecaller}
                  disabled={addingTelecaller}
                  className="flex-1 px-4 py-2.5 rounded-xl bg-[var(--accent-blue)] text-white text-xs font-semibold hover:opacity-90 transition-all disabled:opacity-50"
                >
                  {addingTelecaller ? "Creating..." : "Create Telecaller"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
}
