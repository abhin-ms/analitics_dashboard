/** Mobile call flow for telecallers: Call (opens the phone's dialer and
 * starts the timer) → End call → "what happened" → saved through the same
 * Log activity endpoint as the desktop dialog, with the call's length. */
import { useMemo, useState, type ReactNode } from "react";
import {
  Ban, CalendarCheck, ChevronLeft, CircleMinus, Ellipsis, IndianRupee, Phone, PhoneMissed, PhoneOff,
  Power, RotateCcw, Store, ThumbsUp, X,
} from "lucide-react";
import { useToast } from "@/components/shared/Toast";
import { sanitizePhone } from "@/components/shared/PhoneActions";
import { cn } from "@/lib/utils";
import { type ActivityBody, useCrmMeta, useLogActivity, usePatchLead } from "../api";
import { OUTCOME_GROUPS, PRIORITIES, statusColor } from "../statusConfig";
import { addDaysKey, fmtDateTime, localInputToISO, todayIST } from "../format";
import { type CallTarget, callSeconds, mmss, useActiveCall, useNow } from "./activeCall";

export function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]!.toUpperCase()).join("") || "?";
}

const isNoStatus = (s: string) => !s || s === "No Status";

/** Lead status tag. A lead nobody has called yet shows as "New". `soft` is
 * the tinted list style; the default is solid. */
export function StatusTag({ status, soft }: { status: string; soft?: boolean }) {
  const label = isNoStatus(status) ? "New" : status;
  const color = isNoStatus(status) ? "#8a94a6" : statusColor(status);
  return soft ? (
    <span className="inline-block px-2 py-0.5 rounded-md text-[11.5px] font-medium"
      style={{ backgroundColor: `${color}22`, color: isNoStatus(status) ? "var(--text-secondary)" : color }}>
      {label}
    </span>
  ) : (
    <span className="inline-block px-2 py-0.5 rounded-md text-[11.5px] font-semibold"
      style={{ backgroundColor: color, color: "#fff" }}>
      {label}
    </span>
  );
}

/** Short source tag: META, WEB, WALK-IN… */
export function SourceTag({ source, label }: { source?: string; label?: string }) {
  const SHORT: Record<string, string> = {
    meta_sheet: "META", facebook: "META", instagram: "META", website: "WEB", walk_in: "WALK-IN",
    whatsapp: "WHATSAPP", referral: "REFERRAL", phone: "PHONE", app: "APP",
  };
  const text = (source && SHORT[source]) || (label || "").toUpperCase();
  if (!text) return null;
  return <span className="inline-block shrink-0 whitespace-nowrap px-2 py-0.5 rounded-md text-[11px] font-bold tracking-wide bg-blue-500/12 text-blue-500">{text}</span>;
}

/** Start the call timer and hand the number to the phone's dialer. Used by
 * auto-dial; a tap uses CallButton's tel: link instead. */
export function dial(target: CallTarget) {
  const clean = sanitizePhone(target.phone || "");
  if (!clean.replace("+", "")) return false;
  useActiveCall.getState().start({ ...target, phone: clean }, true);
  window.location.href = `tel:${clean}`;
  return true;
}

/** Green call button: a real tel: link (the only way a web page can open
 * the phone's dialer), which also starts the call timer. */
export function CallButton({ target, className }: { target: CallTarget; className?: string }) {
  const start = useActiveCall((s) => s.start);
  const clean = sanitizePhone(target.phone || "");
  if (!clean.replace("+", "")) {
    return (
      <span className={cn("w-12 h-12 rounded-xl grid place-items-center bg-[var(--bg-subtle)] text-[var(--text-muted)] shrink-0", className)}
        title="No phone number">
        <PhoneOff size={18} />
      </span>
    );
  }
  return (
    <a href={`tel:${clean}`} aria-label={`Call ${target.name}`}
      onClick={(e) => { e.stopPropagation(); start({ ...target, phone: clean }); }}
      className={cn("w-[46px] h-[46px] rounded-xl grid place-items-center bg-emerald-500/15 text-emerald-500 shrink-0 active:scale-95 transition-transform", className)}>
      <Phone size={22} fill="currentColor" strokeWidth={0} />
    </a>
  );
}

