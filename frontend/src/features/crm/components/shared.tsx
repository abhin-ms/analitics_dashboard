import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { PhoneCall, Clock } from "lucide-react";
import { getSocket } from "@/lib/socket";
import { useAuthStore } from "@/lib/authStore";
import { useToast } from "@/components/shared/Toast";
import { cn, localDateStr } from "@/lib/utils";
import { CRM_KEY } from "../api";
import { FOLLOWUP_KIND_LABELS, STATUS_CHIP_ORDER, statusColor } from "../statusConfig";
import type { CrmLead, Followup } from "../types";
import { fmtDue } from "../format";
import { openLead } from "./LeadDrawer";
import { LogActivityDialog } from "./dialogs";
import { Avatar, Button, PriorityBadge, StatusBadge } from "./ui";

/** Clickable status chips with counts ("All statuses · 8", "No Status · 1", …). */
export function StatusChips({ counts, value, onChange, showAll = true, size = "md" }: {
  counts: Record<string, number>; value?: string; onChange?: (status: string) => void;
  showAll?: boolean; size?: "sm" | "md";
}) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const keys = [...STATUS_CHIP_ORDER.filter((s) => counts[s]), ...Object.keys(counts).filter((s) => !STATUS_CHIP_ORDER.includes(s as never))];
  const chip = (key: string, label: string, n: number, color: string) => {
    const active = (value || "") === key;
    const Tag = onChange ? "button" : "span";
    return (
      <Tag
        key={key || "all"}
        onClick={onChange ? () => onChange(active && key ? "" : key) : undefined}
        className={cn(
          "inline-flex items-center gap-1.5 rounded-xl border transition-colors",
          size === "sm" ? "px-2 py-1 text-[11px]" : "px-3 py-1.5 text-xs",
          onChange && "cursor-pointer hover:bg-[var(--bg-card-hover)]",
          active ? "font-semibold" : "text-[var(--text-secondary)]",
        )}
        style={{
          borderColor: active ? color : "var(--border-subtle)",
          backgroundColor: active ? `${color}1f` : "var(--bg-card)",
          color: active ? color : undefined,
        }}
      >
        {key && <span className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />}
        {label} <span className="font-semibold">· {n}</span>
      </Tag>
    );
  };
  return (
    <div className="flex flex-wrap gap-2">
      {showAll && chip("", "All statuses", total, "#3b82f6")}
      {keys.map((k) => chip(k, k, counts[k]!, statusColor(k)))}
    </div>
  );
}

/** Horizontal stacked bar of status counts (compact visual for dashboards). */
export function StatusBar({ counts }: { counts: Record<string, number> }) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  if (!total) return null;
  return (
    <div className="flex h-2 w-full overflow-hidden rounded-full bg-[var(--bg-primary)]">
      {Object.entries(counts).map(([k, n]) => (
        <div key={k} title={`${k}: ${n}`} style={{ width: `${(n / total) * 100}%`, backgroundColor: statusColor(k) }} />
      ))}
    </div>
  );
}

/** One follow-up row: avatar, lead name (opens drawer), kind · owner · due, action. */
export function FollowupRow({ f, showOwner = true }: { f: Followup; showOwner?: boolean }) {
  const [logging, setLogging] = useState(false);
  const due = fmtDue(f.due_at);
  const lead = f.lead!;
  const asLead = { id: lead.id, full_name: lead.full_name, service_type: lead.service_type } as CrmLead;
  return (
    <div className="flex items-center gap-3 px-5 py-3">
      <Avatar name={lead.full_name} color={due.overdue ? "#ef4444" : "#3b82f6"} />
      <div className="min-w-0 flex-1">
        <button onClick={() => openLead(lead.id)} className="text-sm font-medium text-blue-400 hover:underline cursor-pointer text-left truncate block max-w-full">
          {lead.full_name}
        </button>
        <p className="text-[11px] text-[var(--text-muted)] flex flex-wrap items-center gap-x-1.5">
          <span>{FOLLOWUP_KIND_LABELS[f.kind] || f.kind}</span>
          {showOwner && f.owner_name && <span>· {f.owner_name}</span>}
          <span>·</span>
          <span className={due.overdue ? "text-rose-400 font-semibold" : ""}>{due.text}</span>
          {lead.phone_model && <span>· {lead.phone_model}</span>}
        </p>
      </div>
      <div className="hidden sm:flex items-center gap-1.5">
        <StatusBadge status={lead.status} />
        <PriorityBadge priority={lead.priority} />
      </div>
      <Button size="sm" onClick={() => setLogging(true)}><PhoneCall size={13} />Log activity</Button>
      {logging && <LogActivityDialog lead={asLead} open onClose={() => setLogging(false)} />}
    </div>
  );
}

