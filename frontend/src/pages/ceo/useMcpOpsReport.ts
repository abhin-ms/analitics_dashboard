import { useEffect, useState } from "react";
import { api } from "@/lib/apiClient";

function currentMonthRange() {
  const now = new Date();
  const from = new Date(now.getFullYear(), now.getMonth(), 1);
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return { from: iso(from), to: iso(now) };
}

// Shared by every CEO Dashboard tab that used to compute revenue/target
// from processOpsData(data.ops_data) — fetches the same MCP-backed report
// /sales-reports already uses elsewhere (Dashboard, Store Overview, Team
// Leaders, Performance), scoped to India to match what these tabs have
// always covered (walk-ins/TL data is India-only regardless).
//
// start/end are passed explicitly (current month to date) because
// /sales-reports defaults an unspecified range to just TODAY when
// granularity=day — omitting them here previously made every CEO Dashboard
// tab silently show only today's revenue instead of month-to-date, which
// is why those tabs briefly showed very different totals than the main
// Dashboard page (which always passes an explicit range).
export function useMcpOpsReport() {
  const [branchBreakdown, setBranchBreakdown] = useState<any[]>([]);
  const [tlBreakdown, setTlBreakdown] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const { from, to } = currentMonthRange();
    Promise.all([
      api.fetchRaw(`/sales-reports?group_by=branch&granularity=day&country=India&start=${from}&end=${to}`),
      api.fetchRaw(`/sales-reports?group_by=team_leader&granularity=day&country=India&start=${from}&end=${to}`),
    ]).then(async ([branchRes, tlRes]) => {
      if (cancelled) return;
      if (branchRes.ok) setBranchBreakdown((await branchRes.json()).breakdown || []);
      if (tlRes.ok) setTlBreakdown((await tlRes.json()).breakdown || []);
      setLoading(false);
    }).catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return { branchBreakdown, tlBreakdown, loading };
}
