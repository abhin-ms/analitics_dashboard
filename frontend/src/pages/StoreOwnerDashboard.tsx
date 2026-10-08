import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { Store, IndianRupee, Target, TrendingUp, Phone, Users, Search, CalendarClock, AlertTriangle } from "lucide-react";
import { api } from "@/lib/apiClient";
import { localDateStr } from "@/lib/utils";
import { formatByCountry } from "@/lib/formatMoney";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { EmptyState } from "@/components/shared/EmptyState";
import { useSocketRefresh } from "@/hooks/useSocketRefresh";
import { statusColor, NO_STATUS } from "@/features/crm/statusConfig";
import SocialSnapshotCard from "@/components/dashboard/SocialSnapshotCard";
import { Card, BarRow, Tip } from "@/features/social/ui";

/** Same achievement colours as the main dashboard's sales cards. */
function salesColor(p: number) {
  return p >= 65 ? "#10b981" : p >= 35 ? "#f59e0b" : "#ef4444";
}

type PeriodKey = "month" | "7day" | "lastmonth" | "3month";
const PERIODS: { key: PeriodKey; label: string }[] = [
  { key: "month", label: "This month" },
  { key: "7day", label: "Last 7 days" },
  { key: "lastmonth", label: "Last month" },
  { key: "3month", label: "Last 3 months" },
];

function periodRange(key: PeriodKey) {
  const now = new Date();
  const to = localDateStr(now);
  if (key === "7day") return { start: localDateStr(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 6)), end: to };
  if (key === "lastmonth") {
    return {
      start: localDateStr(new Date(now.getFullYear(), now.getMonth() - 1, 1)),
      end: localDateStr(new Date(now.getFullYear(), now.getMonth(), 0)),
    };
  }
  if (key === "3month") return { start: localDateStr(new Date(now.getFullYear(), now.getMonth() - 2, 1)), end: to };
  return { start: localDateStr(new Date(now.getFullYear(), now.getMonth(), 1)), end: to };
}

type Tab = "sales" | "leads" | "staff" | "social";
const TABS: { key: Tab; label: string }[] = [
  { key: "sales", label: "Sales" },
  { key: "leads", label: "Leads" },
  { key: "staff", label: "Staff" },
  { key: "social", label: "Social media" },
];

/** Home dashboard for a Store Owner: their store(s)' sales (from MCP),
 * leads, staff and social performance. Read-only. */
