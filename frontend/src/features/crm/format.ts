/** Formatting helpers for the CRM pages. All times shown in IST. */

const IST = "Asia/Kolkata";

export function fmtDateTime(iso: string | null | undefined, opts?: { withYear?: boolean }): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-IN", {
    timeZone: IST,
    day: "numeric",
    month: "short",
    ...(opts?.withYear ? { year: "numeric" } : {}),
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("en-IN", { timeZone: IST, hour: "2-digit", minute: "2-digit", hour12: false });
}

export function istDateKey(d: Date): string {
  // YYYY-MM-DD of the IST calendar day
  return d.toLocaleDateString("en-CA", { timeZone: IST });
}

export function todayIST(): string {
  return istDateKey(new Date());
}

export function addDaysKey(key: string, days: number): string {
  const [y, m, d] = key.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  return dt.toISOString().slice(0, 10);
}

export function fmtDayLabel(key: string): string {
  const [y, m, d] = key.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  const today = todayIST();
  const label = dt.toLocaleDateString("en-IN", { timeZone: "UTC", weekday: "long", day: "numeric", month: "short" });
  if (key === today) return `Today · ${dt.toLocaleDateString("en-IN", { timeZone: "UTC", day: "numeric", month: "short" })}`;
  return label;
}

/** "Overdue · 14:00", "Today · 11:30", "25 Sep · 10:00" */
export function fmtDue(iso: string | null | undefined): { text: string; overdue: boolean; today: boolean } {
  if (!iso) return { text: "Not scheduled", overdue: false, today: false };
  const d = new Date(iso);
  const overdue = d.getTime() < Date.now();
  const today = istDateKey(d) === todayIST();
  const time = fmtTime(iso);
  if (overdue) return { text: today ? `Overdue · ${time}` : `Overdue · ${fmtDateTime(iso)}`, overdue, today };
  if (today) return { text: `Today · ${time}`, overdue, today };
  return { text: fmtDateTime(iso), overdue, today };
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diff / 60000);
  if (Math.abs(mins) < 1) return "just now";
  if (mins > 0 && mins < 60) return `${mins} min ago`;
  if (mins < 0 && mins > -60) return `in ${-mins} min`;
  const hrs = Math.round(mins / 60);
  if (hrs > 0 && hrs < 24) return `${hrs} h ago`;
  if (hrs < 0 && hrs > -24) return `in ${-hrs} h`;
  return fmtDateTime(iso);
}

export function fmtINR(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
}

export function fmtINRShort(n: number): string {
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(1)}Cr`;
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`;
  if (n >= 1000) return `₹${(n / 1000).toFixed(1)}K`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
}

export function pct(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : `${n}%`;
}

export function initials(name: string | null | undefined): string {
  if (!name) return "?";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
}

/** datetime-local input value (IST wall clock) -> ISO with +05:30 offset */
export function localInputToISO(value: string): string {
  return value ? `${value}:00+05:30` : "";
}

/** ISO -> datetime-local input value in IST */
export function isoToLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  const date = istDateKey(d);
  const time = d.toLocaleTimeString("en-GB", { timeZone: IST, hour: "2-digit", minute: "2-digit", hour12: false });
  return `${date}T${time}`;
}

/** Default datetime-local value: now + N minutes, IST */
export function defaultLocalInput(minutesFromNow = 60): string {
  return isoToLocalInput(new Date(Date.now() + minutesFromNow * 60000).toISOString());
}
