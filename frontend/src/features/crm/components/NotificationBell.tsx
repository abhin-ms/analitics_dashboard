import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Bell, BellRing, Flame, Volume2, VolumeX, X } from "lucide-react";
import { getSocket } from "@/lib/socket";
import { useAuthStore } from "@/lib/authStore";
import { isSoundMuted, playLeadChime, setSoundMuted, unlockAudioOnFirstGesture } from "@/lib/leadSound";
import { CRM_KEY, type LeadNotification, useMarkNotificationsRead, useNotifications } from "../api";
import { fmtRelative } from "../format";
import { openLead } from "./LeadDrawer";

/** Leads just announced here, so the older crm:alert toast for the same
 *  lead (premium / unassigned) doesn't pop up a second time. */
const recentlyNotified = new Map<number, number>();
export function wasJustNotified(leadId: number | null | undefined): boolean {
  const at = leadId ? recentlyNotified.get(leadId) : undefined;
  return !!at && Date.now() - at < 15_000;
}

interface Popup { key: number; title: string; body: string; leadId: number | null; hot: boolean; ids: number[] }

const KIND_COLOR: Record<string, string> = { lead_assigned: "#3b82f6", lead_branch: "#94a3b8", lead_unassigned: "#f59e0b" };

function desktopPermission(): NotificationPermission | "unsupported" {
  return typeof window !== "undefined" && "Notification" in window ? Notification.permission : "unsupported";
}