export default function StoreOwnerDashboard() {
  useSocketRefresh(["store-owner", "sheets-data"]);
  const [period, setPeriod] = useState<PeriodKey>("month");
  const [tab, setTab] = useState<Tab>("sales");
  const range = periodRange(period);
  const { data, isLoading, error } = useQuery({
    queryKey: ["store-owner", range.start, range.end],
    queryFn: () => api.get<any>(`/store-owner/overview?start=${range.start}&end=${range.end}`),
    placeholderData: (prev) => prev,
  });

  const country = data?.stores?.[0]?.country || "India";
  const money = (n: number) => formatByCountry(n || 0, country);

  return (
    <ErrorBoundary>
      <div className="space-y-6 p-4 sm:p-6 w-full min-w-0">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-white tracking-tight flex flex-wrap items-center gap-2">
              <Store size={20} className="text-[var(--accent-blue)]" />
              {data?.stores?.length === 1 ? data.stores[0].name : "My Stores"}
            </h1>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              {data?.stores?.length > 1 ? `${data.stores.map((s: any) => s.name).join(" · ")} · ` : ""}
              Sales, leads, staff and social media performance
            </p>
          </div>
          <div className="flex max-w-full items-center overflow-x-auto rounded-xl border border-[var(--border-subtle)] bg-white/5 p-0.5">
            {PERIODS.map((p) => (
              <button
                key={p.key}
                onClick={() => setPeriod(p.key)}
                className={`shrink-0 whitespace-nowrap px-3 py-1.5 rounded-lg text-xs font-medium transition ${period === p.key ? "bg-[var(--accent-blue)] text-white" : "text-[var(--text-secondary)] hover:text-white"}`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {isLoading ? (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-6"><TableSkeleton /></div>
        ) : error || !data ? (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-8 text-center">
            <AlertTriangle size={32} className="mx-auto mb-2 text-rose-400" />
            <p className="text-sm font-semibold text-white">Couldn't load your store dashboard</p>
          </div>
        ) : !data.stores.length ? (
          <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)]">
            <EmptyState title="No store linked to your account" description="Ask an admin to tick your store(s) under Settings → Users → Assigned Stores." />
          </div>
        ) : (
          <>
            <Headline data={data} money={money} />
            <div className="flex gap-1 border-b border-[var(--border-subtle)] overflow-x-auto">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={`-mb-px shrink-0 whitespace-nowrap border-b-2 px-3 sm:px-4 py-2 text-sm font-semibold transition ${tab === t.key ? "border-[var(--accent-blue)] text-white" : "border-transparent text-[var(--text-muted)] hover:text-white"}`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            {tab === "sales" && <SalesTab data={data} money={money} />}
            {tab === "leads" && <LeadsTab data={data} money={money} />}
            {tab === "staff" && <StaffTab data={data} money={money} />}
            {tab === "social" && <SocialSnapshotCard />}
          </>
        )}
      </div>
    </ErrorBoundary>
  );
}

function Headline({ data, money }: { data: any; money: (n: number) => string }) {
  const s = data.sales, k = data.leads?.kpis;
  const measured = data.staff.filter((x: any) => x.measured);
  const tiles = [
    { label: "Revenue", value: money(s.total_revenue), sub: `${s.units_sold} units sold · from MCP`, icon: <IndianRupee size={18} />, color: "#3b82f6" },
    { label: "Target", value: s.total_target ? money(s.total_target) : "—", sub: s.total_target ? `${money(Math.max(0, s.total_target - s.total_revenue))} to go` : "no MCP target set", icon: <Target size={18} />, color: "#10b981" },
    { label: "Achievement", value: s.total_target ? `${s.achievement_pct}%` : "—", sub: "revenue ÷ target", meter: s.total_target ? s.achievement_pct / 100 : undefined, icon: <TrendingUp size={18} />, color: "#a855f7" },
    { label: "Leads", value: String(k?.total_leads ?? 0), sub: `${k?.converted ?? 0} converted · ${k?.conversion_pct ?? 0}%`, icon: <Phone size={18} />, color: "#06b6d4" },
    { label: "Upcoming appointments", value: String(data.leads?.upcoming_appointments ?? 0), sub: "booked into your store(s)", icon: <CalendarClock size={18} />, color: "#f59e0b" },
    { label: "Staff", value: String(data.staff.length), sub: `${measured.length} handling leads`, icon: <Users size={18} />, color: "#ec4899" },
  ];
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3 min-w-0">
      {tiles.map((t) => (
        <div key={t.label} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 relative overflow-hidden min-w-0">
          <div className="absolute top-0 left-0 right-0 h-0.5" style={{ background: t.color }} />
          <div className="flex items-center gap-2 mb-2">
            <div className="p-1.5 rounded-lg" style={{ background: `${t.color}20`, color: t.color }}>{t.icon}</div>
            <p className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] leading-tight">{t.label}</p>
          </div>
          <p className="text-xl font-extrabold text-white">{t.value}</p>
          <p className="text-[11px] text-[var(--text-muted)] mt-0.5">{t.sub}</p>
          {"meter" in t && t.meter !== undefined && (
            <div className="mt-2 h-1.5 rounded-full bg-[var(--border-subtle)] overflow-hidden">
              <div className="h-full rounded-full" style={{ width: `${Math.min(100, t.meter * 100)}%`, background: salesColor(t.meter * 100) }} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function SalesTab({ data, money }: { data: any; money: (n: number) => string }) {
  const s = data.sales;
  const multi = data.stores.length > 1;
  return (
    <div className="space-y-6">
      <Card title="Revenue trend" subtitle={`${s.granularity === "day" ? "Daily" : "Monthly"} revenue from MCP · ${data.period.start} to ${data.period.end}`}>
        {s.trend.length ? (
          <div className="h-64 w-full min-w-0">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={s.trend} margin={{ left: 0, right: 8, top: 8 }}>
                <defs>
                  <linearGradient id="ownerRev" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" vertical={false} />
                <XAxis dataKey="period" tick={{ fontSize: 10, fill: "var(--text-secondary)" }} tickFormatter={(v: string) => (v.length === 10 ? v.slice(8) : v)} />
                <YAxis tick={{ fontSize: 10, fill: "var(--text-secondary)" }} tickFormatter={(v: number) => money(v)} width={64} />
                <Tooltip
                  contentStyle={{ backgroundColor: "var(--bg-card)", borderColor: "var(--border-subtle)", borderRadius: 12, fontSize: 12 }}
                  labelStyle={{ color: "var(--text-primary)" }}
                  formatter={(v) => [money(Number(v) || 0), "Revenue"]}
                />
                <Area type="monotone" dataKey="revenue" stroke="#3b82f6" strokeWidth={2} fill="url(#ownerRev)" isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        ) : <p className="text-xs text-[var(--text-muted)]">No sales recorded in MCP for this period.</p>}
      </Card>

      <Card title={multi ? "Sales by store" : "Store sales"} subtitle="Revenue against the MCP monthly target, walk-ins and conversions">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-xs border-collapse">
            <thead>
              <tr className="border-b border-[var(--border-subtle)] text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                {["Store", "Revenue", "Target", "Achievement", "Units", "Walk-ins", "Conversions"].map((h, i) => (
                  <th key={h} className={`py-2 px-2 font-semibold ${i ? "text-right" : "text-left"}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border-subtle)]">
              {s.by_store.map((r: any) => (
                <tr key={r.store}>
                  <td className="py-2 px-2 font-medium text-white">{r.store}</td>
                  <td className="py-2 px-2 text-right tabular-nums text-white">{formatByCountry(r.revenue, r.country)}</td>
                  <td className="py-2 px-2 text-right tabular-nums text-[var(--text-secondary)]">{r.target ? formatByCountry(r.target, r.country) : "—"}</td>
                  <td className="py-2 px-2 text-right">
                    {r.target ? (
                      <span className="inline-flex items-center gap-2">
                        <span className="h-1.5 w-16 rounded-full bg-[var(--border-subtle)] overflow-hidden">
                          <span className="block h-full rounded-full" style={{ width: `${Math.min(100, r.achievement_pct)}%`, background: salesColor(r.achievement_pct) }} />
                        </span>
                        <b className="tabular-nums text-white">{r.achievement_pct}%</b>
                      </span>
                    ) : <span className="text-[var(--text-muted)]">—</span>}
                  </td>
                  <td className="py-2 px-2 text-right tabular-nums text-[var(--text-secondary)]">{r.units_sold}</td>
                  <td className="py-2 px-2 text-right tabular-nums text-[var(--text-secondary)]">{r.walkins}</td>
                  <td className="py-2 px-2 text-right tabular-nums text-[var(--text-secondary)]">
                    {r.conversions}{r.walkins ? <span className="text-[var(--text-muted)]"> ({Math.round((r.conversions / r.walkins) * 100)}%)</span> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {s.needs_review?.length > 0 && (
          <p className="mt-3 text-[11px] text-amber-400">
            {s.needs_review.map((r: any) => r.store).join(", ")} {s.needs_review.length === 1 ? "is" : "are"} waiting for admin review in MCP and not counted above.
          </p>
        )}
      </Card>
    </div>
  );
}

function LeadsTab({ data, money }: { data: any; money: (n: number) => string }) {
  const leads = data.leads;
  const [status, setStatus] = useState<string>("");
  const [q, setQ] = useState("");
  const counts: [string, number][] = Object.entries(leads.status_counts as Record<string, number>);
  const max = Math.max(1, ...counts.map(([, n]) => n));
  const rows = useMemo(() => leads.recent.filter((l: any) =>
    (!status || (l.status || NO_STATUS) === status)
    && `${l.name} ${l.phone} ${l.handled_by} ${l.salesperson}`.toLowerCase().includes(q.trim().toLowerCase())),
  [leads.recent, status, q]);
  const k = leads.kpis;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.2fr] gap-6 min-w-0">
        <Card title="Lead status" subtitle="Leads received in this period · click a status to filter the list">
          {counts.length ? counts.map(([st, n]) => (
            <button key={st} onClick={() => setStatus(status === st ? "" : st)} className={`block w-full text-left rounded-md ${status === st ? "ring-1 ring-[var(--accent-blue)]" : ""}`}>
              <BarRow label={st} pct={(n / max) * 100} color={statusColor(st)} value={n} tip={`${st}: ${n} lead${n === 1 ? "" : "s"}`} />
            </button>
          )) : <p className="text-xs text-[var(--text-muted)]">No leads in this period.</p>}
        </Card>
        <Card title="Lead summary">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 text-xs">
            {[
              ["Received", k.total_leads], ["Converted", `${k.converted} (${k.conversion_pct}%)`], ["Sale value", money(k.total_sale_amount)],
              ["Appointments", k.appointments], ["Will visit", k.will_visit], ["Not called yet", k.no_status],
              ["Calls connected", `${k.connected_pct}%`], ["Call back later", k.call_back_later], ["Not interested", k.not_interested],
            ].map(([label, value]) => (
              <div key={label as string} className="rounded-xl border border-[var(--border-subtle)] p-3">
                <p className="text-[var(--text-muted)]">{label}</p>
                <p className="mt-1 text-lg font-extrabold text-white tabular-nums">{value}</p>
              </div>
            ))}
          </div>
          {data.stores.length > 1 && (
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr className="border-b border-[var(--border-subtle)] text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                    {["Store", "Leads", "Converted", "Conv. %", "Not called"].map((h, i) => <th key={h} className={`py-2 px-2 font-semibold ${i ? "text-right" : "text-left"}`}>{h}</th>)}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border-subtle)]">
                  {leads.by_store.map((r: any) => (
                    <tr key={r.store}>
                      <td className="py-2 px-2 text-white">{r.store}</td>
                      <td className="py-2 px-2 text-right tabular-nums">{r.total_leads}</td>
                      <td className="py-2 px-2 text-right tabular-nums">{r.converted}</td>
                      <td className="py-2 px-2 text-right tabular-nums">{r.conversion_pct}%</td>
                      <td className="py-2 px-2 text-right tabular-nums">{r.no_status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <Card
        title="Lead details"
        subtitle={`${rows.length} of ${leads.recent.length} most recent leads${status ? ` · status: ${status}` : ""}`}
        right={
          <label className="flex items-center gap-2 rounded-lg border border-[var(--border-subtle)] px-2.5 py-1.5">
            <Search size={14} className="text-[var(--text-muted)]" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, phone or staff"
              className="w-40 bg-transparent text-xs text-white outline-none placeholder:text-[var(--text-muted)]" />
          </label>
        }
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-xs border-collapse">
            <thead>
              <tr className="border-b border-[var(--border-subtle)] text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                {["Received", "Customer", "Phone", "Status", ...(data.stores.length > 1 ? ["Store"] : []), "Handled by", "Salesperson", "Appointment", "Sale"].map((h) => (
                  <th key={h} className="py-2 px-2 text-left font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border-subtle)]">
              {rows.map((l: any) => (
                <tr key={l.id} className="hover:bg-[var(--bg-card-hover)]">
                  <td className="py-2 px-2 whitespace-nowrap text-[var(--text-secondary)]">
                    {l.received_at ? new Date(l.received_at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "numeric", minute: "2-digit" }) : "—"}
                  </td>
                  <td className="py-2 px-2 font-medium text-white">{l.name || "—"}</td>
                  <td className="py-2 px-2 tabular-nums text-[var(--text-secondary)]">{l.phone || "—"}</td>
                  <td className="py-2 px-2">
                    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ background: `${statusColor(l.status)}22`, color: statusColor(l.status) }}>
                      {l.status || NO_STATUS}
                    </span>
                  </td>
                  {data.stores.length > 1 && <td className="py-2 px-2 text-[var(--text-secondary)]">{l.store || "—"}</td>}
                  <td className="py-2 px-2 text-[var(--text-secondary)]">{l.handled_by || "—"}</td>
                  <td className="py-2 px-2 text-[var(--text-secondary)]">{l.salesperson || "—"}</td>
                  <td className="py-2 px-2 whitespace-nowrap text-[var(--text-secondary)]">{l.appointment_date || "—"}</td>
                  <td className="py-2 px-2 tabular-nums text-white">{l.sale_amount ? money(l.sale_amount) : "—"}</td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={9} className="py-6 text-center text-[var(--text-muted)]">No leads match.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function pct(v: number | null | undefined) {
  return v === null || v === undefined ? "—" : `${Math.round(v)}%`;
}

function StaffTab({ data, money }: { data: any; money: (n: number) => string }) {
  const staff = data.staff as any[];
  const measured = staff.filter((s) => s.measured);
  const maxLeads = Math.max(1, ...measured.map((s) => s.total_leads));
  return (
    <div className="space-y-6">
      {data.staff_records.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {data.staff_records.map((r: any) => (
            <Card key={r.store} title={r.store} subtitle={`Staffing record · ${r.month}`}>
              <div className="grid grid-cols-2 gap-3 text-xs">
                {[
                  ["Manager", r.manager_name || "—"], ["Staff / headcount", `${r.staff_count} / ${r.total_headcount}`],
                  ["Accommodation", r.has_accommodation ? "Yes" : "No"], ["Training running", r.training_active ? "Yes" : "No"],
                  ["Resignation risk", r.resignation_risk ? `${r.resignation_risk} staff` : "None"],
                ].map(([label, value]) => (
                  <div key={label as string}>
                    <p className="text-[var(--text-muted)]">{label}</p>
                    <p className={`mt-0.5 font-semibold ${label === "Resignation risk" && r.resignation_risk ? "text-rose-300" : "text-white"}`}>{value}</p>
                  </div>
                ))}
              </div>
              {r.notes && <p className="mt-3 text-[11px] text-[var(--text-muted)]">{r.notes}</p>}
            </Card>
          ))}
        </div>
      )}

      <Card title="Staff performance" subtitle="Leads each person handled in this period, how many they converted, and how fast they called">
        {staff.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-xs border-collapse">
              <thead>
                <tr className="border-b border-[var(--border-subtle)] text-[10px] uppercase tracking-wider text-[var(--text-muted)]">
                  {["Name", "Role", "Store", "Leads", "Converted", "Conv. %", "Calls connected", "First call on time", "Follow-ups on time", "Sales closed", "Sale value"].map((h, i) => (
                    <th key={h} className={`py-2 px-2 font-semibold whitespace-nowrap ${i < 3 ? "text-left" : "text-right"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-subtle)]">
                {staff.map((s) => (
                  <tr key={s.user_id} className="hover:bg-[var(--bg-card-hover)]">
                    <td className="py-2 px-2">
                      <span className="font-medium text-white">{s.name}</span>
                      {!s.is_active && <span className="ml-1.5 rounded bg-white/10 px-1 text-[10px] text-[var(--text-muted)]">inactive</span>}
                      <div className="text-[10px] text-[var(--text-muted)]">{s.email}</div>
                    </td>
                    <td className="py-2 px-2 text-[var(--text-secondary)] whitespace-nowrap">{s.role}</td>
                    <td className="py-2 px-2 text-[var(--text-secondary)]">{s.stores.join(", ") || "—"}</td>
                    {s.measured ? (
                      <>
                        <td className="py-2 px-2">
                          <Tip content={`${s.total_leads} leads · ${s.no_status} not called yet · ${s.appointments} appointments`}>
                            <div className="flex items-center justify-end gap-2">
                              <span className="h-1.5 w-14 rounded-full bg-[var(--border-subtle)] overflow-hidden">
                                <span className="block h-full rounded-full bg-[var(--accent-blue)]" style={{ width: `${(s.total_leads / maxLeads) * 100}%` }} />
                              </span>
                              <span className="tabular-nums text-white">{s.total_leads}</span>
                            </div>
                          </Tip>
                        </td>
                        <td className="py-2 px-2 text-right tabular-nums text-white">{s.converted}</td>
                        <td className="py-2 px-2 text-right tabular-nums">{s.total_leads ? `${s.conversion_pct}%` : "—"}</td>
                        <td className="py-2 px-2 text-right tabular-nums">{s.total_leads ? `${s.connected_pct}%` : "—"}</td>
                        <td className="py-2 px-2 text-right tabular-nums">{pct(s.first_call_pct)}</td>
                        <td className="py-2 px-2 text-right tabular-nums">{pct(s.followups_on_time_pct)}</td>
                      </>
                    ) : (
                      <td colSpan={6} className="py-2 px-2 text-right text-[var(--text-muted)]">
                        {s.role === "Team Leader" ? "Team leader for this store" : "Not handling leads in the CRM"}
                      </td>
                    )}
                    <td className="py-2 px-2 text-right tabular-nums text-white">{s.sales_closed || "—"}</td>
                    <td className="py-2 px-2 text-right tabular-nums text-white">{s.sales_amount ? money(s.sales_amount) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-xs text-[var(--text-muted)]">
            No staff are linked to your store yet. Staff accounts are linked to a store under Settings → Users.
          </p>
        )}
        <p className="mt-3 text-[11px] text-[var(--text-muted)]">
          Sales closed = leads marked "Sale Conversion" in this period where the person is named as the salesperson.
        </p>
      </Card>
    </div>
  );
}
