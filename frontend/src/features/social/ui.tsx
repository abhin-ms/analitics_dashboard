import { ReactNode } from "react";
import { STATUS_COLOR, STATUS_ICON, STATUS_LABEL, Status } from "./socialData";

export function Card({ title, subtitle, right, children, className = "" }: {
  title?: string; subtitle?: string; right?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <div className={`rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 min-w-0 ${className}`}>
      {(title || right) && (
        <div className="flex items-start justify-between gap-3 mb-4">
          <div className="min-w-0">
            {title && <h3 className="text-base font-bold text-white tracking-tight">{title}</h3>}
            {subtitle && <p className="text-xs text-[var(--text-muted)] mt-0.5">{subtitle}</p>}
          </div>
          {right}
        </div>
      )}
      {children}
    </div>
  );
}

/** Hover card shown above its trigger — the per-mark tooltip for the bars. */
export function Tip({ content, children, className = "", style }: {
  content: ReactNode; children: ReactNode; className?: string; style?: React.CSSProperties;
}) {
  return (
    <div className={`group relative ${className}`} style={style}>
      {children}
      <div className="pointer-events-none absolute left-1/2 bottom-full z-20 mb-1.5 hidden -translate-x-1/2 whitespace-nowrap rounded-lg border border-[var(--border-subtle)] bg-[var(--bg-card)] px-2.5 py-1.5 text-[11px] text-[var(--text-secondary)] shadow-xl group-hover:block">
        {content}
      </div>
    </div>
  );
}

export function StatusPill({ status, label }: { status: Status; label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border-subtle)] px-2 py-0.5 text-[11px] font-semibold text-white whitespace-nowrap">
      <i className="inline-block h-2 w-2 rounded-full" style={{ background: STATUS_COLOR[status] }} />
      {STATUS_ICON[status]} {label ?? STATUS_LABEL[status]}
    </span>
  );
}

export function StatusLegend({ items }: { items: [Status, string][] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3 text-[11px] text-[var(--text-secondary)]">
      {items.map(([s, l]) => (
        <span key={s + l} className="inline-flex items-center gap-1.5">
          <i className="inline-block h-2.5 w-2.5 rounded-[3px]" style={{ background: STATUS_COLOR[s] }} />
          {s === "none" ? l : `${STATUS_ICON[s]} ${l}`}
        </span>
      ))}
    </div>
  );
}

/** One labelled horizontal bar: name · track · value. `pct` is 0–100 of the track. */
export function BarRow({ label, pct, color, value, tip, refPct }: {
  label: string; pct: number; color: string; value: ReactNode; tip: ReactNode; refPct?: number;
}) {
  return (
    <Tip content={tip}>
      <div className="grid grid-cols-[minmax(90px,140px)_1fr_56px] items-center gap-2 rounded-md px-1 py-[3px] text-xs hover:bg-[var(--bg-card-hover)]">
        <span className="min-w-0 truncate text-[var(--text-secondary)]" title={label}>{label}</span>
        <span className="relative h-3.5">
          <b
            className="absolute inset-y-0 left-0 rounded-r"
            style={{ width: `${Math.max(0, Math.min(100, pct))}%`, background: color }}
          />
          {refPct !== undefined && (
            <span className="absolute -inset-y-1 border-l border-dashed border-[var(--text-secondary)]" style={{ left: `${refPct}%` }} />
          )}
        </span>
        <span className="text-right tabular-nums text-white">{value}</span>
      </div>
    </Tip>
  );
}

/** Store count per status as one segmented bar, with counts beneath. */
export function StatusBar({ counts }: { counts: Record<Status, number> }) {
  const order: Status[] = ["good", "warn", "crit", "none"];
  const present = order.filter((s) => counts[s] > 0);
  return (
    <div>
      <div className="flex h-3 w-full gap-[2px] rounded-md">
        {present.map((s, i) => (
          <Tip key={s} className="h-full" style={{ flex: `${counts[s]} 0 0` }} content={`${STATUS_LABEL[s]}: ${counts[s]} store${counts[s] === 1 ? "" : "s"}`}>
            <div
              className={`h-full w-full ${i === 0 ? "rounded-l-md" : ""} ${i === present.length - 1 ? "rounded-r-md" : ""}`}
              style={{ background: STATUS_COLOR[s] }}
            />
          </Tip>
        ))}
      </div>
      <div className="mt-2 grid grid-cols-4 gap-2">
        {order.map((s) => (
          <div key={s}>
            <div className="text-lg font-extrabold text-white leading-tight">{counts[s]}</div>
            <div className="flex items-center gap-1 text-[11px] text-[var(--text-muted)]">
              <i className="inline-block h-2 w-2 rounded-full" style={{ background: STATUS_COLOR[s] }} />
              {STATUS_LABEL[s]}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