export function EmptyFollowups({ text }: { text: string }) {
  return (
    <div className="px-5 py-8 text-center text-sm text-[var(--text-muted)] flex flex-col items-center gap-2">
      <Clock size={18} />{text}
    </div>
  );
}

// ── period filter ──
export type PeriodKey = "all" | "today" | "7d" | "month" | "30d" | "custom";

export function periodRange(key: PeriodKey, custom?: { start: string; end: string }): { start: string; end: string } {
  const now = new Date();
  const end = localDateStr(now);
  if (key === "all") return { start: "", end: "" };
  if (key === "today") return { start: end, end };
  if (key === "7d") return { start: localDateStr(new Date(now.getTime() - 6 * 86400000)), end };
  if (key === "30d") return { start: localDateStr(new Date(now.getTime() - 29 * 86400000)), end };
  if (key === "month") return { start: localDateStr(new Date(now.getFullYear(), now.getMonth(), 1)), end };
  return custom || { start: end, end };
}

export function PeriodFilter({ value, onChange, custom, onCustom, allowAll }: {
  value: PeriodKey; onChange: (k: PeriodKey) => void;
  custom: { start: string; end: string }; onCustom: (c: { start: string; end: string }) => void;
  allowAll?: boolean;
}) {
  const opts: { key: PeriodKey; label: string }[] = [
    ...(allowAll ? [{ key: "all" as PeriodKey, label: "All time" }] : []),
    { key: "today", label: "Today" }, { key: "7d", label: "7 days" }, { key: "month", label: "This month" },
    { key: "30d", label: "30 days" }, { key: "custom", label: "Custom" },
  ];
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="inline-flex rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-0.5">
        {opts.map((o) => (
          <button key={o.key} onClick={() => onChange(o.key)}
            className={cn("px-2.5 py-1 text-xs rounded-lg cursor-pointer",
              value === o.key ? "bg-blue-500/15 text-blue-400 font-semibold" : "text-[var(--text-secondary)] hover:text-white")}>
            {o.label}
          </button>
        ))}
      </div>
      {value === "custom" && (
        <div className="flex items-center gap-1.5 text-xs">
          <input type="date" value={custom.start} onChange={(e) => onCustom({ ...custom, start: e.target.value })}
            className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-primary)] px-2 py-1 text-[var(--text-primary)]" />
          <span className="text-[var(--text-muted)]">to</span>
          <input type="date" value={custom.end} onChange={(e) => onCustom({ ...custom, end: e.target.value })}
            className="rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-primary)] px-2 py-1 text-[var(--text-primary)]" />
        </div>
      )}
    </div>
  );
}

/** Listens for live CRM alerts pushed to this user and shows a toast. */
export function useCrmAlertListener() {
  const qc = useQueryClient();
  const toast = useToast();
  const toastRef = useRef(toast);
  toastRef.current = toast;
  const isAuthenticated = useAuthStore((s) => !!s.token);
  useEffect(() => {
    if (!isAuthenticated) return;
    const socket = getSocket();
    if (!socket) return;
    const onAlert = (a: { title: string; body?: string | null }) => {
      toastRef.current.error(`${a.title}${a.body ? ` — ${a.body}` : ""}`);
      qc.invalidateQueries({ queryKey: [CRM_KEY] });
    };
    const onRefresh = (p: { section?: string }) => {
      if (p?.section === "tele_call_leads") {
        qc.invalidateQueries({ queryKey: [CRM_KEY] });
        qc.invalidateQueries({ queryKey: ["dashboard"] });
      }
    };
    socket.on("crm:alert", onAlert);
    socket.on("data:refresh", onRefresh);
    return () => {
      socket.off("crm:alert", onAlert);
      socket.off("data:refresh", onRefresh);
    };
  }, [isAuthenticated, qc]);
}

export function CrmGlobalListeners() {
  useCrmAlertListener();
  return null;
}
