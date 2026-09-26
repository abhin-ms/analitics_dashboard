import { useState } from "react";
import { ChevronLeft, ChevronRight, Plus, Search } from "lucide-react";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useToast } from "@/components/shared/Toast";
import { useAppointments, useCreateAppointment, useCrmLeads, useCrmMeta, usePatchAppointment } from "../api";
import { ATTENDANCE } from "../statusConfig";
import type { CrmLead } from "../types";
import { addDaysKey, fmtDayLabel, fmtTime, todayIST } from "../format";
import { openLead } from "../components/LeadDrawer";
import { BookAppointmentDialog } from "../components/dialogs";
import { Button, Card, CardHeader, Modal, PageHeader, Pill, inputCls } from "../components/ui";

function PickLeadDialog({ open, onClose, onPick }: { open: boolean; onClose: () => void; onPick: (l: CrmLead) => void }) {
  const [q, setQ] = useState("");
  const { data } = useCrmLeads({ tab: "all", q, page_size: 20 });
  return (
    <Modal open={open} onClose={onClose} title="Book appointment · choose a lead">
      <div className="space-y-3">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input autoFocus className={`${inputCls} pl-8`} placeholder="Search name or phone" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="max-h-72 overflow-y-auto divide-y divide-[var(--border-subtle)]">
          {data?.items.map((l) => (
            <button key={l.id} onClick={() => onPick(l)} className="w-full text-left px-2 py-2 hover:bg-[var(--bg-card-hover)] cursor-pointer">
              <span className="text-sm text-white">{l.full_name}</span>
              <span className="block text-[11px] text-[var(--text-muted)]">{l.city} · {l.phone} · {l.status_label}</span>
            </button>
          ))}
        </div>
      </div>
    </Modal>
  );
}

export default function AppointmentsPage() {
  const toast = useToast();
  const { data: meta } = useCrmMeta();
  const isAgent = meta?.role === "Telecaller" || meta?.role === "Salesperson";
  const [start, setStart] = useState(todayIST());
  const [mine, setMine] = useState<boolean | undefined>(undefined);
  const { data, isLoading, error } = useAppointments(start, 3, mine);
  const patch = usePatchAppointment();
  const create = useCreateAppointment();
  const [picking, setPicking] = useState(false);
  const [booking, setBooking] = useState<CrmLead | null>(null);

  const setAttendance = async (item: NonNullable<typeof data>["columns"][number]["items"][number], attendance: string) => {
    try {
      if (item.id) {
        await patch.mutateAsync({ id: item.id, body: { attendance } });
      } else {
        // sheet appointment → becomes an app record the first time it's updated
        await create.mutateAsync({ lead_id: item.lead_id, scheduled_at: item.scheduled_at, purpose: item.purpose, attendance });
      }
      toast.success(`Attendance: ${ATTENDANCE.find((a) => a.key === attendance)?.label}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not update");
    }
  };

  return (
    <ErrorBoundary>
      <div className="space-y-4 p-4 sm:p-6">
        <PageHeader title="Appointments" subtitle="Confirm attendance and follow up on missed visits."
          actions={<Button variant="primary" onClick={() => setPicking(true)}><Plus size={15} />Book appointment</Button>} />
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => setStart(addDaysKey(start, -3))}><ChevronLeft size={14} /></Button>
          <Button size="sm" onClick={() => setStart(todayIST())}>Today</Button>
          <Button size="sm" onClick={() => setStart(addDaysKey(start, 3))}><ChevronRight size={14} /></Button>
          {!isAgent && (
            <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)] ml-2 cursor-pointer">
              <input type="checkbox" checked={!!(mine ?? false)} onChange={(e) => setMine(e.target.checked)} />Only my leads
            </label>
          )}
          {isAgent && (
            <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)] ml-2 cursor-pointer">
              <input type="checkbox" checked={mine === false} onChange={(e) => setMine(e.target.checked ? false : undefined)} />Whole city
            </label>
          )}
        </div>

        {isLoading ? <TableSkeleton /> : error ? (
          <p className="text-sm text-rose-400">{error instanceof Error ? error.message : "Could not load"}</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {data?.columns.map((col) => (
              <Card key={col.date}>
                <CardHeader title={fmtDayLabel(col.date)} subtitle={`${col.items.length} appointment${col.items.length === 1 ? "" : "s"}`} />
                <div className="p-4 space-y-3">
                  {col.items.length === 0 && <p className="text-sm text-[var(--text-muted)] text-center py-6">No appointments</p>}
                  {col.items.map((it) => {
                    const att = ATTENDANCE.find((a) => a.key === it.attendance) || ATTENDANCE[0];
                    return (
                      <div key={`${it.id ?? "s"}-${it.lead_id}`} className="rounded-xl border-l-4 border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-3 space-y-1.5"
                        style={{ borderLeftColor: att.color }}>
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-white">{it.has_time ? fmtTime(it.scheduled_at) : "Time not set"}</span>
                          {it.source === "sheet" && <Pill label="From sheet" color="#94a3b8" />}
                        </div>
                        <button onClick={() => openLead(it.lead_id)} className="text-sm font-medium text-blue-400 hover:underline cursor-pointer text-left">{it.lead_name}</button>
                        <p className="text-[11px] text-[var(--text-muted)]">{it.purpose} · {it.city}{it.owner_name ? ` · ${it.owner_name}` : ""}</p>
                        <label className="block">
                          <span className="block text-[11px] text-[var(--text-secondary)] mb-1">Attendance</span>
                          <select className={inputCls} value={it.attendance} onChange={(e) => setAttendance(it, e.target.value)}>
                            {ATTENDANCE.map((a) => <option key={a.key} value={a.key}>{a.label}</option>)}
                          </select>
                        </label>
                      </div>
                    );
                  })}
                </div>
              </Card>
            ))}
          </div>
        )}

        <Card>
          <CardHeader title="Appointment follow-through" />
          <div className="px-5 py-4 text-sm space-y-1">
            <p className="text-white">One place to confirm, reschedule and record attendance.</p>
            <p className="text-xs text-[var(--text-muted)]">
              A confirmation call is scheduled 2 hours before each appointment. Marking a no-show creates a call-back task to reschedule.
              Sheet appointment dates appear here as "From sheet"; updating their attendance saves them in the app.
            </p>
          </div>
        </Card>
      </div>
      <PickLeadDialog open={picking} onClose={() => setPicking(false)} onPick={(l) => { setPicking(false); setBooking(l); }} />
      {booking && <BookAppointmentDialog lead={booking} open onClose={() => setBooking(null)} />}
    </ErrorBoundary>
  );
}
