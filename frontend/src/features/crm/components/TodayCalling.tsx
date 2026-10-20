/** Admin / team leader: today's calling at a glance — who is calling, how
 * many calls, first calls on time, talk time, and the late first calls. */
import { AlertTriangle, PhoneCall } from "lucide-react";
import { cn } from "@/lib/utils";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useTodayCalling, type TodayCallingAgent } from "../api";
import { fmtTime } from "../format";
import { openLead } from "./LeadDrawer";
import { Card, CardHeader, Empty } from "./ui";

function talk(secs: number) {
  if (!secs) return "—";
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return h ? `${h}h ${m}m` : m ? `${m}m ${secs % 60}s` : `${secs}s`;
}

const pct = (a: number, b: number) => (b ? Math.round((a / b) * 100) : null);

function minutesAgo(iso: string) {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : `${fmtTime(iso)}`;
}

function CallingStatus({ a }: { a: TodayCallingAgent }) {
  if (!a.last_call_at) return <span className="text-amber-500 font-medium">No calls yet</span>;
  const idleMin = (Date.now() - new Date(a.last_call_at).getTime()) / 60000;
  return (
    <span className={idleMin <= 30 ? "text-emerald-500" : "text-[var(--text-secondary)]"}>
      {idleMin <= 30 ? "Calling · " : "Last call "}{minutesAgo(a.last_call_at)}
    </span>
  );
}

function FirstCalls({ a, target }: { a: Pick<TodayCallingAgent, "first_calls_on_time" | "first_calls_total">; target: number }) {
  if (!a.first_calls_total) return <span className="text-[var(--text-muted)]">—</span>;
  const p = pct(a.first_calls_on_time, a.first_calls_total)!;
  return (
    <span className={p >= 90 ? "text-emerald-500" : p >= 70 ? "text-amber-500" : "text-rose-500"} title={`within ${target} working minutes`}>
      {a.first_calls_on_time} of {a.first_calls_total}
    </span>
  );
}