/** Shows the on-call screen or the call report over the page while a call
 * is open. Mounted once by the mobile telecaller view. */
export function CallFlowHost() {
  const call = useActiveCall((s) => s.call);
  if (!call) return null;
  return (
    <div className="fixed inset-0 z-[55] flex flex-col bg-[var(--bg-primary)] text-[var(--text-primary)]"
      style={{ paddingTop: "env(safe-area-inset-top)", paddingBottom: "env(safe-area-inset-bottom)" }}>
      {call.endedAt ? <CallReport /> : <OnCall />}
    </div>
  );
}

function OnCall() {
  const call = useActiveCall((s) => s.call)!;
  const end = useActiveCall((s) => s.end);
  const clear = useActiveCall((s) => s.clear);
  const now = useNow(true);

  return (
    <div className="flex-1 flex flex-col items-center gap-2.5 px-6 pt-10 pb-8 overflow-y-auto"
      style={{ background: "linear-gradient(180deg, var(--accent-blue-glow), transparent 55%)" }}>
      {call.source && <span className="text-[10.5px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-400">{call.source} lead</span>}
      <div className="w-24 h-24 mt-3 rounded-full grid place-items-center text-3xl font-bold text-white bg-violet-600">
        {initials(call.name)}
      </div>
      <h2 className="mt-1 text-2xl font-bold text-center">{call.name}</h2>
      <p className="text-[15px] text-[var(--text-muted)] tabular-nums">{call.phone}</p>
      <p className="flex items-center gap-2 text-[15px] font-bold text-emerald-400 tabular-nums" aria-live="off">
        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
        {mmss(callSeconds(call, now))}
      </p>
      <StatusTag status={call.status} />
      {call.note && (
        <div className="w-full max-w-md mt-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-card)] p-3 text-[13px] leading-snug">
          <span className="block text-[11px] font-bold uppercase tracking-wider text-[var(--text-muted)] mb-1">Last note</span>
          {call.note}
        </div>
      )}
      <p className="text-xs text-[var(--text-muted)] text-center max-w-xs mt-2">
        {call.auto ? "Auto-dial opened your phone app. If it didn't, tap Call again. " : ""}
        Finish the call in your phone app, then come back here and tap End call.
      </p>

      <div className="mt-auto pt-6 flex items-end gap-7">
        <button onClick={clear} className="flex flex-col items-center gap-1.5 text-xs text-[var(--text-muted)] cursor-pointer">
          <span className="w-14 h-14 rounded-full grid place-items-center border border-[var(--border-strong)] bg-[var(--bg-card)] text-[var(--text-primary)]"><X size={22} /></span>
          Didn't call
        </button>
        <button onClick={end} className="flex flex-col items-center gap-1.5 text-xs text-[var(--text-muted)] cursor-pointer">
          <span className="w-[72px] h-[72px] rounded-full grid place-items-center bg-rose-600 text-white active:scale-95 transition-transform"><PhoneOff size={30} /></span>
          End call
        </button>
        <a href={`tel:${call.phone}`} className="flex flex-col items-center gap-1.5 text-xs text-[var(--text-muted)]">
          <span className="w-14 h-14 rounded-full grid place-items-center border border-[var(--border-strong)] bg-[var(--bg-card)] text-[var(--text-primary)]"><RotateCcw size={22} /></span>
          Call again
        </a>
      </div>
    </div>
  );
}