export function NotificationBell() {
  const isAuthenticated = useAuthStore((s) => !!s.token);
  const qc = useQueryClient();
  const { data } = useNotifications(isAuthenticated);
  const markRead = useMarkNotificationsRead();
  const [open, setOpen] = useState(false);
  const [muted, setMuted] = useState(isSoundMuted);
  const [perm, setPerm] = useState(desktopPermission);
  const [popups, setPopups] = useState<Popup[]>([]);
  const buffer = useRef<LeadNotification[]>([]);
  const timer = useRef<number | null>(null);
  const popupKey = useRef(1);

  useEffect(() => unlockAudioOnFirstGesture(), []);

  useEffect(() => {
    if (!isAuthenticated) return;
    const socket = getSocket();
    if (!socket) return;

    // Several leads in one sync arrive together: show them as one popup,
    // one sound and one desktop notification.
    const flush = () => {
      timer.current = null;
      const items = buffer.current;
      buffer.current = [];
      if (!items.length) return;
      qc.invalidateQueries({ queryKey: [CRM_KEY] });
      const hot = items.some((n) => n.is_hot);
      const one = items.length === 1 ? items[0] : null;
      const title = one ? one.title : `${items.length} new leads${hot ? " (incl. 🔥 hot)" : ""}`;
      const body = one ? one.body || "" : items.slice(0, 3).map((n) => n.title).join(" · ") + (items.length > 3 ? " …" : "");
      playLeadChime(hot);
      const key = popupKey.current++;
      setPopups((p) => [...p.slice(-3), { key, title, body, leadId: one?.lead_id ?? null, hot, ids: items.map((n) => n.id) }]);
      window.setTimeout(() => setPopups((p) => p.filter((x) => x.key !== key)), hot ? 15_000 : 8_000);
      if (document.hidden && desktopPermission() === "granted") {
        try {
          const n = new Notification(title, { body, tag: "bp-new-lead", icon: "/favicon.ico" });
          n.onclick = () => {
            window.focus();
            if (one?.lead_id) openLead(one.lead_id);
            n.close();
          };
        } catch { /* some mobile browsers only allow notifications from a service worker */ }
      }
    };

    const onNotify = (n: LeadNotification) => {
      if (n.lead_id) recentlyNotified.set(n.lead_id, Date.now());
      buffer.current.push(n);
      if (timer.current == null) timer.current = window.setTimeout(flush, 1200);
    };
    socket.on("crm:notify", onNotify);
    return () => {
      socket.off("crm:notify", onNotify);
      if (timer.current != null) window.clearTimeout(timer.current);
    };
  }, [isAuthenticated, qc]);

  if (!isAuthenticated) return null;
  const unread = data?.unread ?? 0;
  const items = data?.items ?? [];

  const openOne = (leadId: number | null, ids: number[]) => {
    if (ids.length) markRead.mutate(ids);
    if (leadId) openLead(leadId);
    setOpen(false);
  };

  return (
    <>
      <div className="relative">
        <button
          onClick={() => setOpen((o) => !o)}
          className="relative p-2 rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-card)] text-[var(--text-secondary)] hover:text-white cursor-pointer flex items-center justify-center"
          title="New lead notifications" aria-label="Notifications"
        >
          {unread > 0 ? <BellRing size={18} className="text-amber-400" /> : <Bell size={18} />}
          {unread > 0 && (
            <span className="absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] px-1 rounded-full bg-rose-500 text-white text-[10px] font-bold flex items-center justify-center">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </button>

        {open && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
            <div className="absolute right-0 mt-2 z-50 w-[min(380px,calc(100vw-2rem))] rounded-xl border border-[var(--border-subtle)] shadow-2xl overflow-hidden"
              style={{ background: "var(--bg-card)" }}>
              <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-subtle)]">
                <p className="text-sm font-semibold text-white">New leads</p>
                <div className="flex items-center gap-3 text-xs">
                  <button onClick={() => { setSoundMuted(!muted); setMuted(!muted); if (muted) playLeadChime(); }}
                    className="text-[var(--text-muted)] hover:text-white cursor-pointer" title={muted ? "Turn sound on" : "Mute sound"}>
                    {muted ? <VolumeX size={15} /> : <Volume2 size={15} />}
                  </button>
                  {unread > 0 && (
                    <button onClick={() => markRead.mutate(undefined)} className="text-blue-400 hover:underline cursor-pointer">Mark all read</button>
                  )}
                </div>
              </div>
              {perm === "default" && (
                <button onClick={async () => setPerm(await Notification.requestPermission())}
                  className="w-full text-left px-4 py-2 text-xs text-blue-400 hover:bg-[var(--bg-card-hover)] border-b border-[var(--border-subtle)] cursor-pointer">
                  Turn on desktop notifications — get alerted even when this tab is in the background
                </button>
              )}
              {perm === "denied" && (
                <p className="px-4 py-2 text-[11px] text-[var(--text-muted)] border-b border-[var(--border-subtle)]">
                  Desktop notifications are blocked for this site — allow them in the browser's site settings.
                </p>
              )}
              <div className="max-h-[60vh] overflow-y-auto divide-y divide-[var(--border-subtle)]">
                {items.length === 0 && <p className="px-4 py-6 text-center text-xs text-[var(--text-muted)]">No notifications yet</p>}
                {items.map((n) => (
                  <button key={n.id} onClick={() => openOne(n.lead_id, n.read ? [] : [n.id])}
                    className={`w-full text-left px-4 py-2.5 hover:bg-[var(--bg-card-hover)] cursor-pointer ${n.read ? "opacity-60" : ""}`}
                    style={{ boxShadow: n.read ? undefined : `inset 3px 0 0 ${n.is_hot ? "#ef4444" : KIND_COLOR[n.kind]}` }}>
                    <p className="text-xs font-semibold text-white flex items-center gap-1">
                      {n.is_hot && <Flame size={12} className="text-rose-400 shrink-0" />}{n.title}
                    </p>
                    {n.body && <p className="text-[11px] text-[var(--text-secondary)] truncate">{n.body}</p>}
                    <p className="text-[10px] text-[var(--text-muted)]">{n.created_at ? fmtRelative(n.created_at) : ""}</p>
                  </button>
                ))}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Live popups (top right) */}
      <div className="fixed top-20 right-4 z-[110] flex flex-col gap-2 w-[min(360px,calc(100vw-2rem))]">
        {popups.map((p) => (
          <div key={p.key} role="alert"
            className="rounded-xl border shadow-2xl px-4 py-3 flex items-start gap-3 cursor-pointer animate-in"
            style={{ background: "var(--bg-card)", borderColor: p.hot ? "#ef444480" : "#3b82f680" }}
            onClick={() => { openOne(p.leadId, p.ids); setPopups((x) => x.filter((y) => y.key !== p.key)); }}>
            {p.hot ? <Flame size={18} className="text-rose-400 shrink-0 mt-0.5" /> : <BellRing size={18} className="text-blue-400 shrink-0 mt-0.5" />}
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold text-white">{p.title}</p>
              {p.body && <p className="text-[11px] text-[var(--text-secondary)] line-clamp-2">{p.body}</p>}
              {p.leadId && <p className="text-[10px] text-blue-400 mt-0.5">Click to open the lead</p>}
            </div>
            <button onClick={(e) => { e.stopPropagation(); setPopups((x) => x.filter((y) => y.key !== p.key)); }}
              className="text-[var(--text-muted)] hover:text-white cursor-pointer shrink-0"><X size={14} /></button>
          </div>
        ))}
      </div>
    </>
  );
}