export function TodayCalling() {
  const { data, isLoading } = useTodayCalling();
  if (isLoading || !data) return <Card><div className="p-5"><TableSkeleton /></div></Card>;
  const s = data.summary;
  const target = data.first_call_minutes;
  const connectedPct = pct(s.connected, s.calls);
  const onTimePct = pct(s.first_calls_on_time, s.first_calls_total);

  const tiles: [string, string, string?, boolean?][] = [
    ["Calls today", String(s.calls), `${s.calling} of ${s.telecallers} telecallers calling`],
    ["Connected", connectedPct == null ? "—" : `${connectedPct}%`, `${s.connected} calls`],
    [`First calls in ${target} min`, s.first_calls_total ? `${s.first_calls_on_time}/${s.first_calls_total}` : "—",
      onTimePct == null ? "no new leads due yet" : `${onTimePct}% on time`, onTimePct != null && onTimePct < 90],
    ["Talk time", talk(s.talk_seconds), "timed on the mobile app"],
    ["Late first calls", String(s.late), s.waiting ? `${s.waiting} still waiting` : "none waiting", s.late > 0],
  ];

  return (
    <Card>
      <CardHeader title="Today's calling" icon={<PhoneCall size={15} className="text-blue-400" />}
        subtitle={`Every telecaller's calls today · first call target ${target} working minutes (Telecalling Automation)`} />
      <div className="px-5 pt-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {tiles.map(([label, value, hint, bad]) => (
          <div key={label} className="rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-subtle)] px-3 py-2.5">
            <p className="text-[11px] text-[var(--text-muted)]">{label}</p>
            <p className={cn("text-xl font-bold tabular-nums", bad ? "text-rose-500" : "text-[var(--text-primary)]")}>{value}</p>
            {hint && <p className="text-[10.5px] text-[var(--text-muted)]">{hint}</p>}
          </div>
        ))}
      </div>

      {data.agents.length === 0 ? <Empty>No telecallers yet.</Empty> : (
        <>
          {/* phones: one card per telecaller */}
          <div className="md:hidden mt-3 divide-y divide-[var(--border-subtle)] border-t border-[var(--border-subtle)]">
            {data.agents.map((a) => (
              <div key={a.user_id} className="px-5 py-3 text-xs space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-sm text-[var(--text-primary)]">{a.name}{!a.available && <span className="ml-1.5 text-[10px] text-amber-500">Away</span>}</span>
                  <span className="text-sm font-bold tabular-nums text-[var(--text-primary)]">{a.calls} calls</span>
                </div>
                <p><CallingStatus a={a} /></p>
                <p className="text-[var(--text-secondary)]">
                  {a.connected} connected · first calls <FirstCalls a={a} target={target} /> · talk {talk(a.talk_seconds)}
                </p>
              </div>
            ))}
          </div>
          <div className="hidden md:block mt-3 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-[var(--text-muted)] border-y border-[var(--border-subtle)]">
                  {["Telecaller", "Status", "Calls", "Connected", `First calls in ${target} min`, "Avg first call", "Talk time"].map((h, i) => (
                    <th key={h} className={cn("py-2.5 px-4 font-semibold whitespace-nowrap", i < 2 ? "text-left" : "text-right")}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border-subtle)]">
                {data.agents.map((a) => (
                  <tr key={a.user_id} className="hover:bg-[var(--bg-card-hover)]">
                    <td className="py-2.5 px-4 font-medium text-[var(--text-primary)] whitespace-nowrap">
                      {a.name}{!a.available && <span className="ml-1.5 text-[10px] font-semibold text-amber-500">Away</span>}
                    </td>
                    <td className="py-2.5 px-4 whitespace-nowrap"><CallingStatus a={a} /></td>
                    <td className="py-2.5 px-4 text-right font-bold tabular-nums text-[var(--text-primary)]">{a.calls}</td>
                    <td className="py-2.5 px-4 text-right tabular-nums text-[var(--text-secondary)]">
                      {a.connected}{a.calls ? <span className="text-[var(--text-muted)]"> · {pct(a.connected, a.calls)}%</span> : null}
                    </td>
                    <td className="py-2.5 px-4 text-right tabular-nums"><FirstCalls a={a} target={target} /></td>
                    <td className="py-2.5 px-4 text-right tabular-nums text-[var(--text-secondary)]">
                      {a.avg_first_call_minutes != null ? `${a.avg_first_call_minutes} min` : "—"}
                    </td>
                    <td className="py-2.5 px-4 text-right tabular-nums text-[var(--text-secondary)]">{talk(a.talk_seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {data.late.length > 0 && (
        <div className="border-t border-[var(--border-subtle)]">
          <p className="px-5 pt-3 pb-1 flex items-center gap-1.5 text-xs font-semibold text-rose-500">
            <AlertTriangle size={13} />Late first calls today ({data.late.length})
          </p>
          <div className="divide-y divide-[var(--border-subtle)]">
            {data.late.map((l) => (
              <button key={`${l.lead_id}-${l.due_at}`} onClick={() => openLead(l.lead_id)}
                className="w-full text-left px-5 py-2.5 flex flex-col sm:flex-row sm:items-center gap-0.5 sm:gap-3 text-xs hover:bg-[var(--bg-card-hover)] cursor-pointer">
                <span className="sm:w-44 font-medium text-[var(--text-primary)] truncate">{l.lead_name}</span>
                <span className="sm:w-32 text-[var(--text-secondary)] truncate">{l.owner || "Unassigned"}</span>
                <span className="flex-1 text-[var(--text-secondary)]">
                  Arrived {fmtTime(l.received_at)} · {l.still_waiting
                    ? <span className="text-rose-500 font-semibold">not called yet</span>
                    : <>called {fmtTime(l.called_at)} ({l.minutes_to_call} min)</>}
                </span>
                <span className="font-semibold text-rose-500 whitespace-nowrap">{l.late_by_minutes} min late</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}
