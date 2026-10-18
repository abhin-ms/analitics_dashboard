/** The call a telecaller is on from the mobile view. Kept in localStorage:
 * tapping Call hands the number to the phone's dialer, and the browser tab
 * may be suspended or even reloaded while they talk — the timer is worked
 * out from startedAt, so it is still right when they come back. */
import { useEffect, useState } from "react";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export interface CallTarget {
  leadId: number;
  name: string;
  phone: string;
  status: string;
  source?: string;
  note?: string;
}

export interface ActiveCall extends CallTarget {
  startedAt: number;
  /** Set by "End call"; null while the call is running. */
  endedAt: number | null;
  /** Started by the auto-dial countdown rather than a tap. */
  auto?: boolean;
}

interface ActiveCallState {
  call: ActiveCall | null;
  /** Auto-dial: count down and call the next lead. Off until turned on. */
  autoDial: boolean;
  setAutoDial: (on: boolean) => void;
  start: (t: CallTarget, auto?: boolean) => void;
  end: () => void;
  resume: () => void;
  clear: () => void;
}

// A call left open longer than this (app closed mid-call, forgotten) is
// dropped instead of reopening with an absurd duration.
const STALE_MS = 6 * 60 * 60 * 1000;

const safeStorage = createJSONStorage(() => ({
  getItem: (k: string) => { try { return localStorage.getItem(k); } catch { return null; } },
  setItem: (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  removeItem: (k: string) => { try { localStorage.removeItem(k); } catch { /* private mode */ } },
}));

export const useActiveCall = create<ActiveCallState>()(
  persist(
    (set) => ({
      call: null,
      autoDial: false,
      setAutoDial: (on) => set({ autoDial: on }),
      start: (t, auto) => set({ call: { ...t, startedAt: Date.now(), endedAt: null, auto } }),
      end: () => set((s) => (s.call && !s.call.endedAt ? { call: { ...s.call, endedAt: Date.now() } } : s)),
      resume: () => set((s) => (s.call ? { call: { ...s.call, endedAt: null } } : s)),
      clear: () => set({ call: null }),
    }),
    {
      name: "bp.active-call",
      storage: safeStorage,
      onRehydrateStorage: () => (state) => {
        if (state?.call && Date.now() - state.call.startedAt > STALE_MS) state.clear();
      },
    },
  ),
);

export function callSeconds(call: ActiveCall, now = Date.now()): number {
  return Math.max(0, Math.round(((call.endedAt ?? now) - call.startedAt) / 1000));
}

export function mmss(total: number): string {
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/** Re-renders every second while `running`, and at once when the tab comes
 * back into view (timers are paused while the dialer is in front). */
export function useNow(running: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const tick = () => setNow(Date.now());
    const id = window.setInterval(tick, 1000);
    document.addEventListener("visibilitychange", tick);
    return () => {
      window.clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [running]);
  return now;
}
