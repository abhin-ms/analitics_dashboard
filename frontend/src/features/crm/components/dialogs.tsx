import { useMemo, useState } from "react";
import { useToast } from "@/components/shared/Toast";
import {
  ActivityBody, useAssignLead, useCreateAppointment, useCreateLead, useCrmMeta, useLogActivity, usePatchLead,
} from "../api";
import { OUTCOME_GROUPS } from "../statusConfig";
import type { CrmLead } from "../types";
import { defaultLocalInput, fmtDateTime, localInputToISO } from "../format";
import { Button, ErrorText, Field, InfoNote, Modal, inputCls } from "./ui";

const CLOSING = new Set(["wrong_number", "converted", "not_interested"]);

export function LogActivityDialog({ lead, open, onClose }: { lead: CrmLead; open: boolean; onClose: () => void }) {
  const toast = useToast();
  const { data: meta } = useCrmMeta();
  const log = useLogActivity();
  const [outcome, setOutcome] = useState("");
  const [notes, setNotes] = useState("");
  const [callbackAt, setCallbackAt] = useState(defaultLocalInput(120));
  const [apptAt, setApptAt] = useState(defaultLocalInput(24 * 60));
  const [purpose, setPurpose] = useState(lead.service_type || "");
  const [storeId, setStoreId] = useState<string>("");
  const [sale, setSale] = useState("");
  const [override, setOverride] = useState(false);
  const [nextAt, setNextAt] = useState(defaultLocalInput(24 * 60));

  const submit = async () => {
    const body: ActivityBody = { outcome, notes: notes || undefined };
    if (outcome === "callback_requested") body.callback_at = localInputToISO(callbackAt);
    if (outcome === "appointment_booked") {
      body.appointment_at = localInputToISO(apptAt);
      body.appointment_purpose = purpose || undefined;
      body.store_id = storeId ? Number(storeId) : null;
    }
    if (outcome === "converted" && sale) body.sale_amount = sale;
    if (override && !CLOSING.has(outcome) && outcome !== "note") body.next_follow_up_at = localInputToISO(nextAt);
    if (outcome === "note" && override) body.next_follow_up_at = localInputToISO(nextAt);
    try {
      const res = await log.mutateAsync({ leadId: lead.id, body });
      toast.success(res.next_follow_up
        ? `Logged. Next: ${res.next_follow_up.reason} · ${fmtDateTime(res.next_follow_up.due_at)}`
        : "Logged. Sequence closed for this lead.");
      setOutcome("");
      setNotes("");
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not log the activity");
    }
  };

  return (
    <Modal open={open} onClose={onClose} wide title={`Log activity · ${lead.full_name}`}
      footer={<>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" onClick={submit} disabled={!outcome} loading={log.isPending}>Save</Button>
      </>}>
      <div className="space-y-4">
        <p className="text-xs text-[var(--text-muted)]">
          Record what happened. The status and the next follow-up are set for you.
        </p>
        {OUTCOME_GROUPS.map((g) => (
          <div key={g.label}>
            <p className="text-[10px] uppercase tracking-wider font-semibold text-[var(--text-muted)] mb-1.5">{g.label}</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {g.outcomes.map((o) => (
                <button key={o.key} type="button" onClick={() => setOutcome(o.key)}
                  className={`text-left rounded-xl border px-3 py-2 cursor-pointer transition-colors ${
                    outcome === o.key ? "border-blue-500/60 bg-blue-500/10" : "border-[var(--border-subtle)] hover:bg-[var(--bg-card-hover)]"}`}>
                  <span className="block text-sm text-white font-medium">{o.label}</span>
                  <span className="block text-[11px] text-[var(--text-muted)]">{o.hint}</span>
                </button>
              ))}
            </div>
          </div>
        ))}

        {outcome === "callback_requested" && (
          <Field label="Customer's callback time (IST)">
            <input type="datetime-local" className={inputCls} value={callbackAt} onChange={(e) => setCallbackAt(e.target.value)} />
          </Field>
        )}
        {outcome === "appointment_booked" && (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Appointment (IST)">
              <input type="datetime-local" className={inputCls} value={apptAt} onChange={(e) => setApptAt(e.target.value)} />
            </Field>
            <Field label="Store">
              <select className={inputCls} value={storeId} onChange={(e) => setStoreId(e.target.value)}>
                <option value="">Not set</option>
                {meta?.stores.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </Field>
            <Field label="Purpose">
              <input className={inputCls} value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="e.g. Screen replacement" />
            </Field>
          </div>
        )}
        {outcome === "converted" && (
          <Field label="Sale amount (₹)" hint="Optional. Converted values stay fixed.">
            <input className={inputCls} inputMode="numeric" value={sale} onChange={(e) => setSale(e.target.value)} placeholder="e.g. 12000" />
          </Field>
        )}
        {outcome && !CLOSING.has(outcome) && (
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-xs text-[var(--text-secondary)] cursor-pointer">
              <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} />
              {outcome === "note" ? "Also schedule a follow-up" : "Choose the next follow-up time myself"}
            </label>
            {override && (
              <input type="datetime-local" className={inputCls} value={nextAt} onChange={(e) => setNextAt(e.target.value)} />
            )}
          </div>
        )}
        <Field label="Notes">
          <textarea className={inputCls} rows={2} value={notes} onChange={(e) => setNotes(e.target.value)}
            placeholder="What did the customer say?" />
        </Field>
        <ErrorText error={log.error} />
      </div>
    </Modal>
  );
}

