import { useState } from "react";
import { Link } from "react-router-dom";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useToast } from "@/components/shared/Toast";
import { useAliases, useAudit, useCrmMeta, useDataQuality, useIntegrations, useSetAlias, useSetAvailability, useTeam } from "../api";
import { fmtDateTime, fmtRelative } from "../format";
import { openLead } from "../components/LeadDrawer";
import { Button, Card, CardHeader, Empty, InfoNote, PageHeader, Pill, Tabs, inputCls, inlineInputCls } from "../components/ui";

function AccessTab() {
  const { data: team } = useTeam();
  const setAvail = useSetAvailability();
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Role permissions" subtitle="Enforced on the server" />
        <table className="w-full text-sm">
          <thead><tr className="text-[11px] text-[var(--text-muted)] border-b border-[var(--border-subtle)]">
            {["Role", "Lead access", "Reassign", "Export"].map((h) => <th key={h} className="py-2.5 px-5 text-left font-semibold">{h}</th>)}
          </tr></thead>
          <tbody className="divide-y divide-[var(--border-subtle)] text-[var(--text-secondary)]">
            <tr><td className="py-3 px-5 text-white">Telecaller</td><td className="px-5">All leads of their city sheets (default view: My leads)</td><td className="px-5">No</td><td className="px-5">No</td></tr>
            <tr><td className="py-3 px-5 text-white">Team leader</td><td className="px-5">Their city sheets' leads</td><td className="px-5">Within team</td><td className="px-5">With permission (leads:export)</td></tr>
            <tr><td className="py-3 px-5 text-white">Admin / CEO / COO / RM</td><td className="px-5">All records</td><td className="px-5">Yes</td><td className="px-5">With permission (Admin: yes)</td></tr>
          </tbody>
        </table>
        <div className="px-5 py-3 text-xs text-[var(--text-muted)] border-t border-[var(--border-subtle)]">
          Change permissions in <Link to="/settings/roles" className="text-blue-400 hover:underline">Roles & Permissions</Link>; change who is on which city in{" "}
          <Link to="/settings/sheet-assignments" className="text-blue-400 hover:underline">Sheet Assignments</Link>.
        </div>
      </Card>
      <Card>
        <CardHeader title="Telecallers and availability" subtitle="Away telecallers are skipped by automatic assignment" />
        {!team ? <div className="p-5"><TableSkeleton /></div> : team.agents.length === 0 ? <Empty>No telecallers on any city sheet yet.</Empty> : (
          <div className="divide-y divide-[var(--border-subtle)]">
            {team.agents.map((a) => (
              <div key={a.id} className="flex items-center justify-between px-5 py-3 text-sm">
                <div><p className="text-white">{a.name}</p><p className="text-[11px] text-[var(--text-muted)]">{a.role} · {a.sheets.join(", ") || "no city"} · {a.open_leads} open leads</p></div>
                <Button size="sm" disabled={!team.can_change} onClick={() => setAvail.mutate({ userId: a.id, available: !a.available })}>
                  {a.available ? <span className="text-emerald-400">Available</span> : <span className="text-amber-400">Away</span>}
                </Button>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function IntegrationsTab() {
  const { data, isLoading } = useIntegrations();
  if (isLoading || !data) return <TableSkeleton />;
  return (
    <div className="space-y-4">
      <InfoNote>{data.direction}. Sync runs every {data.sync_interval_minutes} minute. Automation is {data.automation_enabled ? "on" : "off"}.
        {data.go_live && <> CRM tracking started {fmtDateTime(data.go_live, { withYear: true })}.</>}</InfoNote>
      <Card>
        <CardHeader title="Meta lead sheets (Google Sheets)" />
        <div className="divide-y divide-[var(--border-subtle)]">
          {data.sheets.map((s: any) => (
            <div key={s.city} className="px-5 py-3 text-sm flex flex-col sm:flex-row sm:items-center gap-2">
              <div className="flex-1">
                <p className="text-white font-medium">{s.city}</p>
                <p className="text-[11px] text-[var(--text-muted)]">
                  {s.leads} leads from the sheet{s.app_only_leads ? ` · ${s.app_only_leads} app-only` : ""} · {s.people.length} people ·{" "}
                  {s.people.map((p: any) => p.name).join(", ") || "nobody assigned"}
                </p>
              </div>
              <div className="text-xs text-right">
                {s.last_run ? (
                  s.last_run.ok
                    ? <Pill label={`Synced ${fmtRelative(s.last_run.at)} · ${s.last_run.inserted ?? 0} new`} color="#10b981" />
                    : <Pill label={`Failed ${fmtRelative(s.last_run.at)}`} color="#ef4444" />
                ) : <span className="text-[var(--text-muted)]">Last row sync {s.last_synced_at ? fmtRelative(s.last_synced_at) : "never"}</span>}
                {s.last_run?.error && <p className="text-[11px] text-rose-400 mt-1 max-w-xs">{s.last_run.error}</p>}
              </div>
            </div>
          ))}
        </div>
      </Card>
      <Card>
        <CardHeader title="Messaging" />
        <div className="px-5 py-4 text-xs text-[var(--text-muted)]">WhatsApp messaging is planned for a later phase. No messages are sent from the app today.</div>
      </Card>
    </div>
  );
}

function DataQualityTab() {
  const toast = useToast();
  const { data: meta } = useCrmMeta();
  const { data, isLoading } = useDataQuality();
  const { data: aliases } = useAliases();
  const setAlias = useSetAlias();
  const [pick, setPick] = useState<Record<string, string>>({});
  if (isLoading || !data) return <TableSkeleton />;
  const list = (title: string, block: { count: number; items: any[] }, hint: string) => (
    <Card>
      <CardHeader title={`${title} · ${block.count}`} subtitle={hint} />
      {block.items.length === 0 ? <Empty>All good.</Empty> : (
        <div className="divide-y divide-[var(--border-subtle)] max-h-72 overflow-y-auto">
          {block.items.map((l: any) => (
            <button key={l.id} onClick={() => openLead(l.id)} className="w-full text-left px-5 py-2 text-xs hover:bg-[var(--bg-card-hover)] cursor-pointer flex justify-between gap-3">
              <span className="text-blue-400">{l.full_name}</span>
              <span className="text-[var(--text-muted)]">{l.city} · {l.phone || "no phone"} · {l.created_time || "—"} · {l.status}</span>
            </button>
          ))}
        </div>
      )}
    </Card>
  );
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={`"Person Calling" names that match no user · ${data.unmatched_names.length}`}
          subtitle="Map a sheet name to an app user so those leads get an owner (applied on the next sync)." />
        {data.unmatched_names.length === 0 ? <Empty>Every name in the sheets matches a user.</Empty> : (
          <div className="divide-y divide-[var(--border-subtle)]">
            {data.unmatched_names.map((n: any) => {
              const key = `${n.name}|${n.city}`;
              const people = (meta?.people || []).filter((p) => p.sheets.includes(n.city));
              return (
                <div key={key} className="px-5 py-2.5 flex flex-col sm:flex-row sm:items-center gap-2 text-xs">
                  <span className="flex-1 text-white">“{n.name}” <span className="text-[var(--text-muted)]">· {n.city} · {n.count} leads</span></span>
                  {data.can_fix_aliases && (
                    <div className="flex gap-2">
                      <select className={`${inlineInputCls} py-1 text-xs`} value={pick[key] || ""} onChange={(e) => setPick({ ...pick, [key]: e.target.value })}>
                        <option value="">Map to…</option>
                        {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                      <Button size="sm" disabled={!pick[key]} onClick={async () => {
                        await setAlias.mutateAsync({ alias: n.name, user_id: Number(pick[key]) });
                        toast.success(`“${n.name}” → mapped. Owners update within a minute.`);
                      }}>Save</Button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
        {(aliases?.aliases.length ?? 0) > 0 && (
          <div className="px-5 py-3 border-t border-[var(--border-subtle)] text-xs text-[var(--text-muted)] flex flex-wrap gap-2">
            Existing mappings:
            {aliases!.aliases.map((a) => (
              <span key={a.alias} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border-subtle)] px-2 py-0.5">
                “{a.alias}” → {a.user_name || a.user_id}
                {data.can_fix_aliases && <button className="hover:text-rose-400 cursor-pointer" onClick={() => setAlias.mutate({ alias: a.alias, user_id: null })}>×</button>}
              </span>
            ))}
          </div>
        )}
      </Card>
      <Card>
        <CardHeader title={`Statuses not in the list · ${data.unknown_statuses.length}`} subtitle="Kept as typed in the sheet. Fix the spelling in the sheet or update the lead." />
        {data.unknown_statuses.length === 0 ? <Empty>All statuses match the list.</Empty> : (
          <div className="px-5 py-3 flex flex-wrap gap-2">{data.unknown_statuses.map((s: any) => <Pill key={s.status} label={`${s.status} · ${s.count}`} color="#94a3b8" />)}</div>
        )}
      </Card>
      <Card>
        <CardHeader title={`Possible duplicates · ${data.duplicates.count}`} subtitle="Same city and phone number" />
        {data.duplicates.items.length === 0 ? <Empty>No duplicates found.</Empty> : (
          <div className="divide-y divide-[var(--border-subtle)] max-h-72 overflow-y-auto">
            {data.duplicates.items.map((d: any) => (
              <div key={`${d.city}${d.phone}`} className="px-5 py-2 text-xs flex flex-wrap gap-2 items-center">
                <span className="text-[var(--text-muted)]">{d.city} · …{d.phone.slice(-4)}:</span>
                {d.leads.map((l: any) => <button key={l.id} onClick={() => openLead(l.id)} className="text-blue-400 hover:underline cursor-pointer">{l.full_name}</button>)}
              </div>
            ))}
          </div>
        )}
      </Card>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {list("No status after 24 hours", data.no_status_24h, "Nobody has recorded a first contact")}
        {list("Unassigned open leads", data.unassigned_open, "Assign an owner")}
        {list("Created time not readable", data.unparseable_created_time, "Check the date format in the sheet")}
        {list("Missing phone number", data.missing_phone, "Cannot be called")}
        {list("Open leads without a phone model", data.missing_model, "Needed for potential value")}
      </div>
    </div>
  );
}

function AuditTab() {
  const { data, isLoading } = useAudit();
  if (isLoading || !data) return <TableSkeleton />;
  return (
    <Card>
      <CardHeader title="Audit history" subtitle="Reassignments, lead edits by team leaders/admins, exports, price and settings changes" />
      {data.items.length === 0 ? <Empty>No changes recorded yet.</Empty> : (
        <div className="divide-y divide-[var(--border-subtle)]">
          {data.items.map((r) => (
            <div key={r.id} className="px-5 py-2.5 text-xs flex flex-col sm:flex-row gap-1 sm:gap-3">
              <span className="text-[var(--text-muted)] w-36 shrink-0">{fmtDateTime(r.at, { withYear: true })}</span>
              <span className="text-white w-28 shrink-0">{r.user}</span>
              <span className="text-[var(--text-secondary)] flex-1 break-all">
                {r.action} · {r.resource}{r.resource_id ? ` #${r.resource_id}` : ""}
                {r.after ? ` · ${JSON.stringify(r.after).slice(0, 160)}` : ""}
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

export default function CrmSettingsPage() {
  const [tab, setTab] = useState("access");
  const { data: meta } = useCrmMeta();
  const isAdmin = meta && ["SuperAdmin", "Admin", "CEO", "COO", "Regional Manager"].includes(meta.role);
  const tabs = [
    { key: "access", label: "Access & team" },
    { key: "integrations", label: "Integrations" },
    { key: "quality", label: "Data quality" },
    ...(isAdmin ? [{ key: "audit", label: "Audit history" }] : []),
  ];
  return (
    <ErrorBoundary>
      <div className="space-y-4 p-4 sm:p-6">
        <PageHeader title="Telecalling settings" subtitle="Access, integrations and data quality in one place." />
        <Tabs tabs={tabs} value={tab} onChange={setTab} />
        {tab === "access" && <AccessTab />}
        {tab === "integrations" && <IntegrationsTab />}
        {tab === "quality" && <DataQualityTab />}
        {tab === "audit" && <AuditTab />}
      </div>
    </ErrorBoundary>
  );
}
