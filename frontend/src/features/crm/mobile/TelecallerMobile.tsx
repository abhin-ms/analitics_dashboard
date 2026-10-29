/** Telecaller dashboard on phones and tablets: today's call list with a
 * one-tap Call button and auto-dial, follow-ups, appointments and my stats.
 * Laptops and desktops keep the full TelecallerDashboard (see RoleDashboard). */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  BarChart3, CalendarCheck, ChevronDown, Clock, Coffee, Ellipsis, LayoutDashboard, Pause, Phone, Play, Search,
  ShieldCheck, X,
} from "lucide-react";
import { useToast } from "@/components/shared/Toast";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useAuthStore } from "@/lib/authStore";
import { useUIStore } from "@/lib/uiStore";
import { cn } from "@/lib/utils";
import { useAppointments, useCrmLeads, useFollowups, useSetAvailability } from "../api";
import type { AgentRow, CrmLead } from "../types";
import { FOLLOWUP_KIND_LABELS, statusColor } from "../statusConfig";
import { fmtDateTime, fmtDayLabel, fmtINR, fmtTime, istDateKey, todayIST } from "../format";
import { openLead, useLeadDrawer } from "../components/LeadDrawer";
import { CallButton, CallFlowHost, SourceTag, StatusTag, dial, initials } from "./CallFlow";
import { useActiveCall } from "./activeCall";

type Tab = "calls" | "follow" | "appts" | "me";

const CLOSED_STAGES = new Set(["converted", "not_interested"]);
const CLOSED_STATUSES = new Set(["Wrong number", "Sale Conversion", "Not Interested"]);
const AUTO_DIAL_SECONDS = 10;

function isOpen(l: CrmLead) {
  return !CLOSED_STAGES.has(l.stage) && !CLOSED_STATUSES.has(l.status);
}
function isNew(l: CrmLead) {
  return l.first_call_pending || !l.status || l.status === "No Status";
}
function isOverdue(l: CrmLead) {
  return l.first_call_pending || (!!l.next_follow_up_at && new Date(l.next_follow_up_at).getTime() < Date.now());
}

function leadTarget(l: CrmLead) {
  return {
    leadId: l.id, name: l.full_name || "Unknown", phone: l.phone, status: l.status || "No Status",
    source: l.source_label, note: l.remarks || undefined,
  };
}