export function AssignDialog({ leads, open, onClose, onDone }: {
  leads: CrmLead[]; open: boolean; onClose: () => void; onDone?: () => void;
}) {
  const toast = useToast();
  const { data: meta } = useCrmMeta();
  const assign = useAssignLead();
  const [owner, setOwner] = useState<string>("");
  const cities = useMemo(() => new Set(leads.map((l) => l.city)), [leads]);
  // Only people on every selected lead's city team (the server checks too).
  const people = (meta?.people || []).filter((p) => [...cities].every((c) => p.sheets.includes(c)));
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    let ok = 0;
    let failed = 0;
    for (const l of leads) {
      try {
        await assign.mutateAsync({ leadId: l.id, ownerId: owner === "none" ? null : Number(owner) });
        ok += 1;
      } catch {
        failed += 1;
      }
    }
    setBusy(false);
    if (ok) toast.success(`Reassigned ${ok} lead${ok > 1 ? "s" : ""}`);
    if (failed) toast.error(`${failed} lead${failed > 1 ? "s" : ""} could not be reassigned`);
    onDone?.();
    onClose();
  };

  return (
    <Modal open={open} onClose={onClose} title={leads.length === 1 ? `Assign · ${leads[0]!.full_name}` : `Assign ${leads.length} leads`}
      footer={<>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" onClick={submit} disabled={!owner} loading={busy}>Assign</Button>
      </>}>
      <div className="space-y-3">
        <Field label="New owner" hint="Only people on the lead's city team are listed. Open follow-ups move to the new owner; missed deadlines stay with the previous owner.">
          <select className={inputCls} value={owner} onChange={(e) => setOwner(e.target.value)}>
            <option value="">Choose…</option>
            {people.map((p) => (
              <option key={p.id} value={p.id}>{p.name} · {p.role}{p.available ? "" : " (away)"}</option>
            ))}
            <option value="none">Unassign</option>
          </select>
        </Field>
      </div>
    </Modal>
  );
}

export function ScheduleFollowupDialog({ lead, open, onClose }: { lead: CrmLead; open: boolean; onClose: () => void }) {
  const toast = useToast();
  const patch = usePatchLead();
  const [when, setWhen] = useState(defaultLocalInput(60));
  const submit = async () => {
    try {
      await patch.mutateAsync({ leadId: lead.id, body: { next_follow_up_at: localInputToISO(when) } });
      toast.success("Follow-up scheduled");
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not schedule");
    }
  };
  return (
    <Modal open={open} onClose={onClose} title={`Schedule follow-up · ${lead.full_name}`}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={submit} loading={patch.isPending}>Schedule</Button></>}>
      <div className="space-y-3">
        <Field label="Call at (IST)">
          <input type="datetime-local" className={inputCls} value={when} onChange={(e) => setWhen(e.target.value)} />
        </Field>
        <InfoNote>Moving a follow-up that is already overdue still counts it as missed in reports.</InfoNote>
      </div>
    </Modal>
  );
}

