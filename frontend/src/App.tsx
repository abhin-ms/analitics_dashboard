import { lazy, Suspense, useEffect } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AppLayout } from "./components/layout/AppLayout";
import { getSocket, disconnectSocket } from "./lib/socket";
import { useAuthStore } from "./lib/authStore";
import Login from "./pages/Login";
import ForgotPassword from "./pages/ForgotPassword";
import SetPassword from "./pages/SetPassword";
import Dashboard from "./pages/Dashboard";
import RoleDashboard from "./components/dashboard/RoleDashboard";
import SalesOverview from "./pages/SalesOverview";
import Operations from "./pages/Operations";
import OperationsSubmit from "./pages/OperationsSubmit";
import TeamLeaders from "./pages/TeamLeaders";
import TeamLeaderDetail from "./pages/TeamLeaderDetail";
import Leads from "./pages/Leads";
import LeadDetail from "./pages/LeadDetail";
import Campaigns from "./pages/Campaigns";
import Tasks from "./pages/Tasks";
import Performance from "./pages/Performance";
import SocialPerformance from "./pages/SocialPerformance";
import Reports from "./pages/Reports";
import Investments from "./pages/Investments";
import StockPosition from "./pages/StockPosition";
import CountryComparison from "./pages/CountryComparison";
import SalesReports from "./pages/SalesReports";
import RolesPermissions from "./pages/settings/RolesPermissions";
import UserManagement from "./pages/settings/Users";
import BranchAssignment from "./pages/settings/BranchAssignment";
import SheetAssignments from "./pages/settings/SheetAssignments";
import KPIWeights from "./pages/settings/KPIWeights";
import DataSync from "./pages/settings/DataSync";
import CurrencySettings from "./pages/settings/Currency";
import InstagramForms from "./pages/settings/InstagramForms";
import AIProviders from "./pages/settings/AIProviders";
import SocialTargets from "./pages/settings/SocialTargets";
import InstagramDashboard from "./pages/instagram/InstagramDashboard";
import InstagramSetup from "./pages/instagram/InstagramSetup";
import Conversations from "./pages/instagram/Conversations";
import CommentRules from "./pages/instagram/CommentRules";
import FormSubmissions from "./pages/instagram/FormSubmissions";
import HostedForm from "./pages/instagram/HostedForm";
import TeleCallLeads from "./pages/TeleCallLeads";
import { TableSkeleton } from "./components/shared/Skeleton";

// Telecalling CRM pages
const CrmAlerts = lazy(() => import("./features/crm/pages/AlertsPage"));
const CrmAutomation = lazy(() => import("./features/crm/pages/AutomationPage"));
const CrmSettings = lazy(() => import("./features/crm/pages/CrmSettingsPage"));

/** Old /crm/... addresses now open the matching tab of the Leads page,
 * keeping their filters (the lead list's ?tab= became ?list=). */
function ToLeadsTab({ view }: { view: string }) {
  const loc = useLocation();
  const sp = new URLSearchParams(loc.search);
  if (sp.has("tab")) { sp.set("list", sp.get("tab")!); sp.delete("tab"); }
  sp.set("view", view);
  return <Navigate to={`/leads?${sp.toString()}`} replace />;
}

function Lazy({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<div className="p-6"><TableSkeleton /></div>}>{children}</Suspense>;
}

function SocketProvider({ children }: { children: React.ReactNode }) {
  // Keyed on presence, not the token's value — a silent token refresh
  // changes the token string without logging the user out, and shouldn't
  // tear down and reconnect the socket (getSocket() always sends the
  // current token on each connection attempt anyway).
  const isAuthenticated = useAuthStore((s) => !!s.token);
  useEffect(() => {
    if (isAuthenticated) getSocket();
    return () => disconnectSocket();
  }, [isAuthenticated]);
  return <>{children}</>;
}

export default function App() {
  return (
    <SocketProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/set-password/:token" element={<SetPassword />} />

        <Route element={<AppLayout />}>
          <Route path="/dashboard" element={<RoleDashboard />} />
          <Route path="/sales-overview" element={<SalesOverview />} />
          <Route path="/operations" element={<Operations />} />
          <Route path="/operations/submit" element={<OperationsSubmit />} />
          <Route path="/team-leaders" element={<TeamLeaders />} />
          <Route path="/team-leaders/:id" element={<TeamLeaderDetail />} />
          <Route path="/leads" element={<Leads />} />
          <Route path="/leads/update" element={<TeleCallLeads />} />
          <Route path="/leads/:id" element={<LeadDetail />} />
          <Route path="/campaigns" element={<Campaigns />} />
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/performance" element={<Performance />} />
          <Route path="/social-performance" element={<SocialPerformance />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/stock-position" element={<StockPosition />} />
          <Route path="/country-comparison" element={<CountryComparison />} />
          <Route path="/sales-reports" element={<SalesReports />} />
          <Route path="/investments" element={<Investments />} />
          <Route path="/instagram" element={<InstagramDashboard />} />
          <Route path="/instagram/setup" element={<InstagramSetup />} />
          <Route path="/instagram/conversations" element={<Conversations />} />
          <Route path="/instagram/rules" element={<CommentRules />} />
          <Route path="/instagram/submissions" element={<FormSubmissions />} />
          <Route path="/settings/roles" element={<RolesPermissions />} />
          <Route path="/settings/users" element={<UserManagement />} />
          <Route path="/settings/branch-assignment" element={<BranchAssignment />} />
          <Route path="/settings/sheet-assignments" element={<SheetAssignments />} />
          <Route path="/settings/kpi-weights" element={<KPIWeights />} />
          <Route path="/settings/data-sync" element={<DataSync />} />
          <Route path="/settings/currency" element={<CurrencySettings />} />
          <Route path="/settings/instagram-forms" element={<InstagramForms />} />
          <Route path="/settings/ai-providers" element={<AIProviders />} />
          <Route path="/settings/social-targets" element={<SocialTargets />} />
          {/* Telecalling now lives in the main Dashboard and the tabbed Leads page */}
          <Route path="/crm" element={<Navigate to="/dashboard" replace />} />
          <Route path="/crm/leads" element={<ToLeadsTab view="leads" />} />
          <Route path="/crm/pipeline" element={<ToLeadsTab view="pipeline" />} />
          <Route path="/crm/appointments" element={<ToLeadsTab view="appointments" />} />
          <Route path="/crm/tasks" element={<ToLeadsTab view="tasks" />} />
          <Route path="/crm/reports" element={<ToLeadsTab view="reports" />} />
          <Route path="/crm/pricing" element={<ToLeadsTab view="pricing" />} />
          <Route path="/crm/alerts" element={<Lazy><CrmAlerts /></Lazy>} />
          <Route path="/crm/automation" element={<Lazy><CrmAutomation /></Lazy>} />
          <Route path="/settings/crm" element={<Lazy><CrmSettings /></Lazy>} />
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
        </Route>

        <Route path="/ig-form/:formId/:submissionId" element={<HostedForm />} />

        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </SocketProvider>
  );
}
