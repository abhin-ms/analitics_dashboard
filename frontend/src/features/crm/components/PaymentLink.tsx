/** ₹99 payment link after a call: the send form, a lead's link status, the
 * badge on lead lists, and the "₹99 bookings from calls" report for a
 * telecaller (own), a team leader (their team) and the admin (every team). */
import { useEffect, useState } from "react";
import { CreditCard, RefreshCw, Send } from "lucide-react";
import { useToast } from "@/components/shared/Toast";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { localDateStr } from "@/lib/utils";
import {
  type PaymentLinkRow, useCrmMeta, usePaymentLinkForm, usePaymentList, usePaymentSummary, useRefreshPaymentLink,
  useSendPaymentLink,
} from "../api";
import type { CrmLead } from "../types";
import { fmtDateTime } from "../format";
import { openLead } from "./LeadDrawer";
import { Button, Card, CardHeader, Empty, Field, Modal, Pill, inputCls } from "./ui";

const fmt12 = (iso: string | null | undefined) => fmtDateTime(iso, { hour12: true });

export const PAY_LOOK: Record<string, { label: string; color: string }> = {
  sent: { label: "Payment request sent · waiting", color: "#f59e0b" },
  paid: { label: "₹99 paid · via call", color: "#10b981" },
  expired: { label: "Payment request expired", color: "#ef4444" },
  cancelled: { label: "Replaced by a newer request", color: "#64748b" },
  failed: { label: "Not sent", color: "#ef4444" },
};

/** The small tag on lead lists. */
export function PayBadge({ lead }: { lead: CrmLead }) {
  const p = lead.call_payment;
  if (!p || p.status === "cancelled") return null;
  const look = PAY_LOOK[p.status] ?? PAY_LOOK.sent;
  return <Pill label={p.status === "paid" ? `₹${p.amount} paid · via call` : look.label} color={look.color} />;
}