const OUTCOME_LOOK: Record<string, { icon: ReactNode; tone: string; short: string }> = {
  no_answer: { icon: <PhoneMissed size={19} />, tone: "grey", short: "No answer" },
  busy: { icon: <CircleMinus size={19} />, tone: "grey", short: "Busy" },
  switched_off: { icon: <Power size={19} />, tone: "grey", short: "Switched off" },
  wrong_number: { icon: <X size={19} />, tone: "grey", short: "Wrong number" },
  callback_requested: { icon: <RotateCcw size={19} />, tone: "blue", short: "Call back" },
  will_visit: { icon: <Store size={19} />, tone: "blue", short: "Will visit" },
  appointment_booked: { icon: <CalendarCheck size={19} />, tone: "purple", short: "Appointment" },
  advance_paid: { icon: <IndianRupee size={19} />, tone: "green", short: "Advance paid" },
  converted: { icon: <ThumbsUp size={19} />, tone: "green", short: "Sale done" },
  not_interested: { icon: <Ban size={19} />, tone: "red", short: "Not interested" },
  connected_other: { icon: <Ellipsis size={19} />, tone: "grey", short: "Other" },
};

const TONE: Record<string, string> = {
  amber: "bg-[var(--tone-amber-bg)] text-[var(--tone-amber-fg)]",
  blue: "bg-[var(--tone-blue-bg)] text-[var(--tone-blue-fg)]",
  purple: "bg-[var(--tone-purple-bg)] text-[var(--tone-purple-fg)]",
  green: "bg-[var(--tone-green-bg)] text-[var(--tone-green-fg)]",
  red: "bg-[var(--tone-red-bg)] text-[var(--tone-red-fg)]",
  grey: "bg-[var(--bg-subtle)] text-[var(--text-secondary)]",
};

// The design's order inside each group (the desktop dialog keeps its own).
const TILE_ORDER = ["no_answer", "busy", "switched_off", "wrong_number", "callback_requested", "will_visit",
  "appointment_booked", "advance_paid", "converted", "not_interested", "connected_other"];
const orderTiles = <T extends { key: string }>(list: T[]) =>
  [...list].sort((a, b) => TILE_ORDER.indexOf(a.key) - TILE_ORDER.indexOf(b.key));
const NOTE_MAX = 250;

const NEEDS_TIME = new Set(["callback_requested", "appointment_booked"]);
const ASK_PRIORITY = new Set(["will_visit", "advance_paid", "connected_other"]);
const QUICK_TIMES = ["10:00", "11:30", "14:00", "16:30", "18:00"];

function timeLabel(hhmm: string) {
  const [h, m] = hhmm.split(":").map(Number);
  return `${((h! + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${h! < 12 ? "AM" : "PM"}`;
}

function dayLabel(key: string, i: number) {
  if (i === 0) return "Today";
  if (i === 1) return "Tomorrow";
  const [y, mo, d] = key.split("-").map(Number);
  return new Date(Date.UTC(y!, mo! - 1, d!)).toLocaleDateString("en-IN", { timeZone: "UTC", weekday: "short", day: "numeric" });
}

function Pick({ on, onClick, disabled, children }: { on: boolean; onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} aria-pressed={on}
      className={cn("px-3 py-2 rounded-md border text-[13px] font-semibold tabular-nums cursor-pointer disabled:opacity-35 disabled:cursor-not-allowed",
        on ? "bg-blue-600 border-blue-600 text-white" : "bg-[var(--bg-card)] border-[var(--border-subtle)] text-[var(--text-primary)]")}>
      {children}
    </button>
  );
}

function GroupLabel({ children }: { children: ReactNode }) {
  return <p className="text-[11px] font-bold uppercase tracking-wider text-[var(--text-muted)] mt-1">{children}</p>;
}

