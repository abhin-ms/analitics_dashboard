import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Bell, ArrowRight, Plus, TrendingUp, ShieldCheck, Coffee } from "lucide-react";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useToast } from "@/components/shared/Toast";
import { useAckAlert, useCrmMeta, useOverview, useSetAvailability } from "../api";
import { ALERT_KIND_LABELS, stageMeta } from "../statusConfig";
import { fmtDateTime, fmtINR, fmtINRShort } from "../format";
import { openLead } from "../components/LeadDrawer";
import { NewLeadDialog } from "../components/dialogs";
import { EmptyFollowups, FollowupRow } from "../components/shared";
import { Button, Card, CardHeader, Empty, PageHeader, Tile } from "../components/ui";

export default function TodayPage() {
  const { data: meta } = useCrmMeta();
  const isAgent = meta?.role === "Telecaller" || meta?.role === "Salesperson";
  const [mine, setMine] = useState<boolean | undefined>(undefined);
  const { data, isLoading, error } = useOverview(mine);
  const ack = useAckAlert();
  const setAvail = useSetAvailability();
  const toast = useToast();
  const navigate = useNavigate();
  const [newLead, setNewLead] = useState(false);

  if (isLoading || !meta) return <div className="p-6"><TableSkeleton /></div>;
  if (error || !data) return <p className="p-6 text-sm text-rose-400">{error instanceof Error ? error.message : "Could not load"}</p>;

  const scopeLabel = data.mine ? "My day" : meta.role === "Team Leader" ? "Team overview" : "All cities";
  const today = new Date().toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", weekday: "long", day: "numeric", month: "long" });
  const maxStage = Math.max(1, ...data.pipeline.map((p) => p.count));

  return (
    <ErrorBoundary>
      <div className="space-y-6 p-4 sm:p-6">
        <PageHeader
          title="A clear plan for today"
          subtitle={`${today} · ${scopeLabel}`}
          actions={<>
            {!isAgent && (
              <Button size="sm" onClick={() => setMine(!data.mine)}>{data.mine ? "Show team" : "Only mine"}</Button>
            )}
            {isAgent && (
              <Button size="sm" loading={setAvail.isPending}
                onClick={async () => {
                  await setAvail.mutateAsync({ available: !meta.user.available });
                  toast.success(meta.user.available ? "You are Away — no new leads will be auto-assigned" : "You are Available");
                }}>
                {meta.user.available ? <><ShieldCheck size={14} className="text-emerald-400" />Available</> : <><Coffee size={14} className="text-amber-400" />Away</>}
              </Button>
            )}
            <Button variant="primary" onClick={() => setNewLead(true)}><Plus size={15} />New lead</Button>
          </>}
        />

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Tile label="First contact" value={data.tiles.first_contact_pending} hint="Awaiting a first call ↗"
            onClick={() => navigate("/crm/leads?tab=new")} />
          <Tile label="Due today" value={data.tiles.due_today} hint={data.mine ? "Your next actions ↗" : "Team's next actions ↗"}
            onClick={() => navigate("/crm/tasks")} />
          <Tile label="Overdue" value={data.tiles.overdue} hint="Needs attention ↗" color={data.tiles.overdue ? "#ef4444" : undefined}
            onClick={() => navigate("/crm/leads?tab=overdue")} />
          <Tile label="Unassigned" value={data.tiles.unassigned} hint="Assign an owner ↗" color={data.tiles.unassigned ? "#f59e0b" : undefined}
            onClick={() => navigate("/crm/leads?tab=unassigned")} />
        </div>

        <Card>
          <CardHeader title="Dashboard inbox" icon={<Bell size={15} className="text-blue-400" />}
            action={<Link to="/crm/alerts" className="text-xs text-blue-400 hover:underline">All alerts ({data.inbox.total}) →</Link>} />
          {data.inbox.items.length === 0 ? <Empty>No open alerts. Nice work.</Empty> : (
            <div className="divide-y divide-[var(--border-subtle)]">
              {data.inbox.items.map((a) => (
                <div key={a.id} className="flex flex-col sm:flex-row sm:items-center gap-3 px-5 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-white">{a.title}</p>
                    <p className="text-xs text-[var(--text-muted)]">
                      {ALERT_KIND_LABELS[a.kind] || a.kind} · {fmtDateTime(a.created_at)}{a.lead_name ? ` · ${a.lead_name}` : ""}
                    </p>
                    {a.body && <p className="text-xs text-[var(--text-secondary)] mt-0.5">{a.body}</p>}
                  </div>
                  <div className="flex items-center gap-2">
                    {a.lead_id && <Button size="sm" variant="ghost" onClick={() => openLead(a.lead_id!)}>Open lead</Button>}
                    {!a.acknowledged_at
                      ? <Button size="sm" onClick={() => ack.mutate(a.id)}>Acknowledge</Button>
                      : <span className="text-[11px] text-[var(--text-muted)]">Acknowledged</span>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Card className="lg:col-span-2">
            <CardHeader title="Follow-ups to prioritise"
              action={<Link to="/crm/tasks" className="text-xs text-blue-400 hover:underline">View all →</Link>} />
            {data.followups.length === 0 ? <EmptyFollowups text="Nothing pending." /> : (
              <div className="divide-y divide-[var(--border-subtle)]">
                {data.followups.map((f) => <FollowupRow key={f.id} f={f} showOwner={!data.mine} />)}
              </div>
            )}
          </Card>

          <Card>
            <CardHeader title="Sales snapshot" icon={<TrendingUp size={15} className="text-emerald-400" />} />
            <div className="px-5 py-4 space-y-4">
              <div>
                <div className="flex justify-between text-xs"><span className="text-[var(--text-muted)]">Open pipeline</span>
                  <span className="text-white font-semibold">{fmtINR(data.sales.open_pipeline_value)}</span></div>
              </div>
              <div>
                <div className="flex justify-between text-xs"><span className="text-[var(--text-muted)]">Converted this month</span>
                  <span className="text-emerald-400 font-semibold">{fmtINR(data.sales.converted_this_month_value)}</span></div>
                <p className="text-[10px] text-[var(--text-muted)] mt-0.5">{data.sales.converted_this_month_count} sale{data.sales.converted_this_month_count === 1 ? "" : "s"}</p>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-[var(--text-muted)]">Today's appointments</span>
                <Link to="/crm/appointments" className="text-blue-400 hover:underline">{data.sales.appointments_today} scheduled →</Link>
              </div>
              <p className="text-[10px] text-[var(--text-muted)]">Values in INR · open value comes from the price book.</p>
            </div>
          </Card>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Card className="lg:col-span-2">
            <CardHeader title="Pipeline by stage" action={<Link to="/crm/pipeline" className="text-xs text-blue-400 hover:underline">Open board →</Link>} />
            <div className="px-5 py-4 space-y-3">
              {data.pipeline.map((p) => (
                <button key={p.stage} onClick={() => navigate(`/crm/leads?stage=${p.stage}`)} className="w-full text-left cursor-pointer group">
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-[var(--text-secondary)] group-hover:text-white">{p.label}</span>
                    <span className="text-[var(--text-muted)]">{p.count} lead{p.count === 1 ? "" : "s"}{p.value ? ` · ${fmtINRShort(p.value)}` : ""}</span>
                  </div>
                  <div className="h-2 rounded-full bg-[var(--bg-primary)] overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${(p.count / maxStage) * 100}%`, backgroundColor: stageMeta(p.stage).color }} />
                  </div>
                </button>
              ))}
            </div>
          </Card>

          <Card>
            <CardHeader title="Keep your data healthy" />
            <div className="px-5 py-4 space-y-2 text-xs">
              <p className="text-white font-semibold">One owner. One next action.</p>
              <p className="text-[var(--text-muted)] mb-2">Every open lead should have an owner and a scheduled follow-up.</p>
              {[
                ["No status after 24 h", data.data_health.no_status_24h, "/crm/leads?tab=new"],
                ["Unassigned open leads", data.data_health.unassigned_open, "/crm/leads?tab=unassigned"],
                ["Open leads without a phone model", data.data_health.missing_model, "/crm/leads"],
                ["Leads without a phone number", data.data_health.missing_phone, "/crm/leads"],
                ["Statuses not in the list", data.data_health.unknown_status, "/crm/leads"],
              ].map(([label, n, to]) => (
                <Link key={label as string} to={to as string} className="flex justify-between hover:text-white text-[var(--text-secondary)]">
                  <span>{label}</span>
                  <span className={Number(n) ? "text-amber-400 font-semibold" : "text-emerald-400"}>{n}</span>
                </Link>
              ))}
              <Link to="/crm/leads" className="inline-flex items-center gap-1 text-blue-400 hover:underline pt-2">Review leads <ArrowRight size={12} /></Link>
            </div>
          </Card>
        </div>
      </div>
      <NewLeadDialog open={newLead} onClose={() => setNewLead(false)} onCreated={(l) => openLead(l.id)} />
    </ErrorBoundary>
  );
}