/** "11:30 AM" today, "19 Oct" another day. */
function dueLabel(l: CrmLead): { text: string; late: boolean } {
  if (l.in_night_queue) return { text: "Night lead", late: false }; // came in at night: due once its message goes out
  if (isOverdue(l)) return { text: "Due now", late: true };
  if (!l.next_follow_up_at) return { text: isNew(l) ? "Due now" : "No time set", late: isNew(l) };
  const d = new Date(l.next_follow_up_at);
  if (istDateKey(d) === todayIST()) {
    return { text: d.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit", hour12: true }).toUpperCase(), late: false };
  }
  return { text: d.toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short" }), late: false };
}

export default function TelecallerMobile({ data, onShowFull }: { data: any; onShowFull: () => void }) {
  const [tab, setTab] = useState<Tab>("calls");
  const followups = useFollowups(true);
  const followCount = (followups.data?.overdue.length ?? 0) + (followups.data?.today.length ?? 0);
  const leads = useCrmLeads({ tab: "mine", sort: "smart", page_size: 200 });
  const open = useMemo(() => (leads.data?.items || []).filter(isOpen), [leads.data]);
  const queue = useMemo(() => [...open.filter(isOverdue), ...open.filter((l) => !isOverdue(l))], [open]);

  return (
    <div className="-mx-2 -mt-2 sm:m-0 pb-44 max-w-2xl sm:mx-auto">
      {tab === "calls" && <CallsTab data={data} queue={queue} loading={leads.isLoading} onShowFull={onShowFull} />}
      {tab === "follow" && <FollowupsTab />}
      {tab === "appts" && <AppointmentsTab />}
      {tab === "me" && <StatsTab my={data?.my} onShowFull={onShowFull} />}
      <BottomBar tab={tab} onChange={setTab} followCount={followCount} queue={tab === "calls" ? queue : undefined} />
      <CallFlowHost />
    </div>
  );
}

function TopBar({ title, sub, right }: { title: string; sub: string; right?: ReactNode }) {
  return (
    <header className="flex items-center gap-2 pb-4">
      <div className="min-w-0 flex-1">
        <h1 className="text-[24px] font-extrabold text-[var(--text-primary)] leading-tight tracking-tight">{title}</h1>
        <p className="text-sm text-[var(--text-muted)] mt-0.5">{sub}</p>
      </div>
      {right}
    </header>
  );
}

function IconButton({ label, onClick, children, active }: { label: string; onClick: () => void; children: ReactNode; active?: boolean }) {
  return (
    <button onClick={onClick} aria-label={label} title={label}
      className={cn("w-10 h-10 rounded-full grid place-items-center cursor-pointer text-[var(--text-primary)]",
        active ? "bg-blue-500/12 text-blue-500" : "hover:bg-[var(--bg-card-hover)]")}>
      {children}
    </button>
  );
}

/** The ⋯ menu: availability and the full desktop dashboard. */
function MoreMenu({ available, onShowFull }: { available: boolean | undefined; onShowFull: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const toast = useToast();
  const setAvail = useSetAvailability();
  useEffect(() => {
    if (!open) return;
    const close = (e: PointerEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("pointerdown", close);
    return () => document.removeEventListener("pointerdown", close);
  }, [open]);
  const item = "w-full flex items-center gap-2.5 px-3.5 py-3 text-sm text-left text-[var(--text-primary)] hover:bg-[var(--bg-card-hover)] cursor-pointer";
  return (
    <div className="relative" ref={ref}>
      <IconButton label="More" onClick={() => setOpen(!open)} active={open}><Ellipsis size={22} /></IconButton>
      {open && (
        <div className="absolute right-0 top-11 z-40 w-60 rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-card)] shadow-lg overflow-hidden">
          {available !== undefined && (
            <button className={item} disabled={setAvail.isPending} onClick={async () => {
              await setAvail.mutateAsync({ available: !available });
              toast.success(available ? "You are Away — new leads won't be auto-assigned to you" : "You are Available");
              setOpen(false);
            }}>
              {available ? <ShieldCheck size={17} className="text-emerald-500" /> : <Coffee size={17} className="text-amber-500" />}
              <span className="flex-1">{available ? "Available" : "Away"}</span>
              <span className="text-xs text-blue-500">{available ? "Set away" : "Set available"}</span>
            </button>
          )}
          <button className={cn(item, "border-t border-[var(--border-subtle)]")} onClick={onShowFull}>
            <LayoutDashboard size={17} className="text-[var(--text-muted)]" />Open full dashboard
          </button>
        </div>
      )}
    </div>
  );
}

function CallsTab({ data, queue, loading, onShowFull }: { data: any; queue: CrmLead[]; loading: boolean; onShowFull: () => void }) {
  const user = useAuthStore((s) => s.user);
  const [searching, setSearching] = useState(false);
  const [q, setQ] = useState("");
  const needle = q.trim().toLowerCase();
  const digits = needle.replace(/\D/g, "");
  const list = needle
    ? queue.filter((l) => (l.full_name || "").toLowerCase().includes(needle) || (digits.length >= 3 && (l.phone || "").replace(/\D/g, "").includes(digits)))
    : queue;
  const overdue = list.filter(isOverdue);
  const rest = list.filter((l) => !isOverdue(l));
  const today = new Date().toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", weekday: "long", day: "numeric", month: "short" });

  return (
    <>
      <TopBar title="Today's calls" sub={today} right={<>
        <IconButton label="Search" onClick={() => { setSearching(!searching); setQ(""); }} active={searching}><Search size={21} /></IconButton>
        <MoreMenu available={data ? !!data.available : undefined} onShowFull={onShowFull} />
        <span className="ml-1 w-12 h-12 rounded-full grid place-items-center text-base font-bold bg-violet-600" style={{ color: "#fff" }}>
          {initials(user?.name || "")}
        </span>
      </>} />

      {searching && (
        <div className="relative mb-3">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name or number"
            className="w-full rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-card)] pl-9 pr-9 py-2.5 text-[15px] text-[var(--text-primary)]" />
          {q && <button onClick={() => setQ("")} aria-label="Clear" className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[var(--text-muted)] cursor-pointer"><X size={16} /></button>}
        </div>
      )}

      {loading ? <TableSkeleton /> : list.length === 0 ? (
        <p className="text-center text-sm text-[var(--text-muted)] py-10">
          {needle ? "No lead matches that search." : "No open leads right now. New leads show up here as they arrive."}
        </p>
      ) : (
        <div className="space-y-4">
          {overdue.length > 0 && <Group label="Overdue" count={overdue.length} late>{overdue.map((l) => <LeadCard key={l.id} lead={l} />)}</Group>}
          {rest.length > 0 && <Group label="Up next today" count={rest.length}>{rest.map((l) => <LeadCard key={l.id} lead={l} />)}</Group>}
        </div>
      )}
    </>
  );
}

function Group({ label, count, late, children }: { label: string; count: number; late?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(true);
  return (
    <section className="rounded-2xl bg-[var(--bg-subtle)] border border-[var(--border-subtle)] overflow-hidden">
      <button onClick={() => setOpen(!open)} aria-expanded={open}
        className="w-full flex items-center gap-3 px-4 py-3.5 text-left cursor-pointer">
        <ChevronDown size={20} className={cn("text-[var(--text-primary)] transition-transform", !open && "-rotate-90")} />
        <span className="text-[17px] font-bold text-[var(--text-primary)]">{label}</span>
        <span className={cn("min-w-7 h-7 px-2 rounded-full grid place-items-center text-sm font-semibold",
          late ? "bg-rose-500/12 text-rose-500" : "bg-[var(--border-subtle)] text-[var(--text-secondary)]")}>{count}</span>
      </button>
      {open && <div className="divide-y divide-[var(--border-subtle)] bg-[var(--bg-card)] border-t border-[var(--border-subtle)]">{children}</div>}
    </section>
  );
}

function LeadCard({ lead }: { lead: CrmLead }) {
  const due = dueLabel(lead);
  const edge = isOverdue(lead) ? "#f87171" : `${statusColor(lead.status)}66`;
  return (
    <div className="flex items-center gap-2.5 pl-3 pr-2.5 py-3" style={{ boxShadow: `inset 4px 0 0 ${edge}` }}>
      <button onClick={() => openLead(lead.id)} className="flex items-center gap-2.5 min-w-0 flex-1 text-left cursor-pointer pl-1">
        <span className="w-11 h-11 rounded-full grid place-items-center text-[15px] font-semibold bg-violet-500/12 text-violet-600 shrink-0">
          {initials(lead.full_name || "?")}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block font-medium text-[16px] text-[var(--text-primary)] truncate">{lead.full_name || "Unknown"}</span>
          {/* As in the design: "New" for an uncalled lead, then the source.
              Other statuses show as the card's coloured edge (full status in the drawer). */}
          <span className="flex items-center gap-1.5 mt-1 overflow-hidden">
            {isNew(lead) && <StatusTag status="" soft />}
            <SourceTag source={lead.source} label={lead.source_label} />
          </span>
        </span>
      </button>
      <span className="w-px h-10 bg-[var(--border-subtle)] shrink-0" />
      <span className={cn("flex items-center gap-1 w-[80px] shrink-0 text-[13px] whitespace-nowrap", due.late ? "text-rose-500" : "text-[var(--text-secondary)]")}>
        <Clock size={15} className="text-[var(--text-muted)] shrink-0" />{due.text}
      </span>
      <CallButton target={leadTarget(lead)} />
    </div>
  );
}

function FollowupsTab() {
  const { data, isLoading } = useFollowups(true);
  const rows = [...(data?.overdue || []), ...(data?.today || []), ...(data?.upcoming || [])];
  return (
    <>
      <TopBar title="Follow-ups" sub="Calls you promised to make" />
      {isLoading ? <TableSkeleton /> : rows.length === 0 ? (
        <p className="text-center text-sm text-[var(--text-muted)] py-10">No follow-ups scheduled.</p>
      ) : (
        <div className="space-y-2">
          {rows.map((f) => f.lead && (
            <div key={f.id} className="flex items-center gap-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-card)] px-3 py-2.5">
              <button onClick={() => openLead(f.lead!.id)} className="min-w-0 flex-1 text-left cursor-pointer">
                <p className="font-semibold text-[15px] text-[var(--text-primary)] truncate">{f.lead.full_name}</p>
                <p className="text-xs text-[var(--text-muted)] mt-0.5">
                  {f.reason || FOLLOWUP_KIND_LABELS[f.kind] || "Call"} · {" "}
                  <span className={f.overdue ? "text-rose-400 font-semibold" : ""}>{f.overdue ? "Overdue · " : ""}{fmtDateTime(f.due_at)}</span>
                </p>
              </button>
              <CallButton target={{ leadId: f.lead.id, name: f.lead.full_name, phone: f.lead.phone, status: f.lead.status || "No Status" }} />
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function AppointmentsTab() {
  const { data, isLoading } = useAppointments(todayIST(), 7, true);
  const rows = (data?.columns || []).flatMap((c) => c.items);
  return (
    <>
      <TopBar title="Appointments" sub="Store visits in the next 7 days" />
      {isLoading ? <TableSkeleton /> : rows.length === 0 ? (
        <p className="text-center text-sm text-[var(--text-muted)] py-10">No appointments booked.</p>
      ) : (
        <div className="space-y-2">
          {rows.map((a) => (
            <div key={`${a.source}-${a.id ?? a.lead_id}-${a.date}`} className="flex items-center gap-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-card)] px-3 py-2.5">
              <button onClick={() => openLead(a.lead_id)} className="min-w-0 flex-1 text-left cursor-pointer">
                <p className="font-semibold text-[15px] text-[var(--text-primary)] truncate">{a.lead_name}</p>
                <p className="text-xs text-[var(--text-muted)] mt-0.5">
                  {fmtDayLabel(a.date)}
                  {a.has_time ? ` · ${fmtTime(a.scheduled_at)}` : ""}{a.purpose ? ` · ${a.purpose}` : ""}
                </p>
              </button>
              <CallButton target={{ leadId: a.lead_id, name: a.lead_name, phone: a.phone, status: "Appointment" }} />
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function StatsTab({ my, onShowFull }: { my: AgentRow | undefined; onShowFull: () => void }) {
  const name = useAuthStore((s) => s.user?.name) || "";
  const kpis: [string, string | number, string][] = my ? [
    ["Calls logged", my.calls_logged ?? 0, "#579bfc"],
    ["Connected", `${my.connected_pct}%`, "#00a862"],
    ["Appointments", my.appointments, "#a25ddc"],
    ["Converted", my.converted, "#e8833a"],
    ["First calls on time", my.first_call_pct != null ? `${my.first_call_pct}%` : "—", "#ff642e"],
    ["Follow-ups on time", my.followups_on_time_pct != null ? `${my.followups_on_time_pct}%` : "—", "#e2445c"],
  ] : [];
  return (
    <>
      <TopBar title="My stats" sub={name ? `${name} · all time` : "All time"} />
      {!my ? <TableSkeleton /> : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            {kpis.map(([label, value, color]) => (
              <div key={label} className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-card)] p-3.5">
                <b className="block text-2xl tabular-nums" style={{ color }}>{value}</b>
                <span className="text-xs text-[var(--text-muted)]">{label}</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-[var(--text-muted)]">Sale amount: <span className="text-emerald-400 font-semibold">{fmtINR(my.total_sale_amount)}</span></p>
          <button onClick={onShowFull}
            className="w-full inline-flex items-center justify-center gap-2 py-3 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-card)] text-sm font-semibold text-[var(--text-primary)] cursor-pointer">
            <LayoutDashboard size={16} />Open full dashboard
          </button>
        </div>
      )}
    </>
  );
}


/** Blue auto-dial strip: counts down, then opens the dialer for the next
 * lead. Off until the telecaller taps play; it remembers the choice. It only
 * counts while the list is in front (no call, no lead drawer, app visible)
 * and never redials a lead it already called this session. */
function AutoDialBar({ queue }: { queue: CrmLead[] }) {
  const autoDial = useActiveCall((s) => s.autoDial);
  const setAutoDial = useActiveCall((s) => s.setAutoDial);
  const call = useActiveCall((s) => s.call);
  const drawerOpen = useLeadDrawer((s) => s.leadId != null);
  const dialed = useRef(new Set<number>());
  const next = queue.find((l) => !dialed.current.has(l.id));
  const [count, setCount] = useState(AUTO_DIAL_SECONDS);
  const running = autoDial && !call && !drawerOpen && !!next;

  useEffect(() => { setCount(AUTO_DIAL_SECONDS); }, [next?.id, call, autoDial]);
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") setCount((c) => c - 1);
    }, 1000);
    return () => window.clearInterval(id);
  }, [running]);
  useEffect(() => {
    if (!running || count > 0 || !next) return;
    dialed.current.add(next.id);
    if (!dial(leadTarget(next))) setCount(AUTO_DIAL_SECONDS); // no number: move on to the next lead
  }, [running, count, next]);

  if (!next) return null;
  const R = 22;
  const C = 2 * Math.PI * R;
  const shown = Math.max(count, 0);
  return (
    <div className="mx-3 mb-2 rounded-2xl bg-blue-600 px-3.5 py-3 flex items-center gap-3.5 shadow-lg" style={{ color: "#fff" }}>
      <span className="relative w-14 h-14 grid place-items-center shrink-0 text-lg font-bold tabular-nums">
        <svg width="56" height="56" className="absolute inset-0 -rotate-90">
          <circle cx="28" cy="28" r={R} fill="none" stroke="currentColor" strokeOpacity={0.25} strokeWidth={3.5} />
          {autoDial && (
            <circle cx="28" cy="28" r={R} fill="none" stroke="currentColor" strokeWidth={3.5} strokeLinecap="round"
              strokeDasharray={C} strokeDashoffset={C * (1 - shown / AUTO_DIAL_SECONDS)} style={{ transition: "stroke-dashoffset 1s linear" }} />
          )}
        </svg>
        {autoDial ? shown : <Phone size={18} fill="currentColor" strokeWidth={0} />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[13.5px] opacity-85">{autoDial ? `Auto-dial · next call in ${shown}s` : "Auto-dial is off · next call"}</span>
        <span className="block text-[18px] font-bold truncate">{next.full_name || "Unknown"}</span>
      </span>
      <button onClick={() => setAutoDial(!autoDial)} aria-label={autoDial ? "Pause auto-dial" : "Start auto-dial"}
        className="w-12 h-12 rounded-full grid place-items-center bg-white text-blue-600 shrink-0 cursor-pointer active:scale-95 transition-transform">
        {autoDial ? <Pause size={20} fill="currentColor" strokeWidth={0} /> : <Play size={20} fill="currentColor" strokeWidth={0} className="ml-0.5" />}
      </button>
    </div>
  );
}

function BottomBar({ tab, onChange, followCount, queue }: {
  tab: Tab; onChange: (t: Tab) => void; followCount: number; queue?: CrmLead[];
}) {
  // Sits right of the sidebar on tablets (it is a fixed column from 768px).
  const collapsed = useUIStore((s) => s.sidebarCollapsed);
  const [isMd, setIsMd] = useState(false);
  useEffect(() => {
    const mql = window.matchMedia("(min-width: 768px)");
    const handler = () => setIsMd(mql.matches);
    handler();
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);
  const left = isMd ? (collapsed ? 80 : 256) : 0;

  const items: [Tab, string, ReactNode, number][] = [
    ["calls", "Calls", <Phone size={23} fill={tab === "calls" ? "currentColor" : "none"} />, 0],
    ["follow", "Follow-ups", <Clock size={23} />, followCount],
    ["appts", "Appointments", <CalendarCheck size={23} />, 0],
    ["me", "My stats", <BarChart3 size={23} />, 0],
  ];
  return (
    <div className="fixed bottom-0 right-0 z-30" style={{ left }}>
      {queue && <div className="max-w-2xl mx-auto"><AutoDialBar queue={queue} /></div>}
      <nav className="grid grid-cols-4 border-t border-[var(--border-subtle)] bg-[var(--bg-card)] pt-2"
        style={{ paddingBottom: "max(10px, env(safe-area-inset-bottom))" }}>
        {items.map(([k, label, icon, badge]) => (
          <button key={k} onClick={() => onChange(k)} aria-current={tab === k ? "page" : undefined}
            className={cn("relative flex flex-col items-center gap-1 py-1 text-[12px] font-medium cursor-pointer",
              tab === k ? "text-blue-500 font-semibold" : "text-[var(--text-secondary)]")}>
            {icon}{label}
            {badge > 0 && (
              <span className="absolute top-0 left-[calc(50%+6px)] min-w-4 h-4 px-1 rounded-full bg-rose-600 text-[10px] grid place-items-center" style={{ color: "#fff" }}>
                {badge > 99 ? "99+" : badge}
              </span>
            )}
          </button>
        ))}
      </nav>
    </div>
  );
}
