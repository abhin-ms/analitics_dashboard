import { Outlet, Navigate } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Header } from "./Header";
import { useAuthStore } from "@/lib/authStore";
import { useUIStore } from "@/lib/uiStore";
import { useEffect, useState } from "react";
import { LeadDrawerHost } from "@/features/crm/components/LeadDrawer";
import { CrmGlobalListeners } from "@/features/crm/components/shared";

const SIDEBAR_EXPANDED = 256;
const SIDEBAR_COLLAPSED = 80;

export function AppLayout() {
  const token = useAuthStore((s) => s.token);
  const sidebarCollapsed = useUIStore((s) => s.sidebarCollapsed);
  const [isMd, setIsMd] = useState(false);

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 768px)");
    const handler = (e: MediaQueryListEvent | MediaQueryList) => setIsMd(e.matches);
    handler(mql);
    mql.addEventListener("change", handler as (e: MediaQueryListEvent) => void);
    return () => mql.removeEventListener("change", handler as (e: MediaQueryListEvent) => void);
  }, []);

  if (!token) return <Navigate to="/login" replace />;

  const sidebarWidth = isMd
    ? (sidebarCollapsed ? SIDEBAR_COLLAPSED : SIDEBAR_EXPANDED)
    : 0;

  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        backgroundColor: "var(--bg-primary)",
        color: "var(--text-primary)",
        overflow: "hidden",
      }}
    >
      {/* Sidebar — fixed position */}
      <Sidebar />

      {/* Content area — fills remaining space next to sidebar */}
      <div
        style={{
          marginLeft: sidebarWidth,
          width: `calc(100% - ${sidebarWidth}px)`,
          height: "100vh",
          display: "flex",
          flexDirection: "column",
          transition: "margin-left 0.3s ease, width 0.3s ease",
          overflow: "hidden",
        }}
      >
        <Header />
        <main
          style={{
            flex: 1,
            padding: "24px",
            overflowY: "auto",
            overflowX: "hidden",
            width: "100%",
            boxSizing: "border-box",
          }}
        >
          <Outlet />
        </main>
      </div>
      {/* Telecalling CRM: lead drawer (opens from any page) + live alerts */}
      <LeadDrawerHost />
      <CrmGlobalListeners />
    </div>
  );
}
