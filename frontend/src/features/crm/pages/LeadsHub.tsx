/** The single Leads section: one page with tabs instead of separate menu
 * items (Team, Leads, Pipeline, Appointments, Tasks, Reports, Pricing). */
import { lazy, Suspense } from "react";
import { useSearchParams } from "react-router-dom";
import { TableSkeleton } from "@/components/shared/Skeleton";
import { useCrmMeta } from "../api";
import { Tabs } from "../components/ui";

const TeamTab = lazy(() => import("./TeamTab"));
const LeadsPage = lazy(() => import("./LeadsPage"));
const PipelinePage = lazy(() => import("./PipelinePage"));
const AppointmentsPage = lazy(() => import("./AppointmentsPage"));
const TasksPage = lazy(() => import("./TasksPage"));
const ReportsPage = lazy(() => import("./ReportsPage"));
const PricingPage = lazy(() => import("./PricingPage"));

export default function LeadsHub() {
  const { data: meta } = useCrmMeta();
  const [sp, setSp] = useSearchParams();
  const canSeeTeam = !!meta?.can.see_team;
  const views = [
    ...(canSeeTeam ? [{ key: "team", label: "Team" }] : []),
    { key: "leads", label: "Leads" },
    { key: "pipeline", label: "Pipeline" },
    { key: "appointments", label: "Appointments" },
    { key: "tasks", label: "Tasks" },
    { key: "reports", label: meta && !canSeeTeam ? "My performance" : "Reports" },
    { key: "pricing", label: "Pricing" },
  ];
  const requested = sp.get("view") || (canSeeTeam ? "team" : "leads");
  const view = views.some((v) => v.key === requested) ? requested : "leads";

  return (
    <div className="space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-bold text-white tracking-tight">Leads</h1>
        <p className="text-xs text-[var(--text-muted)] mt-0.5">Meta leads from the city Google Sheets, worked here.</p>
      </div>
      <Tabs tabs={views} value={view} onChange={(v) => setSp(new URLSearchParams({ view: v }))} />
      <Suspense fallback={<TableSkeleton />}>
        {!meta ? <TableSkeleton /> : (
          <>
            {view === "team" && <TeamTab />}
            {view === "leads" && <LeadsPage embedded />}
            {view === "pipeline" && <PipelinePage embedded />}
            {view === "appointments" && <AppointmentsPage embedded />}
            {view === "tasks" && <TasksPage embedded />}
            {view === "reports" && <ReportsPage embedded />}
            {view === "pricing" && <PricingPage embedded />}
          </>
        )}
      </Suspense>
    </div>
  );
}
