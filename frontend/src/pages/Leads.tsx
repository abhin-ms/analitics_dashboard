import { useState, useCallback, useEffect, useMemo } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { api } from "@/lib/apiClient";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { AISummary } from "@/components/dashboard/AISummary";
import { Filter, Loader2, Phone, Users, ArrowRight } from "lucide-react";
import { TableSkeleton } from "@/components/shared/Skeleton";

import { useSocketRefresh } from "../hooks/useSocketRefresh";

// Same status vocabulary/colors as every other telecalling page (shared
// config), so this summary and the pages telecallers work in read alike.
import { STATUS_COLORS } from "@/features/crm/statusConfig";

export default function Leads() {
  const [searchParams] = useSearchParams();
  const tab = searchParams.get("tab") || "main";
  useSocketRefresh(["leads", "tele_call_leads"]);
  const [tlGroups, setTlGroups] = useState<Record<string, { total: number; status_counts: Record<string, number> }>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tlFilter, setTlFilter] = useState("");

  const fetchLeads = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api.fetchRaw("/tele-call-leads");
      if (res.ok) {
        const d = await res.json();
        setTlGroups(d.tl_groups || {});
      } else {
        setError("Failed to load leads data");
      }
    } catch {
      setError("Failed to load leads data");
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchLeads(); }, [fetchLeads]);

  const rows = useMemo(() => {
    return Object.entries(tlGroups)
      .map(([tl, d]) => ({ tl, total: d.total, statuses: d.status_counts || {} }))
      .filter((r) => !tlFilter || r.tl === tlFilter)
      .sort((a, b) => b.total - a.total);
  }, [tlGroups, tlFilter]);

  const uniqueTLs = useMemo(() => Object.keys(tlGroups).sort(), [tlGroups]);

  const totals = useMemo(() => {
    const out = { total: 0, converted: 0, appointments: 0, willVisit: 0, needsFollowUp: 0 };
    for (const r of rows) {
      out.total += r.total;
      out.converted += r.statuses["Sale Conversion"] || 0;
      out.appointments += r.statuses["Appointment"] || 0;
      out.willVisit += r.statuses["Will Visit"] || 0;
      out.needsFollowUp += (r.statuses["Call Not Connected"] || 0) + (r.statuses["Unattended"] || 0) + (r.statuses["Call back later"] || 0);
    }
    return out;
  }, [rows]);

  return (
    <ErrorBoundary>
      {tab === "analytics" ? (
        <AISummary section="leads" title="Leads AI Summary" />
      ) : (
        <div className="space-y-6">
        {error && (
          <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
            {error}
          </div>
        )}
        {loading && !error && (
          <div className="flex items-center gap-2 text-zinc-400 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading leads data...
          </div>
        )}

        {/* KPIs — real telecalling pipeline data, from the same stored
            records telecallers work off in Leads > Update Leads, not a
            crude daily count. */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
          {[
            { label: "Total Leads", value: totals.total.toLocaleString(), color: "#3b82f6" },
            { label: "Sale Conversions", value: totals.converted.toLocaleString(), color: "#10b981" },
            { label: "Conversion Rate", value: totals.total > 0 ? `${Math.round((totals.converted / totals.total) * 100)}%` : "0%", color: "#10b981" },
            { label: "Appointments + Will Visit", value: (totals.appointments + totals.willVisit).toLocaleString(), color: "#8b5cf6" },
            { label: "Needs Follow-up", value: totals.needsFollowUp.toLocaleString(), color: "#f59e0b" },
          ].map((k, i) => (
            <div key={i} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 relative overflow-hidden">
              <div className="absolute top-0 left-0 right-0 h-0.5" style={{ background: k.color }} />
              <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] mb-1">{k.label}</p>
              <p className="text-xl font-extrabold text-white">{k.value}</p>
            </div>
          ))}
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3 bg-[var(--bg-card)] border border-[var(--border-subtle)] p-3 rounded-2xl flex-wrap">
          <Filter size={16} className="text-[var(--text-muted)] ml-1 shrink-0" />
          <select
            value={tlFilter}
            onChange={(e) => setTlFilter(e.target.value)}
            className="px-3 py-2 rounded-xl bg-[var(--bg-primary)] border border-[var(--border-subtle)] text-xs text-white focus:outline-none max-w-[220px] w-full"
          >
            <option value="">All Cities / TLs</option>
            {uniqueTLs.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <Link
            to="/leads/update"
            className="ml-auto flex items-center gap-2 px-3 py-2 text-xs rounded-xl border border-[var(--accent-blue)]/40 bg-[var(--accent-blue)]/10 text-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/20"
          >
            <Phone size={14} />
            Manage Leads
            <ArrowRight size={12} />
          </Link>
        </div>

        {/* Table */}
        <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 sm:p-6 overflow-hidden">
          {loading ? (
            <TableSkeleton rows={6} cols={6} />
          ) : rows.length === 0 ? (
            <div className="text-center py-12 text-[var(--text-muted)]">No lead data available</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left border-collapse">
                <thead>
                  <tr className="text-[var(--text-muted)] text-xs uppercase tracking-wider border-b border-[var(--border-subtle)]">
                    <th className="py-3 px-4 font-semibold">City / TL</th>
                    <th className="py-3 px-4 font-semibold text-right">Total Leads</th>
                    <th className="py-3 px-4 font-semibold text-right">Converted</th>
                    <th className="py-3 px-4 font-semibold text-right">Conv %</th>
                    <th className="py-3 px-4 font-semibold">Status Breakdown</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border-subtle)]">
                  {rows.map((r, i) => {
                    const converted = r.statuses["Sale Conversion"] || 0;
                    const convPct = r.total > 0 ? Math.round((converted / r.total) * 100) : 0;
                    return (
                      <tr key={i} className="hover:bg-[var(--bg-card-hover)] transition-colors">
                        <td className="py-3.5 px-4 font-medium text-white flex items-center gap-2.5">
                          <Users size={15} className="text-[var(--accent-blue)] shrink-0" />
                          <span>{r.tl}</span>
                        </td>
                        <td className="py-3.5 px-4 text-right font-semibold text-white">{r.total}</td>
                        <td className="py-3.5 px-4 text-right font-semibold text-emerald-400">{converted}</td>
                        <td className="py-3.5 px-4 text-right text-[var(--text-secondary)]">{convPct}%</td>
                        <td className="py-3.5 px-4">
                          <div className="flex flex-wrap gap-1.5">
                            {Object.entries(r.statuses).map(([status, count]) => (
                              <span
                                key={status}
                                className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border"
                                style={{
                                  borderColor: `${STATUS_COLORS[status] || "#6b7280"}40`,
                                  backgroundColor: `${STATUS_COLORS[status] || "#6b7280"}15`,
                                  color: STATUS_COLORS[status] || "#9ca3af",
                                }}
                              >
                                {status}: {count}
                              </span>
                            ))}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      )}
    </ErrorBoundary>
  );
}
