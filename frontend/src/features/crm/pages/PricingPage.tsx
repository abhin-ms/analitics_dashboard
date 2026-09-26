import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useToast } from "@/components/shared/Toast";
import { PriceRow, useDeletePriceRow, usePriceBook, useSavePriceRow } from "../api";
import { fmtINR } from "../format";
import { Button, Card, Empty, Field, InfoNote, Modal, PageHeader, inputCls } from "../components/ui";

function EditDialog({ row, coverages, onClose }: { row: PriceRow | null; coverages: string[]; onClose: () => void }) {
  const toast = useToast();
  const save = useSavePriceRow();
  const [model, setModel] = useState(row?.phone_model || "");
  const [service, setService] = useState(row?.service_type || "Screen repair");
  const [prices, setPrices] = useState<Record<string, string>>(
    Object.fromEntries(coverages.map((c) => [c, row?.prices[c] != null ? String(row.prices[c]) : ""])),
  );
  const [newCov, setNewCov] = useState("");
  return (
    <Modal open onClose={onClose} title={row ? `Edit rates · ${row.phone_model} · ${row.service_type}` : "Add price"}
      footer={<><Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!model.trim() || !service.trim()} loading={save.isPending} onClick={async () => {
          try {
            await save.mutateAsync({
              phone_model: model, service_type: service, prices,
              original_phone_model: row?.phone_model, original_service_type: row?.service_type,
            });
            toast.success("Price book updated");
            onClose();
          } catch (e) { toast.error(e instanceof Error ? e.message : "Could not save"); }
        }}>Save</Button></>}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Phone model"><input className={inputCls} value={model} onChange={(e) => setModel(e.target.value)} placeholder="iPhone 15" /></Field>
          <Field label="Service"><input className={inputCls} value={service} onChange={(e) => setService(e.target.value)} placeholder="Screen repair" /></Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {Object.keys(prices).map((c) => (
            <Field key={c} label={`${c} (₹)`}>
              <input className={inputCls} inputMode="numeric" value={prices[c]} placeholder="blank = review needed"
                onChange={(e) => setPrices({ ...prices, [c]: e.target.value })} />
            </Field>
          ))}
        </div>
        <div className="flex items-end gap-2">
          <Field label="Add a coverage type"><input className={inputCls} value={newCov} onChange={(e) => setNewCov(e.target.value)} placeholder="e.g. OneAssist" /></Field>
          <Button size="sm" disabled={!newCov.trim()} onClick={() => { setPrices({ ...prices, [newCov.trim()]: "" }); setNewCov(""); }}>Add</Button>
        </div>
      </div>
    </Modal>
  );
}

export default function PricingPage() {
  const { data, isLoading, error } = usePriceBook();
  const del = useDeletePriceRow();
  const toast = useToast();
  const [editing, setEditing] = useState<PriceRow | "new" | null>(null);

  return (
    <ErrorBoundary>
      <div className="space-y-4 p-4 sm:p-6">
        <PageHeader title="Phone model price book" subtitle="Standard and coverage prices · INR · phone model + service type"
          actions={data?.can_edit && <Button variant="primary" onClick={() => setEditing("new")}><Plus size={15} />Add price</Button>} />
        <InfoNote>
          {data?.can_edit
            ? "Replace these with your approved price list. A blank rate means a price review is needed. Third-party rates need provider eligibility to be confirmed."
            : "Read-only price list for quoting customers. A blank rate means the price is still under review — ask an admin to update rates."}
        </InfoNote>
        <Card>
          {isLoading ? <div className="p-5"><TableSkeleton /></div> : error ? (
            <p className="p-5 text-sm text-rose-400">{error instanceof Error ? error.message : "Could not load"}</p>
          ) : data!.rows.length === 0 ? (
            <Empty>No prices yet.{data!.can_edit ? " Use “Add price” to build the price book." : ""}</Empty>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="text-[11px] text-[var(--text-muted)] border-b border-[var(--border-subtle)]">
                  <th className="py-2.5 px-5 text-left font-semibold">Phone model / service</th>
                  {data!.coverages.map((c) => <th key={c} className="py-2.5 pr-4 text-left font-semibold">{c}</th>)}
                  {data!.can_edit && <th className="py-2.5 pr-5" />}
                </tr></thead>
                <tbody className="divide-y divide-[var(--border-subtle)]">
                  {data!.rows.map((r) => (
                    <tr key={`${r.phone_model}|${r.service_type}`} className="hover:bg-[var(--bg-card-hover)]">
                      <td className="py-3 px-5"><p className="text-white">{r.phone_model}</p><p className="text-[11px] text-[var(--text-muted)]">{r.service_type}</p></td>
                      {data!.coverages.map((c) => (
                        <td key={c} className="py-3 pr-4 text-[var(--text-secondary)]">{r.prices[c] != null ? fmtINR(r.prices[c]) : "—"}</td>
                      ))}
                      {data!.can_edit && (
                        <td className="py-3 pr-5 text-right whitespace-nowrap">
                          <Button size="sm" variant="ghost" onClick={() => setEditing(r)}>Edit rates</Button>
                          <button title="Remove" className="ml-1 text-[var(--text-muted)] hover:text-rose-400 cursor-pointer align-middle"
                            onClick={async () => {
                              if (!window.confirm(`Remove ${r.phone_model} · ${r.service_type} from the price book?`)) return;
                              await del.mutateAsync({ phone_model: r.phone_model, service_type: r.service_type });
                              toast.success("Removed");
                            }}><Trash2 size={14} /></button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <p className="text-xs text-[var(--text-muted)]">
          An open lead's potential value updates when its device details are saved. Converted sale values stay fixed.
        </p>
      </div>
      {editing && data && (
        <EditDialog row={editing === "new" ? null : editing} coverages={data.coverages} onClose={() => setEditing(null)} />
      )}
    </ErrorBoundary>
  );
}
