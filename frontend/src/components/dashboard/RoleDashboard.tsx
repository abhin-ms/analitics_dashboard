import { lazy, Suspense } from "react";
import { useAuthStore } from "@/lib/authStore";
import { TableSkeleton } from "@/components/shared/Skeleton";

const Dashboard = lazy(() => import("@/pages/Dashboard"));
const TeamLeaderDashboard = lazy(() => import("@/pages/TeamLeaderDashboard"));
const TelecallerDashboard = lazy(() => import("@/pages/TelecallerDashboard"));
// Store owners get sales, leads, staff and social for their store(s);
// store staff land on their store's social performance.
const StoreOwnerDashboard = lazy(() => import("@/pages/StoreOwnerDashboard"));
const StoreDashboard = lazy(() => import("@/pages/SocialPerformance"));

const ADMIN_ROLES = ["SuperAdmin", "Admin", "CEO", "COO", "Regional Manager"];

export default function RoleDashboard() {
  const role = useAuthStore((s) => s.user?.role_name);

  return (
    <Suspense fallback={<div className="p-6"><TableSkeleton /></div>}>
      {role === "Telecaller" && <TelecallerDashboard />}
      {role === "Team Leader" && <TeamLeaderDashboard />}
      {role === "Salesperson" && <TelecallerDashboard />}
      {role === "Store Owner" && <StoreOwnerDashboard />}
      {role === "Store Staff" && <div className="p-6"><StoreDashboard /></div>}
      {ADMIN_ROLES.includes(role || "") && <Dashboard />}
      {!role && <Dashboard />}
    </Suspense>
  );
}
