/** Small UI building blocks for the CRM pages, styled with the app's
 * existing theme tokens (var(--bg-card), var(--border-subtle), …) so they
 * follow dark/light mode like every other page. */
import { ReactNode, useEffect } from "react";
import { X, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { priorityMeta, stageMeta, statusColor, NO_STATUS } from "../statusConfig";

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)]", className)}>
      {children}
    </div>
  );
}

export function CardHeader({ title, icon, action, subtitle }: {
  title: ReactNode; icon?: ReactNode; action?: ReactNode; subtitle?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-[var(--border-subtle)]">
      <div className="min-w-0">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">{icon}{title}</h3>
        {subtitle && <p className="text-[11px] text-[var(--text-muted)] mt-0.5">{subtitle}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-bold text-white tracking-tight">{title}</h1>
        {subtitle && <p className="text-xs text-[var(--text-muted)] mt-0.5">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Button({ children, onClick, variant = "secondary", size = "md", disabled, loading, type = "button", className, title }: {
  children: ReactNode; onClick?: () => void; variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md"; disabled?: boolean; loading?: boolean; type?: "button" | "submit"; className?: string; title?: string;
}) {
  const base = "inline-flex items-center justify-center gap-1.5 rounded-xl font-medium transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap";
  const sizes = { sm: "px-2.5 py-1.5 text-xs", md: "px-3.5 py-2 text-sm" };
  const variants = {
    primary: "bg-blue-600 hover:bg-blue-500 text-white border border-blue-500/50",
    secondary: "border border-[var(--border-subtle)] bg-[var(--bg-card)] hover:bg-[var(--bg-card-hover)] text-[var(--text-primary)]",
    ghost: "text-blue-400 hover:bg-blue-500/10",
    danger: "border border-rose-500/30 text-rose-400 hover:bg-rose-500/10",
  };
  return (
    <button type={type} title={title} onClick={onClick} disabled={disabled || loading}
      className={cn(base, sizes[size], variants[variant], className)}>
      {loading && <Loader2 size={14} className="animate-spin" />}
      {children}
    </button>
  );
}

export function Pill({ label, color, className }: { label: ReactNode; color: string; className?: string }) {
  return (
    <span
      className={cn("inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold whitespace-nowrap", className)}
      style={{ backgroundColor: `${color}18`, color, border: `1px solid ${color}35` }}
    >
      {label}
    </span>
  );
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const label = status || NO_STATUS;
  return <Pill label={label} color={statusColor(label)} />;
}

export function StageBadge({ stage }: { stage: string | null | undefined }) {
  const m = stageMeta(stage);
  return <Pill label={m.label} color={m.color} />;
}

export function PriorityBadge({ priority }: { priority: string | null | undefined }) {
  const m = priorityMeta(priority);
  return <Pill label={m.label} color={m.color} />;
}

export function Tile({ label, value, hint, color, onClick, active }: {
  label: string; value: ReactNode; hint?: ReactNode; color?: string; onClick?: () => void; active?: boolean;
}) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag
      onClick={onClick}
      className={cn(
        "text-left rounded-2xl border bg-[var(--bg-card)] p-4 transition-colors",
        active ? "border-blue-500/50 bg-blue-500/5" : "border-[var(--border-subtle)]",
        onClick && "hover:bg-[var(--bg-card-hover)] cursor-pointer",
      )}
    >
      <p className="text-[11px] text-[var(--text-muted)] font-medium">{label}</p>
      <p className="text-2xl font-bold mt-1" style={{ color: color || "var(--text-primary)" }}>{value}</p>
      {hint && <p className="text-[11px] text-[var(--text-muted)] mt-1">{hint}</p>}
    </Tag>
  );
}

export function Modal({ open, onClose, title, children, footer, wide }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[70] flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-[2px] p-0 sm:p-4"
      onClick={onClose}>
      <div
        role="dialog"
        className={cn(
          "w-full rounded-t-2xl sm:rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] shadow-2xl max-h-[92vh] flex flex-col",
          wide ? "sm:max-w-2xl" : "sm:max-w-md",
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border-subtle)]">
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          <button onClick={onClose} className="text-[var(--text-muted)] hover:text-white cursor-pointer"><X size={18} /></button>
        </div>
        <div className="px-5 py-4 overflow-y-auto">{children}</div>
        {footer && <div className="px-5 py-3 border-t border-[var(--border-subtle)] flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  );
}

const inputBase =
  "rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-primary)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)]";
export const inputCls = `w-full ${inputBase}`;
/** For selects/inputs that sit inline in a toolbar (natural width). */
export const inlineInputCls = `w-auto ${inputBase}`;

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[11px] font-medium text-[var(--text-secondary)] mb-1">{label}</span>
      {children}
      {hint && <span className="block text-[10px] text-[var(--text-muted)] mt-1">{hint}</span>}
    </label>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-5 py-10 text-center text-sm text-[var(--text-muted)]">{children}</div>;
}

export function Tabs({ tabs, value, onChange }: {
  tabs: { key: string; label: ReactNode }[]; value: string; onChange: (key: string) => void;
}) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-[var(--border-subtle)]">
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={cn(
            "px-3 py-2 text-sm whitespace-nowrap border-b-2 -mb-px cursor-pointer transition-colors",
            value === t.key
              ? "border-blue-500 text-blue-400 font-semibold"
              : "border-transparent text-[var(--text-secondary)] hover:text-white",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Avatar({ name, color = "#3b82f6" }: { name: string; color?: string }) {
  const text = name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]!.toUpperCase()).join("") || "?";
  return (
    <span className="shrink-0 w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold"
      style={{ backgroundColor: `${color}1f`, color }}>
      {text}
    </span>
  );
}

export function InfoNote({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-blue-500/20 bg-blue-500/5 px-4 py-3 text-xs text-[var(--text-secondary)]">
      {children}
    </div>
  );
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="text-xs text-rose-400">{error instanceof Error ? error.message : String(error)}</p>;
}
