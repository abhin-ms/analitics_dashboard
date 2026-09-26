import { useState } from "react";
import { Plus, Search } from "lucide-react";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useToast } from "@/components/shared/Toast";
import { useCrmMeta, usePatchLead, usePipeline } from "../api";
import { STAGES, stageMeta } from "../statusConfig";
import type { CrmLead } from "../types";
import { fmtDue, fmtINR, fmtINRShort } from "../format";
import { openLead } from "../components/LeadDrawer";
import { NewLeadDialog } from "../components/dialogs";
import { Button, PageHeader, PriorityBadge, inputCls, inlineInputCls } from "../components/ui";

function LeadCard({ lead }: { lead: CrmLead }) {
  const toast = useToast();
  const patch = usePatchLead();
  const [menu, setMenu] = useState(false);
  const due = fmtDue(lead.next_follow_up_at);
  const value = lead.stage === "converted" && lead.sale_amount_value ? lead.sale_amount_value : lead.potential_value;
  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-3 space-y-1.5">
      <button onClick={() => openLead(lead.id)} className="text-sm font-medium text-blue-400 hover:underline cursor-pointer text-left">
        {lead.full_name}
      </button>
      <p className="text-[11px] text-[var(--text-muted)]">{lead.service_type || "Service to confirm"}{lead.phone_model ? ` · ${lead.phone_model}` : ""}</p>
      <div className="flex items-center justify-between">
        <span className="text-sm text-white">{value != null ? fmtINR(value) : "Price pending"}</span>
        <PriorityBadge priority={lead.priority} />
      </div>
      <p className="text-[11px] text-[var(--text-muted)]">
        {lead.owner_name || "Unassigned"} · <span className={due.overdue ? "text-rose-400" : ""}>{due.text}</span>
      </p>
      <div className="relative">
        <button onClick={() => setMenu(!menu)} className="text-xs text-blue-400 hover:underline cursor-pointer">Change stage →</button>
        {menu && (
          <div className="absolute z-10 mt-1 w-48 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-card)] shadow-xl py-1">
            {STAGES.filter((s) => s.key !== lead.stage).map((s) => (
              <button key={s.key} className="w-full text-left px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-card-hover)] hover:text-white cursor-pointer"
                onClick={async () => {
                  setMenu(false);
                  try {
                    await patch.mutateAsync({ leadId: lead.id, body: { stage: s.key } });
                    toast.success(`${lead.full_name} → ${s.label}`);
                  } catch (e) {
                    toast.error(e instanceof Error ? e.message : "Could not change stage");
                  }
                }}>
                {s.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function PipelinePage() {
  const { data: meta } = useCrmMeta();
  const [mine, setMine] = useState(false);
  const [sheet, setSheet] = useState("");
  const [q, setQ] = useState("");
  const { data, isLoading, error } = usePipeline({ mine, sheet, q });
  const [newLead, setNewLead] = useState(false);

  return (
    <ErrorBoundary>
      <div className="space-y-4 p-4 sm:p-6">
        <PageHeader
          title="Sales pipeline"
          subtitle="Will Visit = Warm · Paid Advance = Hot · Sale Conversion = Converted Customer"
          actions={<Button variant="primary" onClick={() => setNewLead(true)}><Plus size={15} />New lead</Button>}
        />
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-full sm:w-64">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
            <input className={`${inputCls} pl-8`} placeholder="Search name, phone or model" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {(meta?.sheets.length ?? 0) > 1 && (
            <select className={`${inlineInputCls}`} value={sheet} onChange={(e) => setSheet(e.target.value)}>
              <option value="">All cities</option>
              {meta?.sheets.map((s) => <option key={s}>{s}</option>)}
            </select>
          )}
          <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)] cursor-pointer">
            <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />Only my leads
          </label>
        </div>

        {isLoading ? <TableSkeleton /> : error ? (
          <p className="text-sm text-rose-400">{error instanceof Error ? error.message : "Could not load"}</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            {data?.columns.map((col) => (
              <div key={col.stage} className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-4 flex flex-col">
                <div className="flex items-start justify-between mb-1">
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: stageMeta(col.stage).color }} />{col.label}
                  </h3>
                  <span className="text-[11px] px-2 py-0.5 rounded-lg bg-blue-500/10 text-blue-400 font-semibold">{col.count}</span>
                </div>
                <p className="text-xs text-[var(--text-muted)] mb-3">{fmtINRShort(col.value)}</p>
                <div className="space-y-2 max-h-[560px] overflow-y-auto pr-1">
                  {col.cards.length === 0 && <p className="text-xs text-[var(--text-muted)] py-4 text-center">No leads</p>}
                  {col.cards.map((l) => <LeadCard key={l.id} lead={l} />)}
                  {col.count > col.cards.length && (
                    <p className="text-[11px] text-[var(--text-muted)] text-center pt-1">+{col.count - col.cards.length} more — use Leads to see all</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      <NewLeadDialog open={newLead} onClose={() => setNewLead(false)} onCreated={(l) => openLead(l.id)} />
    </ErrorBoundary>
  );
}
