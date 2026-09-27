/** "Today" essentials on the main dashboard: tiles (optional), the alerts
 * inbox and the follow-ups to prioritise. Replaces the separate Today page. */
import { Link, useNavigate } from "react-router-dom";
import { Bell, PhoneCall } from "lucide-react";
import { useAuthStore } from "@/lib/authStore";
import { useAckAlert, useOverview } from "../api";
import { ALERT_KIND_LABELS } from "../statusConfig";
import { fmtDateTime } from "../format";
import { openLead } from "./LeadDrawer";
import { EmptyFollowups, FollowupRow } from "./shared";
import { Button, Card, CardHeader, Empty, Tile } from "./ui";

export function DashboardInbox({ mine, showTiles = false }: { mine?: boolean; showTiles?: boolean }) {
  const canSee = useAuthStore((s) => s.hasPermission("leads", "view"));
  const { data } = useOverview(mine);
  const ack = useAckAlert();
  const navigate = useNavigate();
  if (!canSee || !data) return null;
  return (
    <div className="space-y-4">
      {showTiles && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Tile label="First contact" value={data.tiles.first_contact_pending} hint="Awaiting a first call ↗" onClick={() => navigate("/leads?view=leads&list=new")} />
          <Tile label="Due today" value={data.tiles.due_today} hint="Next actions ↗" onClick={() => navigate("/leads?view=tasks")} />
          <Tile label="Overdue" value={data.tiles.overdue} hint="Needs attention ↗" color={data.tiles.overdue ? "#ef4444" : undefined} onClick={() => navigate("/leads?view=leads&list=overdue")} />
          <Tile label="Unassigned" value={data.tiles.unassigned} hint="Assign an owner ↗" color={data.tiles.unassigned ? "#f59e0b" : undefined} onClick={() => navigate("/leads?view=leads&list=unassigned")} />
        </div>
      )}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card>
          <CardHeader title="Inbox" icon={<Bell size={15} className="text-blue-400" />}
            action={<Link to="/crm/alerts" className="text-xs text-blue-400 hover:underline">All alerts ({data.inbox.total}) →</Link>} />
          {data.inbox.items.length === 0 ? <Empty>No open alerts.</Empty> : (
            <div className="divide-y divide-[var(--border-subtle)]">
              {data.inbox.items.map((a) => (
                <div key={a.id} className="flex flex-col sm:flex-row sm:items-center gap-2 px-5 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-white">{a.title}</p>
                    <p className="text-xs text-[var(--text-muted)]">{ALERT_KIND_LABELS[a.kind] || a.kind} · {fmtDateTime(a.created_at)}{a.lead_name ? ` · ${a.lead_name}` : ""}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {a.lead_id && <Button size="sm" variant="ghost" onClick={() => openLead(a.lead_id!)}>Open lead</Button>}
                    {!a.acknowledged_at ? <Button size="sm" onClick={() => ack.mutate(a.id)}>Acknowledge</Button>
                      : <span className="text-[11px] text-[var(--text-muted)]">Acknowledged</span>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card>
          <CardHeader title="Follow-ups to prioritise" icon={<PhoneCall size={15} className="text-blue-400" />}
            action={<Link to="/leads?view=tasks" className="text-xs text-blue-400 hover:underline">View all →</Link>} />
          {data.followups.length === 0 ? <EmptyFollowups text="Nothing pending." /> : (
            <div className="divide-y divide-[var(--border-subtle)]">
              {data.followups.map((f) => <FollowupRow key={f.id} f={f} showOwner={!data.mine} />)}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
