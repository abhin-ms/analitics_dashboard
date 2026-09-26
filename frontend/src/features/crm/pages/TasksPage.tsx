import { useState } from "react";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useCrmMeta, useFollowups } from "../api";
import { EmptyFollowups, FollowupRow } from "../components/shared";
import { Card, CardHeader, InfoNote, PageHeader, inputCls, inlineInputCls } from "../components/ui";

export default function TasksPage() {
  const { data: meta } = useCrmMeta();
  const isAgent = meta?.role === "Telecaller" || meta?.role === "Salesperson";
  const [mine, setMine] = useState<boolean | undefined>(undefined);
  const [owner, setOwner] = useState("");
  const { data, isLoading, error } = useFollowups(owner ? false : mine, owner);

  const section = (title: string, list: NonNullable<typeof data>["overdue"] | undefined, empty: string, danger?: boolean) => (
    <Card>
      <CardHeader title={title} action={list && list.length > 0 && (
        <span className={`text-[11px] px-2 py-0.5 rounded-lg font-semibold ${danger ? "bg-rose-500/10 text-rose-400" : "bg-blue-500/10 text-blue-400"}`}>{list.length}</span>
      )} />
      {!list || list.length === 0 ? <EmptyFollowups text={empty} /> : (
        <div className="divide-y divide-[var(--border-subtle)]">
          {list.map((f) => <FollowupRow key={f.id} f={f} showOwner={!data?.mine} />)}
        </div>
      )}
    </Card>
  );

  return (
    <ErrorBoundary>
      <div className="space-y-4 p-4 sm:p-6">
        <PageHeader title="Tasks and follow-ups" subtitle="Start with overdue actions, then work through today."
          actions={!isAgent && meta ? (
            <select className={`${inlineInputCls}`} value={owner || (mine ? "me" : "")}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "me") { setOwner(""); setMine(true); }
                else if (v === "") { setOwner(""); setMine(false); }
                else { setOwner(v); }
              }}>
              <option value="">Whole team</option>
              <option value="me">Only mine</option>
              {meta.people.filter((p) => p.id !== meta.user.id).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          ) : undefined} />
        {isLoading ? <TableSkeleton /> : error ? (
          <p className="text-sm text-rose-400">{error instanceof Error ? error.message : "Could not load"}</p>
        ) : (
          <>
            {section("Overdue", data?.overdue, "Nothing overdue.", true)}
            {section("Today", data?.today, "Nothing else due today.")}
            {section("Upcoming", data?.upcoming, "No upcoming follow-ups.")}
            <InfoNote>
              "Replies to re-engage" will appear here once WhatsApp messaging is added. Logging an outcome completes the task and schedules the next one automatically.
            </InfoNote>
          </>
        )}
      </div>
    </ErrorBoundary>
  );
}
