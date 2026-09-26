import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { StatCard } from "@/components/shared/StatCard";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import {
  DollarSign, Target, Users, Phone, CheckCircle2, TrendingUp,
  PhoneCall, PhoneOff, CalendarCheck, Eye, BarChart3,
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, BarChart, Bar, CartesianGrid, Legend,
} from "recharts";
import { statusColor } from "@/features/crm/statusConfig";
import { TeamCrmPanel } from "@/features/crm/components/DashboardPanels";
import { PeriodKey, periodRange } from "@/features/crm/components/shared";

const COLORS = ["#3b82f6", "#10b981", "#a855f7", "#f97316", "#ec4899", "#06b6d4", "#f59e0b", "#ef4444"];

function fmtINR(n: number) {
  if (n >= 100000) return `\u20b9${(n / 100000).toFixed(1)}L`;
  if (n >= 1000) return `\u20b9${(n / 1000).toFixed(1)}K`;
  return `\u20b9${n.toLocaleString("en-IN")}`;
}
function ragColor(p: number) { return p >= 65 ? "#10b981" : p >= 35 ? "#f59e0b" : "#ef4444"; }

export default function TeamLeaderDashboard() {
  // "All time" by default, so the original numbers below stay as they were.
  const [periodKey, setPeriodKey] = useState<PeriodKey>("all");
  const [custom, setCustom] = useState(() => periodRange("month"));
  const range = periodRange(periodKey, custom);
  const qs = range.start ? `?start=${range.start}&end=${range.end}` : "";
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard", "team-leader", qs],
    queryFn: () => api.get<any>(`/dashboard/team-leader${qs}`),
    refetchInterval: 300000,
    placeholderData: (prev) => prev,
  });

  if (isLoading) return <div className="p-6"><TableSkeleton /></div>;
  if (!data) return null;

  const { stores, kpi, lead_funnel, telecaller_performance, revenue_trend } = data;

  const funnelData = Object.entries(lead_funnel || {}).map(([status, count]) => ({
    name: status, value: count as number,
  })).sort((a, b) => b.value - a.value);

  return (
    <ErrorBoundary>
      <div className="space-y-6 p-6">
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight">Team Performance</h1>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">
            Your stores, leads, and telecaller analytics
          </p>
        </div>

        {/* Telecalling: team queue, status, status-by-telecaller, performance (new) */}
        <TeamCrmPanel data={data} period={{ key: periodKey, setKey: setPeriodKey, custom, setCustom }} />

        {/* KPI Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            title="Revenue vs Target"
            value={kpi.total_revenue}
            delta={kpi.achievement_pct >= 100 ? kpi.achievement_pct - 100 : -(100 - kpi.achievement_pct)}
            icon={<DollarSign size={20} />}
            color="#3b82f6"
            type="money"
          />
          <StatCard
            title="Achievement %"
            value={kpi.achievement_pct}
            icon={<Target size={20} />}
            color={ragColor(kpi.achievement_pct)}
            type="percent"
          />
          <StatCard
            title="Active Leads"
            value={kpi.active_leads}
            icon={<Phone size={20} />}
            color="#a855f7"
            type="number"
          />
          <StatCard
            title="Submission Compliance"
            value={kpi.submission_compliance_pct}
            icon={<CheckCircle2 size={20} />}
            color={kpi.submission_compliance_pct >= 80 ? "#10b981" : "#f59e0b"}
            type="percent"
          />
        </div>

        {/* Store Performance + Lead Funnel */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Store Achievement Chart */}
          <div className="lg:col-span-2 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5">
            <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
              <BarChart3 size={16} className="text-[var(--accent-blue)]" />
              Store Revenue vs Target
            </h3>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={stores} layout="vertical" margin={{ left: 10, right: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.1)" />
                <XAxis type="number" tick={{ fill: "#94a3b8", fontSize: 11 }} tickFormatter={(v) => fmtINR(v)} />
                <YAxis dataKey="name" type="category" width={100} tick={{ fill: "#94a3b8", fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 12 }}
                  labelStyle={{ color: "var(--text-primary)" }}
                  itemStyle={{ color: "var(--text-primary)" }}
                  formatter={(val: any) => fmtINR(Number(val))}
                />
                <Bar dataKey="target" fill="rgba(148,163,184,0.2)" radius={[0, 4, 4, 0]} name="Target" />
                <Bar dataKey="revenue" radius={[0, 4, 4, 0]} name="Revenue">
                  {stores.map((s: any, i: number) => (
                    <Cell key={i} fill={ragColor(s.achievement_pct)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Lead Funnel */}
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5">
            <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
              <Phone size={16} className="text-[var(--accent-blue)]" />
              Lead Funnel
            </h3>
            {funnelData.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Pie data={funnelData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} innerRadius={40}>
                      {funnelData.map((f, i) => (
                        <Cell key={i} fill={statusColor(f.name)} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 12 }}
                      labelStyle={{ color: "var(--text-primary)" }}
                      itemStyle={{ color: "var(--text-primary)" }}
                    />
                  </PieChart>
                </ResponsiveContainer>
                <div className="space-y-1.5 mt-2">
                  {funnelData.slice(0, 6).map((f, i) => (
                    <div key={f.name} className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: statusColor(f.name) }} />
                        <span className="text-[var(--text-secondary)]">{f.name}</span>
                      </div>
                      <span className="font-semibold text-white">{f.value}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p className="text-xs text-[var(--text-muted)] text-center py-8">No lead data</p>
            )}
          </div>
        </div>

        {/* Telecaller Performance + Revenue Trend */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Telecaller Table */}
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5">
            <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
              <Users size={16} className="text-[var(--accent-blue)]" />
              Telecaller Performance
            </h3>
            {telecaller_performance.length > 0 ? (
              <>
                {/* Mobile cards */}
                <div className="md:hidden -mx-5 divide-y divide-[var(--border-subtle)]">
                  {telecaller_performance.map((t: any) => (
                    <div key={t.name} className="px-5 py-3 flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p className="font-medium text-white truncate">{t.name}</p>
                        <p className="text-[11px] text-[var(--text-muted)]">
                          {t.total_leads} leads · <span className="text-emerald-400 font-semibold">{t.converted} converted</span> · <span className="text-blue-400 font-semibold">{t.appointments} appts</span>
                        </p>
                      </div>
                      <span
                        className="shrink-0 px-2.5 py-1 rounded-full text-xs font-semibold"
                        style={{
                          backgroundColor: `${ragColor(t.conversion_pct)}15`,
                          color: ragColor(t.conversion_pct),
                          border: `1px solid ${ragColor(t.conversion_pct)}30`,
                        }}
                      >
                        {t.conversion_pct}%
                      </span>
                    </div>
                  ))}
                </div>

                <div className="hidden md:block overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-[var(--text-muted)] uppercase tracking-wider border-b border-[var(--border-subtle)]">
                        <th className="pb-2 text-left font-semibold">Name</th>
                        <th className="pb-2 text-right font-semibold">Leads</th>
                        <th className="pb-2 text-right font-semibold">Converted</th>
                        <th className="pb-2 text-right font-semibold">Appts</th>
                        <th className="pb-2 text-right font-semibold">Conv %</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--border-subtle)]">
                      {telecaller_performance.map((t: any) => (
                        <tr key={t.name} className="hover:bg-[var(--bg-card-hover)]">
                          <td className="py-2.5 font-medium text-white">{t.name}</td>
                          <td className="py-2.5 text-right text-[var(--text-secondary)]">{t.total_leads}</td>
                          <td className="py-2.5 text-right">
                            <span className="text-emerald-400 font-semibold">{t.converted}</span>
                          </td>
                          <td className="py-2.5 text-right">
                            <span className="text-blue-400 font-semibold">{t.appointments}</span>
                          </td>
                          <td className="py-2.5 text-right">
                            <span
                              className="px-2 py-0.5 rounded-full text-[10px] font-semibold"
                              style={{
                                backgroundColor: `${ragColor(t.conversion_pct)}15`,
                                color: ragColor(t.conversion_pct),
                                border: `1px solid ${ragColor(t.conversion_pct)}30`,
                              }}
                            >
                              {t.conversion_pct}%
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <p className="text-xs text-[var(--text-muted)] text-center py-8">No telecaller data</p>
            )}
          </div>

          {/* Revenue Trend */}
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5">
            <h3 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
              <TrendingUp size={16} className="text-[var(--accent-blue)]" />
              Revenue Trend
            </h3>
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={revenue_trend}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.1)" />
                <XAxis
                  dataKey="date" tick={{ fill: "#94a3b8", fontSize: 10 }}
                  tickFormatter={(d) => { const dt = new Date(d); return `${dt.getDate()}/${dt.getMonth()+1}`; }}
                />
                <YAxis tick={{ fill: "#94a3b8", fontSize: 10 }} tickFormatter={(v) => fmtINR(v)} />
                <Tooltip
                  contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 12 }}
                  labelStyle={{ color: "var(--text-primary)" }}
                  itemStyle={{ color: "var(--text-primary)" }}
                  formatter={(val: any) => fmtINR(Number(val))}
                  labelFormatter={(d: any) => new Date(d).toLocaleDateString("en-IN")}
                />
                <Line type="monotone" dataKey="revenue" stroke="#3b82f6" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Walk-in Stats */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 text-center">
            <p className="text-xs text-[var(--text-muted)] uppercase tracking-wide mb-1">Total Walk-ins</p>
            <p className="text-3xl font-bold text-white">{kpi.total_walk_ins}</p>
          </div>
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 text-center">
            <p className="text-xs text-[var(--text-muted)] uppercase tracking-wide mb-1">Walk-in Conversions</p>
            <p className="text-3xl font-bold text-emerald-400">{kpi.total_walk_in_conversions}</p>
          </div>
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 text-center">
            <p className="text-xs text-[var(--text-muted)] uppercase tracking-wide mb-1">Walk-in Conversion %</p>
            <p className="text-3xl font-bold" style={{ color: ragColor(kpi.walk_in_conversion_pct) }}>
              {kpi.walk_in_conversion_pct}%
            </p>
          </div>
        </div>
      </div>
    </ErrorBoundary>
  );
}