export function BookAppointmentDialog({ lead, open, onClose }: { lead: CrmLead; open: boolean; onClose: () => void }) {
  const toast = useToast();
  const { data: meta } = useCrmMeta();
  const create = useCreateAppointment();
  const [when, setWhen] = useState(defaultLocalInput(24 * 60));
  const [purpose, setPurpose] = useState(lead.service_type || "");
  const [storeId, setStoreId] = useState("");
  const submit = async () => {
    try {
      await create.mutateAsync({ lead_id: lead.id, scheduled_at: localInputToISO(when), purpose: purpose || undefined,
        store_id: storeId ? Number(storeId) : null });
      toast.success("Appointment booked");
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not book");
    }
  };
  return (
    <Modal open={open} onClose={onClose} title={`Book appointment · ${lead.full_name}`}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={submit} loading={create.isPending}>Book</Button></>}>
      <div className="space-y-3">
        <Field label="Date & time (IST)">
          <input type="datetime-local" className={inputCls} value={when} onChange={(e) => setWhen(e.target.value)} />
        </Field>
        <Field label="Store">
          <select className={inputCls} value={storeId} onChange={(e) => setStoreId(e.target.value)}>
            <option value="">Not set</option>
            {meta?.stores.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </Field>
        <Field label="Purpose">
          <input className={inputCls} value={purpose} onChange={(e) => setPurpose(e.target.value)} placeholder="e.g. Screen replacement assessment" />
        </Field>
        <p className="text-[11px] text-[var(--text-muted)]">A confirmation call is scheduled 2 hours before.</p>
      </div>
    </Modal>
  );
}

const SOURCES = ["Walk-in", "Referral", "Phone", "Website", "Instagram", "Other"];

export function NewLeadDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated?: (l: CrmLead) => void }) {
  const toast = useToast();
  const { data: meta } = useCrmMeta();
  const create = useCreateLead();
  const [form, setForm] = useState({ full_name: "", phone: "", email: "", city: "", lead_source: "Walk-in",
    phone_model: "", service_type: "", coverage: "Standard", remarks: "", owner_user_id: "" });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const city = form.city || meta?.sheets[0] || "";
  const owners = (meta?.people || []).filter((p) => p.sheets.includes(city));

  const submit = async () => {
    try {
      const res = await create.mutateAsync({
        ...form, city, owner_user_id: form.owner_user_id ? Number(form.owner_user_id) : null,
        phone_model: form.phone_model || null, service_type: form.service_type || null,
      });
      toast.success(`Lead created${res.lead.owner_name ? ` · owner ${res.lead.owner_name}` : ""}`);
      onCreated?.(res.lead);
      setForm((f) => ({ ...f, full_name: "", phone: "", email: "", remarks: "" }));
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not create the lead");
    }
  };

  return (
    <Modal open={open} onClose={onClose} wide title="New lead"
      footer={<><Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" onClick={submit} disabled={!form.full_name || !form.phone || !city} loading={create.isPending}>Create lead</Button></>}>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="Customer name"><input className={inputCls} value={form.full_name} onChange={set("full_name")} /></Field>
        <Field label="Phone"><input className={inputCls} value={form.phone} onChange={set("phone")} inputMode="tel" /></Field>
        <Field label="City">
          <select className={inputCls} value={city} onChange={set("city")}>
            {meta?.sheets.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </Field>
        <Field label="Source">
          <select className={inputCls} value={form.lead_source} onChange={set("lead_source")}>
            {SOURCES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </Field>
        <Field label="Phone model">
          <input className={inputCls} list="crm-models" value={form.phone_model} onChange={set("phone_model")} placeholder="e.g. iPhone 15" />
        </Field>
        <Field label="Service">
          <input className={inputCls} list="crm-services" value={form.service_type} onChange={set("service_type")} placeholder="e.g. Screen repair" />
        </Field>
        <Field label="Coverage">
          <select className={inputCls} value={form.coverage} onChange={set("coverage")}>
            {meta?.coverages.map((c) => <option key={c}>{c}</option>)}
          </select>
        </Field>
        <Field label="Email (optional)"><input className={inputCls} value={form.email} onChange={set("email")} /></Field>
        {meta?.can.reassign && (
          <Field label="Owner" hint="Leave empty to assign automatically (round-robin).">
            <select className={inputCls} value={form.owner_user_id} onChange={set("owner_user_id")}>
              <option value="">Automatic</option>
              {owners.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </Field>
        )}
        <div className="sm:col-span-2">
          <Field label="Remarks"><textarea className={inputCls} rows={2} value={form.remarks} onChange={set("remarks")} /></Field>
        </div>
      </div>
      <p className="text-[11px] text-[var(--text-muted)] mt-3">
        App-only lead (walk-in, referral, phone). Meta leads keep arriving from the Google Sheet as before.
      </p>
      <datalist id="crm-models">{meta?.phone_models.map((m) => <option key={m} value={m} />)}</datalist>
      <datalist id="crm-services">{meta?.service_types.map((m) => <option key={m} value={m} />)}</datalist>
    </Modal>
  );
}
