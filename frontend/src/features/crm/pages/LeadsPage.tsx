import { Fragment, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Plus, Search, Columns3, Bookmark, Download, UserCog, ChevronLeft, ChevronRight, Trash2, Flame } from "lucide-react";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useToast } from "@/components/shared/Toast";
import {
  downloadExport, useCrmLeads, useCrmMeta, useDeleteView, useSaveView, useSavedViews,
} from "../api";
import { PRIORITIES, STAGES, stageMeta } from "../statusConfig";
import type { CrmLead } from "../types";
import { fmtDateTime, fmtDue, fmtINR } from "../format";
import { openLead } from "../components/LeadDrawer";
import { AssignDialog, LogActivityDialog, NewLeadDialog } from "../components/dialogs";
import { StatusChips } from "../components/shared";
import { Button, Card, Empty, Modal, PageHeader, Pill, PriorityBadge, StageBadge, Tabs, inputCls, inlineInputCls, Field } from "../components/ui";

const ALL_COLUMNS = [
  { key: "owner", label: "Owner" },
  { key: "progress", label: "Progress / contact status" },
  { key: "followup", label: "Next follow-up" },
  { key: "priority", label: "Priority" },
  { key: "value", label: "Potential value" },
  { key: "city", label: "City" },
  { key: "received", label: "Received" },
] as const;
const DEFAULT_COLUMNS = ["owner", "progress", "followup", "priority", "value"];
const COLS_KEY = "crm.leads.columns";
const FILTER_KEYS = ["tab", "status", "stage", "owner", "sheet", "priority", "q", "group_by", "sort"] as const;

function loadColumns(): string[] {
  try {
    const raw = localStorage.getItem(COLS_KEY);
    return raw ? JSON.parse(raw) : DEFAULT_COLUMNS;
  } catch {
    return DEFAULT_COLUMNS;
  }
}

function groupKey(l: CrmLead, by: string): string {
  if (by === "owner") return l.owner_name || "Unassigned";
  if (by === "stage") return stageMeta(l.stage).label;
  if (by === "status") return l.status_label;
  if (by === "city") return l.city;
  if (by === "priority") return l.priority;
  return "";
}