/** The send form, filled from the lead; anything can be corrected. */
export function PaymentLinkDialog({ leadId, open, onClose }: { leadId: number; open: boolean; onClose: () => void }) {
  const toast = useToast();
  const { data: meta } = useCrmMeta();
  const { data, isLoading, error } = usePaymentLinkForm(leadId, open);
  const send = useSendPaymentLink();
  const [f, setF] = useState({ customer_name: "", customer_phone: "", phone_model: "", service: "", store_id: "", visit_at: "" });
  const [mode, setMode] = useState<"whatsapp" | "link">("whatsapp");
  useEffect(() => {
    if (!data) return;
    const p = data.form;
    setMode(p.mode);
    setF({ customer_name: p.customer_name, customer_phone: p.customer_phone, phone_model: p.phone_model,
      service: p.service, store_id: p.store_id ? String(p.store_id) : "", visit_at: p.visit_at });
  }, [data]);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((p) => ({ ...p, [k]: e.target.value }));
  const amount = data?.form.amount ?? 99;
  const hours = data?.form.valid_hours ?? 24;
  const storeName = meta?.stores.find((s) => String(s.id) === f.store_id)?.name || "Break Protection";
  const visitLabel = f.visit_at
    ? new Date(`${f.visit_at}:00+05:30`).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true })
    : "To be confirmed";
  const visitAt = f.visit_at ? new Date(`${f.visit_at}:00+05:30`) : null;
  const visitDate = visitAt
    ? visitAt.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", weekday: "short", day: "numeric", month: "short", year: "numeric" })
    : "To be confirmed";
  const visitTime = visitAt
    ? visitAt.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit", hour12: true }).toUpperCase()
    : "To be confirmed";

  const submit = async () => {
    try {
      await send.mutateAsync({ leadId, body: { ...f, mode, store_id: f.store_id ? Number(f.store_id) : null, visit_at: f.visit_at || null } });
      toast.success(`₹${amount} request sent to ${f.customer_name.split(" ")[0]} on WhatsApp. You'll see here when they pay.`);
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not send the link");
    }
  };

  return (
    <Modal open={open} onClose={onClose} wide title={<span className="flex items-center gap-2"><CreditCard size={16} className="text-emerald-400" />Ask for ₹{amount} on WhatsApp</span>}
      footer={<>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" onClick={submit} loading={send.isPending}
          disabled={!data?.enabled || !data?.can_send || !f.customer_name.trim() || !f.customer_phone.trim()}>
          <Send size={14} />Send on WhatsApp
        </Button>
      </>}>
      {isLoading ? <TableSkeleton /> : error ? <p className="text-sm text-rose-400">{error instanceof Error ? error.message : "Could not load the lead"}</p> : (
        <div className="space-y-3">
          {!data?.enabled && <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">Payments aren't set up yet. An admin can set them up in Settings → WhatsApp → Payments.</p>}
          {data && !data.can_send && <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">Your role can't send messages to customers.</p>}
          {data && data.modes.whatsapp && data.modes.link && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2" role="radiogroup" aria-label="How the customer pays">
              {([["whatsapp", "Pay inside WhatsApp", "UPI, without leaving the chat · Indian numbers"],
                 ["link", "Payment link", "Opens Razorpay's page · UPI, cards, net banking"]] as const).map(([k, l, h]) => (
                <button key={k} type="button" role="radio" aria-checked={mode === k} onClick={() => setMode(k)}
                  className={`text-left rounded-xl border px-3 py-2.5 cursor-pointer ${mode === k ? "border-emerald-500 bg-emerald-500/10" : "border-[var(--border-subtle)]"}`}>
                  <span className="block text-sm font-semibold text-white">{l}</span>
                  <span className="block text-[11px] text-[var(--text-muted)]">{h}</span>
                </button>
              ))}
            </div>
          )}
          <p className="text-xs text-[var(--text-muted)]">Filled in from the lead. Correct anything that's wrong; the phone model, service and store are saved to the lead too.</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Customer name"><input id="pl-name" className={inputCls} value={f.customer_name} onChange={set("customer_name")} /></Field>
            <Field label="WhatsApp number" hint="With country code if not Indian">
              <input id="pl-phone" inputMode="tel" className={inputCls} value={f.customer_phone} onChange={set("customer_phone")} />
            </Field>
            <Field label="Phone model"><input id="pl-model" className={inputCls} value={f.phone_model} onChange={set("phone_model")} placeholder="e.g. Galaxy S24" /></Field>
            <Field label="Service"><input id="pl-service" className={inputCls} value={f.service} onChange={set("service")} placeholder="e.g. Screen + back glass" /></Field>
            <Field label="Store">
              <select id="pl-store" className={inputCls} value={f.store_id} onChange={set("store_id")}>
                <option value="">Not set</option>
                {meta?.stores.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </Field>
            <Field label="Visit date & time (IST)" hint="Booked as an appointment once paid">
              <input id="pl-visit" type="datetime-local" className={inputCls} value={f.visit_at} onChange={set("visit_at")} />
            </Field>
            <Field label="Amount"><input id="pl-amount" className={`${inputCls} text-emerald-400 font-bold`} value={`₹${amount}`} readOnly /></Field>
            <Field label="Link valid for"><input id="pl-valid" className={inputCls} value={`${hours} hours`} readOnly /></Field>
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)] mb-1">What the customer gets</p>
            <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-3 text-xs leading-relaxed text-[var(--text-secondary)] whitespace-pre-line">
              {mode === "whatsapp"
                ? `Hi ${f.customer_name.split(" ")[0] || "…"},\n\nPayment is pending for your booking request.\n\nStore: ${storeName}\nModel: ${f.phone_model || "your phone"}\nVisit date: ${visitDate}\nVisit time: ${visitTime}\nAmount due: ₹${amount}\n\nTap Review and Pay to complete the payment for this booking.`
                : `Hi ${f.customer_name.split(" ")[0] || "…"},\n\nAs discussed on the call, here is the link to reserve your priority slot with Break Protection.\n\nStore: ${storeName}\nModel: ${f.phone_model || "your phone"}\nVisit: ${visitLabel}\nAmount: ₹${amount}\n\nTap Pay below to complete the booking. The link is valid for 24 hours.`}
              <div className="mt-2 pt-2 border-t border-[var(--border-subtle)] text-center font-semibold text-blue-400">{mode === "whatsapp" ? "Review and Pay" : "Pay"}</div>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}

/** In the lead panel: the latest link and what happened to it. */
export function PaymentStatus({ leadId, onSend }: { leadId: number; onSend?: () => void }) {
  const toast = useToast();
  const { data } = usePaymentLinkForm(leadId);
  const refresh = useRefreshPaymentLink();
  const last: PaymentLinkRow | undefined = data?.links.find((l) => l.status !== "failed") ?? data?.links[0];
  if (!data?.enabled && !last) return null;
  if (!last) return null;
  const look = PAY_LOOK[last.status] ?? PAY_LOOK.sent;
  return (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-3 text-xs space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <Pill label={look.label} color={look.color} />
        <div className="flex gap-1.5">
          {last.status === "sent" && (
            <Button size="sm" loading={refresh.isPending} onClick={async () => {
              try {
                const r = await refresh.mutateAsync(last.id);
                toast.success(r.paid ? "Paid!" : "Not paid yet");
              } catch (e) { toast.error(e instanceof Error ? e.message : "Could not check"); }
            }}><RefreshCw size={12} />Check</Button>
          )}
          {last.status !== "paid" && onSend && data?.can_send && <Button size="sm" onClick={onSend}><Send size={12} />Send again</Button>}
        </div>
      </div>
      <p className="text-[var(--text-secondary)]">
        ₹{last.amount} {last.mode === "whatsapp" ? "Review and Pay request" : "payment link"} sent {fmt12(last.created_at)}{last.sent_by ? ` by ${last.sent_by}` : ""}
        {last.opened_at && <> · opened {fmt12(last.opened_at)}</>}
      </p>
      {last.status === "paid" && <p className="text-emerald-400 font-semibold">Paid {fmt12(last.paid_at)}{last.payment_id ? ` · ${last.payment_id}` : ""}</p>}
      {last.status === "sent" && last.expires_at && <p className="text-[var(--text-muted)]">Valid till {fmt12(last.expires_at)}</p>}
      {last.error && <p className="text-rose-400">{last.error}</p>}
    </div>
  );
}

// ── report ───────────────────────────────────────────────────────────

const PERIODS = [["today", "Today"], ["7d", "Last 7 days"], ["month", "This month"], ["last_month", "Last month"], ["custom", "Custom"]] as const;
type Period = typeof PERIODS[number][0];
function range(p: Period, custom: { start: string; end: string }) {
  const t = new Date();
  const day = (o: number) => localDateStr(new Date(t.getFullYear(), t.getMonth(), t.getDate() - o));
  if (p === "today") return { start: day(0), end: day(0) };
  if (p === "7d") return { start: day(6), end: day(0) };
  if (p === "month") return { start: localDateStr(new Date(t.getFullYear(), t.getMonth(), 1)), end: day(0) };
  if (p === "last_month") return { start: localDateStr(new Date(t.getFullYear(), t.getMonth() - 1, 1)), end: localDateStr(new Date(t.getFullYear(), t.getMonth(), 0)) };
  return custom;
}
const pctColor = (p: number | null) => (p == null ? "var(--text-muted)" : p >= 50 ? "#10b981" : p >= 25 ? "#f59e0b" : "#ef4444");

/** "₹99 bookings from calls": totals, team leaders (admin), telecallers,
 * and the paid customers behind a number. tlId fixes one team (admin on a
 * team leader's page). */
export function CallPayments({ tlId, title = "₹99 bookings from calls" }: { tlId?: number | null; title?: string }) {
  const [period, setPeriod] = useState<Period>("month");
  const [custom, setCustom] = useState({ start: "", end: "" });
  const r = range(period, custom);
  const ready = !!r.start && !!r.end && r.start <= r.end;
  const [team, setTeam] = useState<number | null>(tlId ?? null);
  const [person, setPerson] = useState<{ id: number; name: string } | null>(null);
  const { data, isLoading } = usePaymentSummary({ start: r.start, end: r.end, tl_id: tlId ?? undefined });
  const list = usePaymentList({ start: r.start, end: r.end, user_id: person?.id, status: "paid" }, ready && !!person);
  const admin = data?.level === "admin" && tlId == null;
  const people = (data?.telecallers || []).filter((t) => !admin || team == null || t.tl_id === team);
  const tile = (label: string, value: string | number, color?: string) => (
    <div className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] p-3">
      <p className="text-[11px] text-[var(--text-muted)]">{label}</p>
      <p className="text-2xl font-extrabold tabular-nums" style={{ color }}>{value}</p>
    </div>
  );
  return (
    <Card>
      <CardHeader title={title} icon={<CreditCard size={15} className="text-emerald-400" />}
        subtitle="Leads turned into a paid ₹99 slot with a payment link sent after a call. Website bookings are not counted here." />
      <div className="p-4 space-y-4">
        <div className="flex flex-wrap items-center gap-1.5">
          {PERIODS.map(([k, l]) => (
            <button key={k} type="button" onClick={() => { setPeriod(k); setPerson(null); }} aria-pressed={period === k}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold border cursor-pointer ${period === k ? "bg-[var(--accent-blue)] border-[var(--accent-blue)] text-white" : "border-[var(--border-subtle)] text-[var(--text-secondary)] hover:text-white"}`}>
              {l}
            </button>
          ))}
          {period === "custom" && (
            <span className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
              <input id="cp-start" type="date" aria-label="From" className={`${inputCls} !w-auto !py-1.5`} value={custom.start} onChange={(e) => setCustom((c) => ({ ...c, start: e.target.value }))} />
              to
              <input id="cp-end" type="date" aria-label="To" className={`${inputCls} !w-auto !py-1.5`} value={custom.end} onChange={(e) => setCustom((c) => ({ ...c, end: e.target.value }))} />
            </span>
          )}
        </div>

        {!ready ? <p className="text-sm text-[var(--text-muted)]">Pick a start and end date.</p> : isLoading || !data ? <TableSkeleton /> : (
          <>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              {tile("Links sent", data.total.sent)}
              {tile("Paid ₹99", data.total.paid, "#10b981")}
              {tile("Waiting to pay", data.total.waiting, "#f59e0b")}
              {tile("Link → paid", data.total.paid_pct == null ? "—" : `${data.total.paid_pct}%`, pctColor(data.total.paid_pct))}
            </div>
            {!data.enabled && data.total.sent === 0 && <p className="text-xs text-amber-300">Payments aren't set up yet (Settings → WhatsApp → Payments).</p>}

            {admin && data.team_leaders.length > 0 && (
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => { setTeam(null); setPerson(null); }}
                  className={`px-3 py-2 rounded-xl border text-xs font-semibold cursor-pointer ${team == null ? "border-[var(--accent-blue)] bg-[var(--accent-blue)]/10 text-white" : "border-[var(--border-subtle)] text-[var(--text-secondary)]"}`}>
                  All teams
                </button>
                {data.team_leaders.map((t) => (
                  <button key={t.tl_id ?? "none"} type="button" onClick={() => { setTeam(t.tl_id); setPerson(null); }}
                    className={`px-3 py-2 rounded-xl border text-xs cursor-pointer text-left ${team === t.tl_id ? "border-[var(--accent-blue)] bg-[var(--accent-blue)]/10" : "border-[var(--border-subtle)]"}`}>
                    <span className="font-semibold text-white">{t.name}</span>
                    <span className="ml-2 text-emerald-400 font-bold">{t.paid}</span><span className="text-[var(--text-muted)]"> / {t.sent} sent</span>
                  </button>
                ))}
              </div>
            )}

            {people.length === 0 ? <Empty>No payment links sent in this period.</Empty> : (
              <div className="flex flex-wrap gap-4 items-start">
                <div className="overflow-x-auto" style={{ flex: "999 1 520px", minWidth: 0 }}>
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-left text-[var(--text-muted)] border-b border-[var(--border-subtle)]">
                        <th className="py-2 pr-3 font-semibold">{data.level === "own" ? "You" : "Telecaller"}</th>
                        <th className="py-2 pr-3 font-semibold text-right">Sent</th>
                        <th className="py-2 pr-3 font-semibold text-right">Paid</th>
                        <th className="py-2 pr-3 font-semibold text-right">Waiting</th>
                        <th className="py-2 pr-3 font-semibold text-right">Expired</th>
                        <th className="py-2 pr-3 font-semibold text-right">Link → paid</th>
                        <th className="py-2 font-semibold" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--border-subtle)]">
                      {people.map((t) => (
                        <tr key={t.user_id} className={person?.id === t.user_id ? "bg-[var(--accent-blue)]/5" : ""}>
                          <td className="py-2.5 pr-3">
                            <p className="font-medium text-white">{t.name}</p>
                            <p className="text-[11px] text-[var(--text-muted)]">{t.role === "Team leader" ? "Team leader" : t.store || "No store set"}{admin && t.team_leader ? ` · ${t.team_leader}` : ""}</p>
                          </td>
                          <td className="py-2.5 pr-3 text-right tabular-nums">{t.sent}</td>
                          <td className="py-2.5 pr-3 text-right tabular-nums text-emerald-400 font-bold">{t.paid}</td>
                          <td className="py-2.5 pr-3 text-right tabular-nums">{t.waiting}</td>
                          <td className="py-2.5 pr-3 text-right tabular-nums">{t.expired}</td>
                          <td className="py-2.5 pr-3 text-right tabular-nums font-semibold" style={{ color: pctColor(t.paid_pct) }}>{t.paid_pct == null ? "—" : `${t.paid_pct}%`}</td>
                          <td className="py-2.5 text-right">
                            <Button size="sm" variant={person?.id === t.user_id ? "primary" : "secondary"} disabled={!t.paid}
                              onClick={() => setPerson(person?.id === t.user_id ? null : { id: t.user_id, name: t.name })}>Details</Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {person && (
                  <div className="rounded-xl border border-[var(--border-subtle)] p-3 space-y-2" style={{ flex: "1 1 320px", minWidth: 0 }}>
                    <p className="text-sm font-semibold text-white">{person.name} · paid customers</p>
                    {list.isLoading ? <TableSkeleton /> : !list.data?.items.length ? <p className="text-xs text-[var(--text-muted)]">None in this period.</p> : list.data.items.map((p) => (
                      <button key={p.id} type="button" onClick={() => openLead(p.lead_id)}
                        className="w-full text-left rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-primary)] px-3 py-2 cursor-pointer hover:border-[var(--accent-blue)]">
                        <span className="flex justify-between gap-2"><b className="text-white text-xs">{p.customer_name}</b><span className="text-emerald-400 font-bold text-xs">₹{p.amount}</span></span>
                        <span className="block text-[11px] text-[var(--text-secondary)]">+{p.customer_phone} · {[p.phone_model, p.service].filter(Boolean).join(" · ") || "Device not given"}</span>
                        <span className="block text-[11px] text-[var(--text-muted)]">Paid {fmt12(p.paid_at)}{p.store ? ` · ${p.store}` : ""}{p.visit_at ? ` · visit ${fmt12(p.visit_at)}` : ""}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </Card>
  );
}