function CallReport() {
  const call = useActiveCall((s) => s.call)!;
  const resume = useActiveCall((s) => s.resume);
  const clear = useActiveCall((s) => s.clear);
  const toast = useToast();
  const { data: meta } = useCrmMeta();
  const log = useLogActivity();
  const patch = usePatchLead();

  const [outcome, setOutcome] = useState("");
  const [notes, setNotes] = useState("");
  const [day, setDay] = useState("");
  const [time, setTime] = useState("");
  const [exact, setExact] = useState("");
  const [storeId, setStoreId] = useState("");
  const [sale, setSale] = useState("");
  const [priority, setPriority] = useState("");

  const secs = callSeconds(call);
  const days = useMemo(() => {
    const t = todayIST();
    return [0, 1, 2, 3, 4].map((n) => addDaysKey(t, n));
  }, []);
  const nowHHMM = new Date().toLocaleTimeString("en-GB", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false });
  const when = exact || (day && time ? `${day}T${time}` : "");
  const ready = !!outcome && (!NEEDS_TIME.has(outcome) || !!when);

  const choose = (k: string) => {
    setOutcome(k);
    setDay(""); setTime(""); setExact(""); setPriority("");
  };

  const save = async () => {
    const body: ActivityBody = {
      outcome, notes: notes.trim() || undefined, call_seconds: secs,
      call_started_at: new Date(call.startedAt).toISOString(),
    };
    if (outcome === "callback_requested") body.callback_at = localInputToISO(when);
    if (outcome === "appointment_booked") {
      body.appointment_at = localInputToISO(when);
      body.store_id = storeId ? Number(storeId) : null;
    }
    if (outcome === "converted" && sale.trim()) body.sale_amount = sale.trim();
    try {
      const res = await log.mutateAsync({ leadId: call.leadId, body });
      if (priority && res.lead.priority !== priority) {
        await patch.mutateAsync({ leadId: call.leadId, body: { priority } }).catch(() => undefined);
      }
      toast.success(res.next_follow_up
        ? `Saved. Next: ${res.next_follow_up.reason} · ${fmtDateTime(res.next_follow_up.due_at)}`
        : "Saved. This lead is closed.");
      clear();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the call");
    }
  };

  return (
    <>
      <header className="shrink-0 flex items-center gap-3 px-4 pt-3 pb-3">
        <button onClick={resume} aria-label="Back to the call"
          className="w-10 h-10 rounded-lg grid place-items-center border border-[var(--border-subtle)] bg-[var(--bg-card)] cursor-pointer">
          <ChevronLeft size={20} />
        </button>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-extrabold leading-tight">Call report</h2>
          <p className="text-xs text-[var(--text-muted)]">Tap what happened</p>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto px-4 pb-4 space-y-3 min-h-0">
        <div className="flex items-center gap-3 rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-3.5">
          <span className="w-12 h-12 rounded-full grid place-items-center text-base font-bold text-white bg-violet-600 shrink-0">{initials(call.name)}</span>
          <div className="min-w-0 flex-1 space-y-1">
            <p className="font-semibold truncate">{call.name}</p>
            <StatusTag status={call.status} />
          </div>
          <span className="w-px self-stretch bg-[var(--border-subtle)]" />
          <span className="w-9 h-9 rounded-full grid place-items-center bg-[var(--bg-subtle)] text-[var(--text-muted)] shrink-0">
            <Phone size={16} fill="currentColor" strokeWidth={0} />
          </span>
          <p className="text-right leading-tight pr-1">
            <span className="block text-xs text-[var(--text-muted)]">Call ended</span>
            <span className="block text-base font-bold tabular-nums text-[var(--text-primary)]">{mmss(secs)}</span>
          </p>
        </div>

        {OUTCOME_GROUPS.map((g) => (
          <div key={g.label} className="space-y-2">
            <GroupLabel>{g.label}</GroupLabel>
            <div className="grid grid-cols-4 gap-2">
              {orderTiles(g.outcomes).map((o) => {
                const look = OUTCOME_LOOK[o.key] ?? { icon: <Ellipsis size={19} />, tone: "grey", short: o.label };
                const on = outcome === o.key;
                return (
                  <button key={o.key} type="button" onClick={() => choose(o.key)} aria-pressed={on} title={o.hint}
                    className={cn("flex flex-col items-center gap-2 rounded-xl border px-0.5 py-3 text-[12px] font-medium leading-tight text-center text-[var(--text-primary)] cursor-pointer",
                      on ? "border-blue-500 bg-blue-500/10 ring-2 ring-blue-500/20" : "border-[var(--border-subtle)] bg-[var(--bg-card)]")}>
                    <span className={cn("w-11 h-11 rounded-xl grid place-items-center", TONE[look.tone])}>{look.icon}</span>
                    {look.short}
                  </button>
                );
              })}
            </div>
          </div>
        ))}

        {outcome && (
          <p className="text-xs text-[var(--text-muted)]">
            {OUTCOME_GROUPS.flatMap((g) => g.outcomes).find((o) => o.key === outcome)?.hint}
          </p>
        )}

        {NEEDS_TIME.has(outcome) && (
          <div className="space-y-2 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-card)] p-3">
            <p className="text-sm font-bold">{outcome === "appointment_booked" ? "Book the store visit" : "When should you call back?"}</p>
            <GroupLabel>Day</GroupLabel>
            <div className="flex flex-wrap gap-1.5">
              {days.map((d, i) => <Pick key={d} on={!exact && day === d} onClick={() => { setDay(d); setExact(""); }}>{dayLabel(d, i)}</Pick>)}
            </div>
            <GroupLabel>Time</GroupLabel>
            <div className="flex flex-wrap gap-1.5">
              {QUICK_TIMES.map((t) => (
                <Pick key={t} on={!exact && time === t} disabled={day === days[0] && t <= nowHHMM}
                  onClick={() => { setTime(t); setExact(""); }}>{timeLabel(t)}</Pick>
              ))}
            </div>
            <GroupLabel>Or pick an exact time</GroupLabel>
            <input type="datetime-local" value={exact} onChange={(e) => setExact(e.target.value)}
              className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-subtle)] px-3 py-2.5 text-[15px] text-[var(--text-primary)]" />
            {outcome === "appointment_booked" && (
              <>
                <GroupLabel>Store</GroupLabel>
                <select value={storeId} onChange={(e) => setStoreId(e.target.value)}
                  className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-subtle)] px-3 py-2.5 text-[15px] text-[var(--text-primary)]">
                  <option value="">Not set</option>
                  {meta?.stores.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </>
            )}
          </div>
        )}

        {outcome === "converted" && (
          <div className="space-y-2 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-card)] p-3">
            <p className="text-sm font-bold">Sale amount</p>
            <input inputMode="numeric" value={sale} onChange={(e) => setSale(e.target.value)} placeholder="₹ e.g. 12000 (optional)"
              className="w-full rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-subtle)] px-3 py-2.5 text-[15px] text-[var(--text-primary)]" />
          </div>
        )}

        {ASK_PRIORITY.has(outcome) && (
          <div className="space-y-2 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-card)] p-3">
            <p className="text-sm font-bold">How interested? <span className="font-normal text-xs text-[var(--text-muted)]">optional</span></p>
            <div className="flex gap-1.5">
              {PRIORITIES.map((p) => (
                <Pick key={p.key} on={priority === p.key} onClick={() => setPriority(priority === p.key ? "" : p.key)}>
                  <span className="inline-block w-2 h-2 rounded-full mr-1.5" style={{ backgroundColor: p.color }} />{p.label}
                </Pick>
              ))}
            </div>
          </div>
        )}

        <div className="relative">
          <textarea value={notes} onChange={(e) => setNotes(e.target.value.slice(0, NOTE_MAX))} rows={4} maxLength={NOTE_MAX}
            placeholder="Other notes (optional)"
            className="w-full resize-none rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-3 pb-6 text-sm text-[var(--text-primary)]" />
          <span className="absolute right-3 bottom-3 text-[11px] text-[var(--text-muted)] tabular-nums">{notes.length}/{NOTE_MAX}</span>
        </div>
      </div>

      <footer className="shrink-0 px-4 pt-2.5 pb-3 border-t border-[var(--border-subtle)] space-y-1">
        <button onClick={save} disabled={!ready || log.isPending}
          className="w-full py-3.5 rounded-xl bg-blue-600 text-white font-semibold text-[15px] cursor-pointer disabled:opacity-45 disabled:cursor-not-allowed">
          {log.isPending ? "Saving…" : "Save and continue"}
        </button>
        {NEEDS_TIME.has(outcome) && !when && <p className="text-[11px] text-center text-[var(--text-muted)]">Pick a day and time first</p>}
      </footer>
    </>
  );
}