export default function LeadsPage() {
  const toast = useToast();
  const { data: meta } = useCrmMeta();
  const [sp, setSp] = useSearchParams();
  const isAgent = meta?.role === "Telecaller" || meta?.role === "Salesperson";
  const tab = sp.get("tab") || (isAgent ? "mine" : "all");
  const page = Number(sp.get("page") || 1);
  const params = {
    tab, page, page_size: 50,
    status: sp.get("status") || "", stage: sp.get("stage") || "", owner: sp.get("owner") || "",
    sheet: sp.get("sheet") || "", priority: sp.get("priority") || "", q: sp.get("q") || "",
    group_by: sp.get("group_by") || "", sort: sp.get("sort") || "smart",
  };
  const { data, isLoading, isFetching, error } = useCrmLeads(params);
  const [search, setSearch] = useState(params.q);
  const [columns, setColumns] = useState<string[]>(loadColumns);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [dialog, setDialog] = useState<"" | "new" | "assign" | "columns" | "save">("");
  const [logLead, setLogLead] = useState<CrmLead | null>(null);
  const [viewName, setViewName] = useState("");
  const { data: views } = useSavedViews("leads");
  const saveView = useSaveView();
  const deleteView = useDeleteView();

  useEffect(() => setSearch(params.q), [params.q]);
  useEffect(() => {
    try { localStorage.setItem(COLS_KEY, JSON.stringify(columns)); } catch { /* private mode */ }
  }, [columns]);
  useEffect(() => setSelected(new Set()), [sp]);

  // debounce search into the URL
  useEffect(() => {
    const t = setTimeout(() => { if (search !== params.q) update({ q: search }); }, 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  function update(patch: Record<string, string>) {
    const next = new URLSearchParams(sp);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    if (!("page" in patch)) next.delete("page");
    setSp(next, { replace: true });
  }

  const items = data?.items || [];
  const selectedLeads = items.filter((l) => selected.has(l.id));
  const show = (c: string) => columns.includes(c);
  const grouped = useMemo(() => {
    if (!params.group_by) return null;
    const m = new Map<string, CrmLead[]>();
    items.forEach((l) => {
      const k = groupKey(l, params.group_by);
      m.set(k, [...(m.get(k) || []), l]);
    });
    return [...m.entries()];
  }, [items, params.group_by]);
  const groupTotals = useMemo(() => new Map((data?.groups || []).map((g) => [String(g.label), g.count])), [data?.groups]);

  const tabDefs = [
    { key: "all", label: "All leads" }, { key: "mine", label: "My leads" }, { key: "today", label: "Today" },
    { key: "overdue", label: "Overdue" }, { key: "unassigned", label: "Unassigned" }, { key: "new", label: "New" },
  ].map((t) => ({ key: t.key, label: <>{t.label}{data?.tab_counts?.[t.key] != null && <span className="ml-1 text-[11px] opacity-70">{data.tab_counts[t.key]}</span>}</> }));

  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const colCount = 2 + ALL_COLUMNS.filter((c) => show(c.key)).length + 1;

  const row = (l: CrmLead) => {
    const due = fmtDue(l.next_follow_up_at);
    return (
      <tr key={l.id} className="hover:bg-[var(--bg-card-hover)] align-top">
        <td className="py-3 pl-4 pr-2">
          <input type="checkbox" checked={selected.has(l.id)}
            onChange={(e) => {
              const next = new Set(selected);
              if (e.target.checked) next.add(l.id); else next.delete(l.id);
              setSelected(next);
            }} />
        </td>
        <td className="py-3 pr-3 min-w-[180px]">
          <button onClick={() => openLead(l.id)} className="text-sm font-medium text-blue-400 hover:underline cursor-pointer text-left">
            {l.full_name}
          </button>
          {l.is_urgent && <Flame size={12} className="inline ml-1 text-rose-400" />}
          <p className="text-[11px] text-[var(--text-muted)]">{l.city} · {l.lead_source || "—"}</p>
          {l.phone_model
            ? <p className="text-xs text-blue-300">{l.phone_model}</p>
            : <button onClick={() => openLead(l.id)} className="text-xs text-blue-400 hover:underline cursor-pointer">+ Add phone model</button>}
          {(l.service_type || l.coverage) && <p className="text-[11px] text-[var(--text-muted)]">{l.service_type || "Add service"} · {l.coverage || "Not confirmed"}</p>}
        </td>
        {show("owner") && (
          <td className="py-3 pr-3 text-xs">
            <span className={l.owner_name ? "text-white" : "text-amber-400"}>{l.owner_name || "Unassigned"}</span>
            {l.first_call_pending && <p className="text-[11px] text-blue-400">Call within {meta?.automation.first_call_minutes ?? 5} minutes</p>}
          </td>
        )}
        {show("progress") && (
          <td className="py-3 pr-3">
            <StageBadge stage={l.stage} />
            <p className="text-[11px] text-[var(--text-secondary)] mt-1">{l.status_label}</p>
          </td>
        )}
        {show("followup") && (
          <td className="py-3 pr-3 text-xs whitespace-nowrap">
            <span className={due.overdue ? "text-rose-400 font-semibold" : "text-white"}>{due.text}</span>
            <p className="text-[11px] text-[var(--text-muted)]">Last: {l.last_contact_at ? fmtDateTime(l.last_contact_at) : "Not contacted"}</p>
          </td>
        )}
        {show("priority") && <td className="py-3 pr-3"><PriorityBadge priority={l.priority} /></td>}
        {show("value") && (
          <td className="py-3 pr-3 text-xs whitespace-nowrap">
            {l.stage === "converted" && l.sale_amount_value
              ? <><span className="text-emerald-400 font-semibold">{fmtINR(l.sale_amount_value)}</span><p className="text-[11px] text-[var(--text-muted)]">Sale amount</p></>
              : l.potential_value != null
                ? <><span className="text-white">{fmtINR(l.potential_value)}</span><p className="text-[11px] text-[var(--text-muted)]">Model + service price</p></>
                : <><span className="text-[var(--text-secondary)]">Price pending</span><p className="text-[11px] text-[var(--text-muted)]">{l.phone_model ? "Price review needed" : "Model needed"}</p></>}
          </td>
        )}
        {show("city") && <td className="py-3 pr-3 text-xs text-[var(--text-secondary)]">{l.city}</td>}
        {show("received") && <td className="py-3 pr-3 text-xs text-[var(--text-secondary)] whitespace-nowrap">{fmtDateTime(l.submitted_at || l.received_at)}</td>}
        <td className="py-3 pr-4 text-right">
          <Button size="sm" variant="ghost" onClick={() => setLogLead(l)}>Log</Button>
        </td>
      </tr>
    );
  };

  const card = (l: CrmLead) => {
    const due = fmtDue(l.next_follow_up_at);
    return (
      <div key={l.id} className="px-4 py-3 space-y-1.5">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <button onClick={() => openLead(l.id)} className="font-semibold text-blue-400 truncate cursor-pointer text-left">{l.full_name}</button>
            <p className="text-[11px] text-[var(--text-muted)]">{l.city} · {l.owner_name || "Unassigned"}{l.phone_model ? ` · ${l.phone_model}` : ""}</p>
          </div>
          <PriorityBadge priority={l.priority} />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <StageBadge stage={l.stage} />
          <Pill label={l.status_label} color="#94a3b8" />
          {l.first_call_pending && <Pill label="Call within 5 min" color="#3b82f6" />}
        </div>
        <div className="flex items-center justify-between">
          <span className={`text-xs ${due.overdue ? "text-rose-400 font-semibold" : "text-[var(--text-secondary)]"}`}>{due.text}</span>
          <Button size="sm" onClick={() => setLogLead(l)}>Log</Button>
        </div>
      </div>
    );
  };

  return (
    <ErrorBoundary>
      <div className="space-y-4 p-4 sm:p-6">
        <PageHeader
          title="Leads"
          subtitle="Update contact status first. Will Visit is Warm; Paid Advance is Hot."
          actions={<>
            {meta?.can.export && (
              <Button size="sm" onClick={async () => {
                try { await downloadExport({ status: params.status, sheet: params.sheet }); }
                catch (e) { toast.error(e instanceof Error ? e.message : "Export failed"); }
              }}><Download size={14} />Export</Button>
            )}
            <Button variant="primary" onClick={() => setDialog("new")}><Plus size={15} />New lead</Button>
          </>}
        />

        {data && <StatusChips counts={data.status_counts} value={params.status === "" ? "" : params.status}
          onChange={(s) => update({ status: s })} />}

        <Tabs tabs={tabDefs} value={tab} onChange={(t) => update({ tab: t })} />

        <div className="flex flex-col lg:flex-row lg:items-center gap-2">
          <div className="relative flex-1 min-w-[200px]">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input className={`${inputCls} pl-8`} placeholder="Search name, phone or model" value={search}
              onChange={(e) => setSearch(e.target.value)} />
          </div>
          <div className="flex flex-wrap gap-2">
            <select className={`${inlineInputCls}`} value={params.owner} onChange={(e) => update({ owner: e.target.value })}>
              <option value="">All owners</option>
              <option value="me">Me</option>
              <option value="none">Unassigned</option>
              {meta?.people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <select className={`${inlineInputCls}`} value={params.stage} onChange={(e) => update({ stage: e.target.value })}>
              <option value="">All stages</option>
              {STAGES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
            <select className={`${inlineInputCls}`} value={params.priority} onChange={(e) => update({ priority: e.target.value })}>
              <option value="">Any priority</option>
              {PRIORITIES.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
            </select>
            {(meta?.sheets.length ?? 0) > 1 && (
              <select className={`${inlineInputCls}`} value={params.sheet} onChange={(e) => update({ sheet: e.target.value })}>
                <option value="">All cities</option>
                {meta?.sheets.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            )}
            <Button onClick={() => setDialog("columns")}><Columns3 size={14} />Columns</Button>
            <Button onClick={() => { setViewName(""); setDialog("save"); }}><Bookmark size={14} />Save view</Button>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--text-muted)]">
          <div className="flex flex-wrap items-center gap-2">
            <span>{data?.total ?? 0} leads · {selected.size} selected{isFetching ? " · updating…" : ""}</span>
            {selected.size > 0 && meta?.can.reassign && (
              <Button size="sm" onClick={() => setDialog("assign")}><UserCog size={13} />Assign selected</Button>
            )}
            {(views?.views.length ?? 0) > 0 && (
              <span className="flex flex-wrap items-center gap-1">
                Views:
                {views!.views.map((v) => (
                  <span key={v.id} className="inline-flex items-center rounded-lg border border-[var(--border-subtle)]">
                    <button className="px-2 py-0.5 hover:text-white cursor-pointer" onClick={() => {
                      const next = new URLSearchParams();
                      FILTER_KEYS.forEach((k) => v.filters[k] && next.set(k, v.filters[k]));
                      setSp(next);
                      if (v.columns?.length) setColumns(v.columns);
                    }}>{v.name}</button>
                    <button title="Delete view" className="px-1 hover:text-rose-400 cursor-pointer" onClick={() => deleteView.mutate(v.id)}><Trash2 size={11} /></button>
                  </span>
                ))}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <span>Sort</span>
            <select className={`${inlineInputCls} py-1 text-xs`} value={params.sort} onChange={(e) => update({ sort: e.target.value })}>
              <option value="smart">Urgent & due first</option>
              <option value="newest">Newest</option>
              <option value="oldest">Oldest</option>
              <option value="value">Highest value</option>
              <option value="name">Name</option>
            </select>
            <span>Group by</span>
            <select className={`${inlineInputCls} py-1 text-xs`} value={params.group_by} onChange={(e) => update({ group_by: e.target.value })}>
              <option value="">None</option>
              <option value="owner">Owner</option>
              <option value="stage">Stage</option>
              <option value="status">Status</option>
              <option value="priority">Priority</option>
              <option value="city">City</option>
            </select>
          </div>
        </div>

        <Card>
          {isLoading ? <div className="p-5"><TableSkeleton /></div> : error ? (
            <p className="p-5 text-sm text-rose-400">{error instanceof Error ? error.message : "Could not load leads"}</p>
          ) : items.length === 0 ? <Empty>No leads match these filters.</Empty> : (
            <>
              <div className="md:hidden divide-y divide-[var(--border-subtle)]">
                {grouped
                  ? grouped.map(([g, ls]) => (
                    <Fragment key={g}>
                      <p className="px-4 py-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)] bg-[var(--bg-primary)]">{g}</p>
                      {ls.map(card)}
                    </Fragment>))
                  : items.map(card)}
              </div>
              <div className="hidden md:block overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-[11px] text-[var(--text-muted)] border-b border-[var(--border-subtle)]">
                      <th className="py-2.5 pl-4 pr-2 text-left">
                        <input type="checkbox" checked={items.length > 0 && selected.size === items.length}
                          onChange={(e) => setSelected(e.target.checked ? new Set(items.map((l) => l.id)) : new Set())} />
                      </th>
                      <th className="py-2.5 pr-3 text-left font-semibold">Customer</th>
                      {ALL_COLUMNS.filter((c) => show(c.key)).map((c) => (
                        <th key={c.key} className="py-2.5 pr-3 text-left font-semibold">{c.label}</th>
                      ))}
                      <th className="py-2.5 pr-4 text-right font-semibold">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border-subtle)]">
                    {grouped
                      ? grouped.map(([g, ls]) => (
                        <Fragment key={g}>
                          <tr className="bg-[var(--bg-primary)]">
                            <td colSpan={colCount} className="px-4 py-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
                              {g} <span className="normal-case font-normal">· {groupTotals.get(g) ?? ls.length} in total</span>
                            </td>
                          </tr>
                          {ls.map(row)}
                        </Fragment>))
                      : items.map(row)}
                  </tbody>
                </table>
              </div>
              {pages > 1 && (
                <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--border-subtle)] text-xs text-[var(--text-muted)]">
                  <span>Page {page} of {pages}</span>
                  <div className="flex gap-2">
                    <Button size="sm" disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}><ChevronLeft size={13} />Prev</Button>
                    <Button size="sm" disabled={page >= pages} onClick={() => update({ page: String(page + 1) })}>Next<ChevronRight size={13} /></Button>
                  </div>
                </div>
              )}
            </>
          )}
        </Card>
      </div>

      <NewLeadDialog open={dialog === "new"} onClose={() => setDialog("")} onCreated={(l) => openLead(l.id)} />
      {dialog === "assign" && <AssignDialog leads={selectedLeads} open onClose={() => setDialog("")} onDone={() => setSelected(new Set())} />}
      {logLead && <LogActivityDialog lead={logLead} open onClose={() => setLogLead(null)} />}
      <Modal open={dialog === "columns"} onClose={() => setDialog("")} title="Columns"
        footer={<><Button onClick={() => setColumns(DEFAULT_COLUMNS)}>Reset</Button><Button variant="primary" onClick={() => setDialog("")}>Done</Button></>}>
        <div className="space-y-2">
          {ALL_COLUMNS.map((c) => (
            <label key={c.key} className="flex items-center gap-2 text-sm text-[var(--text-secondary)] cursor-pointer">
              <input type="checkbox" checked={show(c.key)}
                onChange={(e) => setColumns(e.target.checked ? [...columns, c.key] : columns.filter((x) => x !== c.key))} />
              {c.label}
            </label>
          ))}
        </div>
      </Modal>
      <Modal open={dialog === "save"} onClose={() => setDialog("")} title="Save this view"
        footer={<><Button onClick={() => setDialog("")}>Cancel</Button>
          <Button variant="primary" disabled={!viewName.trim()} loading={saveView.isPending} onClick={async () => {
            const filters: Record<string, string> = {};
            FILTER_KEYS.forEach((k) => { const v = sp.get(k); if (v) filters[k] = v; });
            if (!filters.tab) filters.tab = tab;
            await saveView.mutateAsync({ name: viewName.trim(), page: "leads", filters, columns });
            toast.success("View saved");
            setDialog("");
          }}>Save</Button></>}>
        <Field label="Name" hint="Saves the current tab, filters, sort, grouping and columns.">
          <input className={inputCls} value={viewName} onChange={(e) => setViewName(e.target.value)} placeholder="e.g. Overdue Chennai" autoFocus />
        </Field>
      </Modal>
    </ErrorBoundary>
  );
}
