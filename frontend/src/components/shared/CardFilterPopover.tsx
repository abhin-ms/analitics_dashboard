import { useState, useRef, useEffect } from "react";
import { MoreVertical, Filter, Calendar, X, Check, RotateCcw } from "lucide-react";

export interface CardFilterState {
  dateMode: "all" | "3day" | "7day" | "30day" | "single" | "range" | "month";
  singleDate?: string;
  startDate?: string;
  endDate?: string;
  monthYear?: string;
  selectedEntity?: string;
}

export const DEFAULT_CARD_FILTER: CardFilterState = {
  dateMode: "all",
  selectedEntity: "all",
};

interface CardFilterPopoverProps {
  filter: CardFilterState;
  onFilterChange: (newFilter: CardFilterState) => void;
  entityLabel?: string;
  entityOptions?: string[];
}

export function CardFilterPopover({
  filter,
  onFilterChange,
  entityLabel = "Entity",
  entityOptions = [],
}: CardFilterPopoverProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [localFilter, setLocalFilter] = useState<CardFilterState>(filter);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLocalFilter(filter);
  }, [filter]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen]);

  const handleApply = () => {
    onFilterChange(localFilter);
    setIsOpen(false);
  };

  const handleReset = () => {
    const resetFilter: CardFilterState = { dateMode: "all", selectedEntity: "all" };
    setLocalFilter(resetFilter);
    onFilterChange(resetFilter);
    setIsOpen(false);
  };

  const isFiltered =
    localFilter.dateMode !== "all" || (localFilter.selectedEntity && localFilter.selectedEntity !== "all");

  return (
    <div className="relative inline-block text-left" ref={popoverRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={`p-1.5 rounded-lg transition-colors border ${
          isFiltered
            ? "bg-blue-500/20 border-blue-500/40 text-blue-400"
            : "bg-white/5 border-white/10 text-zinc-400 hover:text-white hover:bg-white/10"
        }`}
        title="Filter options"
      >
        <MoreVertical size={16} />
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-72 rounded-xl bg-[var(--bg-card)] border border-[var(--border-subtle)] shadow-2xl p-4 z-50 text-xs space-y-3 animate-in fade-in zoom-in-95 duration-150">
          <div className="flex items-center justify-between border-b border-white/10 pb-2">
            <div className="flex items-center gap-1.5 font-bold text-white">
              <Filter size={14} className="text-blue-400" />
              <span>Card Filter Options</span>
            </div>
            <button
              onClick={() => setIsOpen(false)}
              className="text-zinc-400 hover:text-white p-1 rounded hover:bg-white/5"
            >
              <X size={14} />
            </button>
          </div>

          {/* Date Filter Section */}
          <div className="space-y-2">
            <label className="font-semibold text-zinc-300 flex items-center gap-1">
              <Calendar size={13} className="text-purple-400" />
              <span>Date Filter</span>
            </label>
            <div className="grid grid-cols-2 gap-1.5">
              {[
                { id: "all", label: "All Dates" },
                { id: "3day", label: "Last 3 Days ⚡" },
                { id: "7day", label: "Last 7 Days" },
                { id: "30day", label: "Last 30 Days" },
                { id: "single", label: "Single Date" },
                { id: "range", label: "Date Range" },
                { id: "month", label: "Month/Year" },
              ].map((m) => (
                <button
                  key={m.id}
                  onClick={() =>
                    setLocalFilter({
                      ...localFilter,
                      dateMode: m.id as CardFilterState["dateMode"],
                    })
                  }
                  className={`px-2.5 py-1.5 rounded-lg border text-left font-medium transition-all ${
                    localFilter.dateMode === m.id
                      ? "bg-blue-600 text-white border-blue-500"
                      : "bg-white/5 border-white/10 text-zinc-300 hover:bg-white/10"
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>

            {/* Sub-inputs depending on date mode */}
            {localFilter.dateMode === "single" && (
              <div className="pt-1">
                <input
                  type="date"
                  value={localFilter.singleDate || ""}
                  onChange={(e) =>
                    setLocalFilter({ ...localFilter, singleDate: e.target.value })
                  }
                  className="w-full bg-[var(--bg-primary)] border border-white/10 rounded-lg px-2.5 py-1.5 text-white font-mono text-xs focus:outline-none focus:border-blue-500"
                />
              </div>
            )}

            {localFilter.dateMode === "range" && (
              <div className="grid grid-cols-2 gap-2 pt-1">
                <div>
                  <span className="text-[10px] text-zinc-400 block mb-0.5">Start Date</span>
                  <input
                    type="date"
                    value={localFilter.startDate || ""}
                    onChange={(e) =>
                      setLocalFilter({ ...localFilter, startDate: e.target.value })
                    }
                    className="w-full bg-[var(--bg-primary)] border border-white/10 rounded-lg px-2 py-1 text-white font-mono text-[11px] focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <span className="text-[10px] text-zinc-400 block mb-0.5">End Date</span>
                  <input
                    type="date"
                    value={localFilter.endDate || ""}
                    onChange={(e) =>
                      setLocalFilter({ ...localFilter, endDate: e.target.value })
                    }
                    className="w-full bg-[var(--bg-primary)] border border-white/10 rounded-lg px-2 py-1 text-white font-mono text-[11px] focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>
            )}

            {localFilter.dateMode === "month" && (
              <div className="pt-1">
                <input
                  type="month"
                  value={localFilter.monthYear || ""}
                  onChange={(e) =>
                    setLocalFilter({ ...localFilter, monthYear: e.target.value })
                  }
                  className="w-full bg-[var(--bg-primary)] border border-white/10 rounded-lg px-2.5 py-1.5 text-white font-mono text-xs focus:outline-none focus:border-blue-500"
                />
              </div>
            )}
          </div>

          {/* Entity Filter (Store / Person / Category) */}
          {entityOptions.length > 0 && (
            <div className="space-y-1.5 pt-1 border-t border-white/10">
              <label className="font-semibold text-zinc-300 block">{entityLabel} Filter</label>
              <select
                value={localFilter.selectedEntity || "all"}
                onChange={(e) =>
                  setLocalFilter({ ...localFilter, selectedEntity: e.target.value })
                }
                className="w-full bg-[var(--bg-primary)] border border-white/10 rounded-lg px-2.5 py-1.5 text-white text-xs focus:outline-none focus:border-blue-500"
              >
                <option value="all">All {entityLabel}s</option>
                {entityOptions.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Action buttons */}
          <div className="flex items-center justify-between pt-2 border-t border-white/10">
            <button
              onClick={handleReset}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-zinc-400 hover:text-white transition-colors"
            >
              <RotateCcw size={12} />
              <span>Reset</span>
            </button>
            <button
              onClick={handleApply}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold shadow-md transition-colors"
            >
              <Check size={13} />
              <span>Apply Filter</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Helper function to filter dataset based on CardFilterState */
export function applyCardFilter<T extends Record<string, any>>(
  data: T[],
  filter: CardFilterState,
  dateFieldKeys: string[] = ["date", "created_at", "day"],
  entityFieldKeys: string[] = ["name", "store", "tl", "person", "category"]
): T[] {
  if (!data || !Array.isArray(data) || data.length === 0) return data;

  let result = [...data];

  // 1. Entity Filter
  if (filter.selectedEntity && filter.selectedEntity !== "all") {
    result = result.filter((row) => {
      return entityFieldKeys.some((key) => {
        const val = row[key];
        if (typeof val === "string") {
          return val.toLowerCase().includes(filter.selectedEntity!.toLowerCase());
        }
        return false;
      });
    });
  }

  // 2. Date Filter
  if (filter.dateMode !== "all") {
    const today = new Date();

    result = result.filter((row) => {
      // Find row date string
      let dateVal: string | null = null;
      for (const key of dateFieldKeys) {
        if (row[key]) {
          dateVal = String(row[key]);
          break;
        }
      }
      if (!dateVal) return true; // If no date field, keep row

      // Parse row date
      const rowDate = new Date(dateVal);
      if (isNaN(rowDate.getTime())) return true;

      if (filter.dateMode === "3day") {
        const cutoff = new Date();
        cutoff.setDate(today.getDate() - 3);
        cutoff.setHours(0, 0, 0, 0);
        return rowDate >= cutoff;
      }

      if (filter.dateMode === "7day") {
        const cutoff = new Date();
        cutoff.setDate(today.getDate() - 7);
        cutoff.setHours(0, 0, 0, 0);
        return rowDate >= cutoff;
      }

      if (filter.dateMode === "30day") {
        const cutoff = new Date();
        cutoff.setDate(today.getDate() - 30);
        cutoff.setHours(0, 0, 0, 0);
        return rowDate >= cutoff;
      }

      if (filter.dateMode === "single" && filter.singleDate) {
        return dateVal.startsWith(filter.singleDate);
      }

      if (filter.dateMode === "range") {
        if (filter.startDate) {
          const start = new Date(filter.startDate);
          start.setHours(0, 0, 0, 0);
          if (rowDate < start) return false;
        }
        if (filter.endDate) {
          const end = new Date(filter.endDate);
          end.setHours(23, 59, 59, 999);
          if (rowDate > end) return false;
        }
        return true;
      }

      if (filter.dateMode === "month" && filter.monthYear) {
        return dateVal.startsWith(filter.monthYear);
      }

      return true;
    });
  }

  return result;
}
