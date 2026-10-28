import { useEffect, useState } from "react";
import { Search } from "lucide-react";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useFailedPayments } from "../api";
import { fmtDateTime } from "../format";
import { openLead } from "./LeadDrawer";
import { Card, Empty, Pill, Tabs, inputCls, inlineInputCls } from "./ui";

const STATUS_COLOR: Record<string, string> = { failed: "#ef4444", cancelled: "#f59e0b", abandoned: "#64748b" };

/** Leads → Failed payments: website bookings that didn't pay the ₹99 —
 * saved with the customer's details, never turned into leads. */
export function FailedPayments() {
  const [show, setShow] = useState("unpaid");
  const [days, setDays] = useState(30);
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setQ(search), 300);
    return () => clearTimeout(t);
  }, [search]);
  const { data, isLoading, error } = useFailedPayments({ days, show, q });

  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--text-muted)]">
        Website bookings whose ₹99 payment failed, was cancelled, timed out or was left unfinished. They are kept here,
        not as leads. If the customer pays later, the booking becomes a normal lead and moves to <b>Paid later</b>.
      </p>
      <div className="flex flex-col lg:flex-row lg:items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input className={`${inputCls} pl-8`} placeholder="Search name, phone, email or store" value={search}
            onChange={(e) => setSearch(e.target.value)} />
        </div>
        <select className={inlineInputCls} value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[7, 30, 90, 365].map((d) => <option key={d} value={d}>Last {d} days</option>)}
        </select>
      </div>
      <Tabs value={show} onChange={setShow} tabs={[
        { key: "unpaid", label: <>Not paid{data && <span className="ml-1 text-[11px] opacity-70">{data.counts.unpaid}</span>}</> },
        { key: "paid_later", label: <>Paid later{data && <span className="ml-1 text-[11px] opacity-70">{data.counts.paid_later}</span>}</> },
        { key: "all", label: "All" },
      ]} />
      <Card>
        {isLoading ? <TableSkeleton rows={6} /> : error ? (
          <Empty>{error instanceof Error ? error.message : "Could not load failed payments"}</Empty>
        ) : !data?.items.length ? (
          <Empty>No failed payments in the last {days} days{q ? " matching your search" : ""}.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-[var(--text-muted)] border-b border-[var(--border-subtle)]">
                  <th className="px-4 py-2.5">Customer</th>
                  <th className="px-4 py-2.5">Store / place</th>
                  <th className="px-4 py-2.5">Device · date wanted</th>
                  <th className="px-4 py-2.5">Payment</th>
                  <th className="px-4 py-2.5">When</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={r.id} className="border-b border-[var(--border-subtle)] last:border-0 align-top">
                    <td className="px-4 py-2.5">
                      <p className="font-semibold text-white">{r.name || "—"}</p>
                      <p className="text-[11px] text-[var(--text-muted)]">
                        <a href={`tel:${r.phone}`} className="hover:underline">{r.phone}</a>{r.email ? ` · ${r.email}` : ""}
                      </p>
                    </td>
                    <td className="px-4 py-2.5">
                      <p className="text-[var(--text-primary)]">{r.store || "—"}</p>
                      {r.place && <p className="text-[11px] text-[var(--text-muted)]">{r.place}</p>}
                    </td>
                    <td className="px-4 py-2.5">
                      <p className="text-[var(--text-primary)]">{r.device || "—"}</p>
                      {r.preferred_date && <p className="text-[11px] text-[var(--text-muted)]">Wants {r.preferred_date}</p>}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex flex-wrap items-center gap-1">
                        <Pill label={r.payment_status} color={STATUS_COLOR[r.payment_status.toLowerCase()] || "#ef4444"} />
                        {r.paid_lead_id && (
                          <button className="cursor-pointer" onClick={() => openLead(r.paid_lead_id!)}>
                            <Pill label="Paid later · open lead" color="#10b981" />
                          </button>
                        )}
                      </div>
                      {r.reason && <p className="text-[11px] text-[var(--text-muted)] mt-1">{r.reason}</p>}
                      {r.attempts > 1 && <p className="text-[11px] text-amber-400">{r.attempts} tries</p>}
                    </td>
                    <td className="px-4 py-2.5 whitespace-nowrap text-[var(--text-secondary)]">
                      {fmtDateTime(r.at)}
                      {r.entry_id && <p className="text-[11px] text-[var(--text-muted)]">{r.entry_id}</p>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
