import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useToast } from "@/components/shared/Toast";
import { useAliases, useAudit, useCrmMeta, useDataQuality, useIntegrations, useMapMetaForm, useMetaBackfill, useMetaForms, useSetAlias, useSetAvailability, useTeam } from "../api";
import { HOT_COLOR } from "../statusConfig";
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

const META_STATUS_COLOR: Record<string, string> = { created: "#10b981", merged: "#3b82f6", error: "#ef4444" };

function MetaLeadsCard({ meta }: { meta: any }) {
  const toast = useToast();
  const { data: forms } = useMetaForms();
  const { data: stores } = useQuery({ queryKey: ["stores"], queryFn: () => api.get<any[]>("/stores/") });
  const mapForm = useMapMetaForm();
  const backfill = useMetaBackfill();
  const [hours, setHours] = useState(24);
  const unmatched = forms?.forms.filter((f) => !f.store_id).length ?? 0;
  return (
    <Card>
      <CardHeader title="Meta lead forms (Facebook / Instagram webhook)"
        subtitle="Each new lead form submission arrives instantly, goes to the form's store team, and merges with its Google Sheet copy" />
      <div className="px-5 py-4 space-y-2 text-xs">
        <p className="text-[var(--text-secondary)]">
          Status: {meta.configured
            ? <span className="text-emerald-400 font-semibold">Ready</span>
            : <span className="text-amber-400 font-semibold">Not set up — add {meta.missing.join(", ")} to backend/.env and restart</span>}
        </p>
        <p className="text-[var(--text-secondary)]">Callback URL for Meta → Webhooks → Page → leadgen: <code className="text-white">{window.location.origin}{meta.endpoint}</code></p>
        <p className="text-[var(--text-muted)]">Last 7 days: {Object.entries(meta.last_7_days).map(([k, v]) => `${v} ${k}`).join(" · ") || "no leads yet"}.
          {" "}Answered “yes” to the pre-booking question → <span className="text-rose-400 font-semibold">Hot</span>.</p>
        {forms?.can_edit && (
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <span className="text-[var(--text-secondary)]">Import missed leads from the last</span>
            <select className={`${inlineInputCls} py-1 text-xs`} value={hours} onChange={(e) => setHours(Number(e.target.value))}>
              {[6, 24, 72, 168].map((h) => <option key={h} value={h}>{h < 48 ? `${h} hours` : `${h / 24} days`}</option>)}
            </select>
            <Button size="sm" loading={backfill.isPending} onClick={async () => {
              try {
                const r = await backfill.mutateAsync(hours);
                toast.success(`Checked ${r.seen} leads: ${r.created} new, ${r.merged} merged with the sheet, ${r.duplicate} already here${r.error ? `, ${r.error} failed` : ""}`);
              } catch (e) {
                toast.error(e instanceof Error ? e.message : "Import failed");
              }
            }}>Import</Button>
          </div>
        )}
      </div>
      {forms && forms.forms.length > 0 && (
        <div className="border-t border-[var(--border-subtle)]">
          <p className="px-5 pt-3 text-xs font-semibold text-white">
            Lead form → store {unmatched > 0 && <span className="text-amber-400 font-normal">· {unmatched} form{unmatched > 1 ? "s" : ""} not matched — their leads stay unassigned</span>}
          </p>
          <div className="divide-y divide-[var(--border-subtle)]">
            {forms.forms.map((f) => (
              <div key={f.form_id} className="px-5 py-2 text-xs flex flex-col sm:flex-row sm:items-center gap-2">
                <div className="flex-1 min-w-0">
                  <p className={`truncate ${f.store_id ? "text-white" : "text-amber-400"}`}>{f.form_name || f.form_id}</p>
                  <p className="text-[11px] text-[var(--text-muted)]">{f.leads} leads{f.last_lead_at ? ` · last ${fmtRelative(f.last_lead_at)}` : ""}{f.match_source === "auto" ? " · matched automatically" : ""}</p>
                </div>
                <select className={`${inlineInputCls} py-1 text-xs`} disabled={!forms.can_edit || mapForm.isPending}
                  value={f.store_id ?? ""} onChange={async (e) => {
                    const store_id = e.target.value ? Number(e.target.value) : null;
                    try {
                      const r = await mapForm.mutateAsync({ form_id: f.form_id, store_id });
                      toast.success(`Saved${r.routed_leads ? ` · ${r.routed_leads} waiting lead${r.routed_leads > 1 ? "s" : ""} assigned` : ""}`);
                    } catch (err) {
                      toast.error(err instanceof Error ? err.message : "Could not save");
                    }
                  }}>
                  <option value="">Not matched</option>
                  {(stores || []).filter((s) => s.is_active !== false).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </div>
            ))}
          </div>
        </div>
      )}
      {meta.recent.length > 0 && (
        <div className="divide-y divide-[var(--border-subtle)] border-t border-[var(--border-subtle)]">
          {meta.recent.map((r: any, i: number) => (
            <div key={i} className="px-5 py-2 text-xs flex flex-wrap items-center gap-2">
              <span className="text-[var(--text-muted)] w-28">{fmtDateTime(r.at)}</span>
              <Pill label={r.status} color={META_STATUS_COLOR[r.status] || "#94a3b8"} />
              {r.hot && <Pill label="Hot" color={HOT_COLOR} />}
              {r.lead_id ? <button onClick={() => openLead(r.lead_id)} className="text-blue-400 hover:underline cursor-pointer">{r.name || `Lead #${r.lead_id}`}</button>
                : <span className="text-white">{r.name || "—"}</span>}
              <span className="text-[var(--text-muted)]">{r.platform === "instagram" ? "Instagram" : "Facebook"} · {r.form || ""}{r.error ? ` · ${r.error}` : ""}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function IntegrationsTab() {
  const { data, isLoading } = useIntegrations();
  if (isLoading || !data) return <TableSkeleton />;
  return (
    <div className="space-y-4">
      <InfoNote>{data.direction}. Sync runs every {data.sync_interval_minutes} minute. Automation is {data.automation_enabled ? "on" : "off"}.
        {data.go_live && <> CRM tracking started {fmtDateTime(data.go_live, { withYear: true })}.</>}</InfoNote>
      {data.website && (
        <Card>
          <CardHeader title="Website bookings (webhook)"
            subtitle="Paid ₹99 bookings from the third-party website become premium leads" />
          <div className="px-5 py-4 space-y-2 text-xs">
            <p className="text-[var(--text-secondary)]">
              Status: {data.website.configured
                ? <span className="text-emerald-400 font-semibold">Ready</span>
                : <span className="text-amber-400 font-semibold">Not set up — add WEBSITE_WEBHOOK_KEY to backend/.env and restart</span>}
            </p>
            <p className="text-[var(--text-secondary)]">Webhook: <code className="text-white">POST {window.location.origin}{data.website.endpoint}</code></p>
            <p className="text-[var(--text-secondary)]">Store list for the website form: <code className="text-white">GET {window.location.origin}{data.website.stores_endpoint}</code></p>
            <p className="text-[var(--text-muted)]">Last 7 days: {Object.entries(data.website.last_7_days).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(" · ") || "no calls yet"}</p>
          </div>
          {data.website.recent.length > 0 && (
            <div className="divide-y divide-[var(--border-subtle)] border-t border-[var(--border-subtle)]">
              {data.website.recent.map((r: any, i: number) => (
                <div key={i} className="px-5 py-2 text-xs flex flex-wrap items-center gap-2">
                  <span className="text-[var(--text-muted)] w-28">{fmtDateTime(r.at)}</span>
                  <Pill label={r.status} color={r.status === "created" ? "#10b981" : r.status === "duplicate" ? "#94a3b8" : "#f59e0b"} />
                  {r.lead_id ? <button onClick={() => openLead(r.lead_id)} className="text-blue-400 hover:underline cursor-pointer">{r.name || `Lead #${r.lead_id}`}</button>
                    : <span className="text-white">{r.name || "—"}</span>}
                  <span className="text-[var(--text-muted)]">{r.store || ""} · {r.message}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}
      {data.meta && <MetaLeadsCard meta={data.meta} />}
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
