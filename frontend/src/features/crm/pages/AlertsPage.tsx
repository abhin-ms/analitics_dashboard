import { useState } from "react";
import { Link } from "react-router-dom";
import { Bell, CheckCircle2, MessageSquare } from "lucide-react";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useAckAlert, useAlerts } from "../api";
import { ALERT_KIND_LABELS } from "../statusConfig";
import type { CrmAlert } from "../types";
import { fmtDateTime } from "../format";
import { openLead } from "../components/LeadDrawer";
import { Button, Card, CardHeader, Empty, InfoNote, PageHeader, Pill } from "../components/ui";

const LEVEL = { 1: { label: "Owner", color: "#3b82f6" }, 2: { label: "Team leader", color: "#f59e0b" }, 3: { label: "Admin", color: "#ef4444" } } as const;

function AlertRow({ a }: { a: CrmAlert }) {
  const ack = useAckAlert();
  const level = LEVEL[(a.level as 1 | 2 | 3) || 1] || LEVEL[1];
  return (
    <div className={`flex flex-col sm:flex-row sm:items-center gap-3 px-5 py-4 ${a.resolved_at ? "opacity-60" : ""}`}>
      <span className="shrink-0 w-9 h-9 rounded-full flex items-center justify-center bg-blue-500/10 text-blue-400">
        {a.kind === "coaching" ? <MessageSquare size={16} /> : a.resolved_at ? <CheckCircle2 size={16} className="text-emerald-400" /> : <Bell size={16} />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-white flex flex-wrap items-center gap-2">
          {a.title}
          <Pill label={ALERT_KIND_LABELS[a.kind] || a.kind} color={level.color} />
          {a.resolved_at && <Pill label="Resolved" color="#10b981" />}
        </p>
        <p className="text-xs text-[var(--text-muted)]">
          {a.lead_name ? `${a.lead_name} · ` : ""}{fmtDateTime(a.created_at)} · routed to {level.label.toLowerCase()}
        </p>
        {a.body && <p className="text-xs text-[var(--text-secondary)] mt-0.5 whitespace-pre-line">{a.body}</p>}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {a.lead_id && <Button size="sm" variant="ghost" onClick={() => openLead(a.lead_id!)}>Open lead</Button>}
        {a.kind === "weekly_review" && <Link to="/crm/reports" className="text-xs text-blue-400 hover:underline px-2">View evidence</Link>}
        {!a.acknowledged_at && !a.resolved_at && <Button size="sm" loading={ack.isPending} onClick={() => ack.mutate(a.id)}>Acknowledge</Button>}
        {a.acknowledged_at && !a.resolved_at && <span className="text-[11px] text-[var(--text-muted)]">Acknowledged</span>}
      </div>
    </div>
  );
}

export default function AlertsPage() {
  const [state, setState] = useState<"open" | "all">("open");
  const { data, isLoading, error } = useAlerts(state);
  return (
    <ErrorBoundary>
      <div className="space-y-4 p-4 sm:p-6">
        <PageHeader title="Alerts and manager inbox" subtitle="Operational messages and coaching, separate from customer conversations."
          actions={<>
            <Button size="sm" onClick={() => setState(state === "open" ? "all" : "open")}>{state === "open" ? "Show resolved too" : "Only open"}</Button>
            <Link to="/crm/automation" className="text-xs text-blue-400 hover:underline">Report routing →</Link>
          </>} />
        <InfoNote>
          Route: the lead's owner first, then the team leader, then admin if still unresolved. In-app only; nothing is sent outside the app.
        </InfoNote>
        {isLoading ? <TableSkeleton /> : error ? (
          <p className="text-sm text-rose-400">{error instanceof Error ? error.message : "Could not load"}</p>
        ) : (
          <>
            <Card>
              <CardHeader title="Lead alerts" />
              {data!.lead_alerts.length === 0 ? <Empty>No lead alerts.</Empty> : (
                <div className="divide-y divide-[var(--border-subtle)]">{data!.lead_alerts.map((a) => <AlertRow key={a.id} a={a} />)}</div>
              )}
            </Card>
            <Card>
              <CardHeader title="Performance notifications" subtitle="Weekly reviews (Mondays, 9 AM) and coaching notes" />
              {data!.performance.length === 0 ? <Empty>No performance notifications.</Empty> : (
                <div className="divide-y divide-[var(--border-subtle)]">{data!.performance.map((a) => <AlertRow key={a.id} a={a} />)}</div>
              )}
            </Card>
            <p className="text-xs text-[var(--text-muted)]">
              Acknowledging an alert does not resolve it. Operational alerts clear when the underlying task is handled.
            </p>
          </>
        )}
      </div>
    </ErrorBoundary>
  );
}
