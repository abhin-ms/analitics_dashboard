import { useState, ReactNode } from "react";
import { cn } from "@/lib/utils";
import { formatMoney, formatNumber, formatPct } from "@/lib/formatMoney";
import { TrendingUp, TrendingDown } from "lucide-react";
import {
  CardFilterPopover,
  CardFilterState,
  DEFAULT_CARD_FILTER,
} from "@/components/shared/CardFilterPopover";

interface StatCardProps {
  title: string;
  value: number;
  delta?: number;
  currency?: string;
  type?: "money" | "number" | "percent";
  icon: ReactNode;
  color: string;
  sparkline?: number[];
  className?: string;
  enableFilter?: boolean;
  entityLabel?: string;
  entityOptions?: string[];
  onFilterChange?: (filter: CardFilterState) => void;
  badge?: string | null;
}

export function StatCard({
  title,
  value,
  delta,
  currency = "INR",
  type = "money",
  icon,
  color,
  sparkline,
  className,
  enableFilter = false,
  entityLabel = "Entity",
  entityOptions = [],
  onFilterChange,
  badge,
}: StatCardProps) {
  const [filter, setFilter] = useState<CardFilterState>(DEFAULT_CARD_FILTER);

  const handleFilterChange = (newFilter: CardFilterState) => {
    setFilter(newFilter);
    if (onFilterChange) onFilterChange(newFilter);
  };
  const renderFormattedValue = () => {
    if (type === "percent") return formatPct(value);
    if (type === "number") return formatNumber(value);
    return formatMoney(value, currency);
  };

  return (
    <div
      className={cn(
        "rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5",
        "hover:border-[var(--border-strong)] hover:shadow-[var(--card-shadow-hover)] transition-all duration-200 flex flex-col justify-between group",
        className
      )}
    >
      <div>
        <div className="flex items-center justify-between mb-3">
          <div
            className="flex h-11 w-11 items-center justify-center rounded-xl transition-transform group-hover:scale-105"
            style={{ backgroundColor: `${color}1f`, color }}
          >
            {icon}
          </div>

          <div className="flex items-center gap-2">
            {delta !== undefined && (
              <span
                className={cn(
                  "flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full border",
                  delta >= 0
                    ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
                    : "text-rose-400 bg-rose-500/10 border-rose-500/20"
                )}
              >
                {delta >= 0 ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
                {delta >= 0 ? "+" : ""}
                {formatPct(delta)}
              </span>
            )}

            {enableFilter && (
              <CardFilterPopover
                filter={filter}
                onFilterChange={handleFilterChange}
                entityLabel={entityLabel}
                entityOptions={entityOptions}
              />
            )}
          </div>
        </div>

        <p className="text-xs font-medium text-[var(--text-secondary)] mb-1">
          {title}
        </p>
        <p className="text-2xl font-bold tracking-tight text-[var(--text-primary)] tabular-nums">
          {renderFormattedValue()}
        </p>
        {badge && (
          <span className="inline-flex items-center gap-1.5 mt-2 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/25">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            {badge}
          </span>
        )}
      </div>

      {sparkline && sparkline.length > 0 && (
        <div className="mt-4 h-8 flex items-end gap-1 pt-2">
          {sparkline.slice(-7).map((v, i) => {
            const max = Math.max(...sparkline.slice(-7), 1);
            const h = (v / max) * 100;
            return (
              <div
                key={i}
                className="flex-1 rounded-xs transition-all duration-300 group-hover:opacity-100"
                style={{
                  height: `${Math.max(h, 8)}%`,
                  backgroundColor: color,
                  opacity: 0.6 + i * 0.05,
                }}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
