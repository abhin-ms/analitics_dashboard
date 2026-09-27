import { lazy, Suspense } from "react";
import { useSearchParams } from "react-router-dom";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { AISummary } from "@/components/dashboard/AISummary";
import { TableSkeleton } from "@/components/shared/Skeleton";

// The Leads section is now one page with tabs (Team, Leads, Pipeline,
// Appointments, Tasks, Reports, Pricing) for every role. It replaces the
// old per-city summary table, whose numbers now live in the Team tab and
// the status chips of the Leads tab. The header's Analytics tab is unchanged.
const LeadsHub = lazy(() => import("@/features/crm/pages/LeadsHub"));

export default function Leads() {
  const [searchParams] = useSearchParams();
  const tab = searchParams.get("tab") || "main";

  return (
    <ErrorBoundary>
      {tab === "analytics" ? (
        <AISummary section="leads" title="Leads AI Summary" />
      ) : (
        <Suspense fallback={<div className="p-6"><TableSkeleton /></div>}>
          <LeadsHub />
        </Suspense>
      )}
    </ErrorBoundary>
  );
}
