import { useEffect, useState } from "react";
import { useAuthStore } from "@/lib/authStore";
import { useUIStore } from "@/lib/uiStore";
import { useLocation, useSearchParams } from "react-router-dom";
import { LogOut, Menu, User, ChevronRight, Sun, Moon } from "lucide-react";
import { useTheme } from "@/lib/theme";

const ROUTE_MAP: Record<string, { title: string; subtitle: string }> = {
  "/dashboard": { title: "Dashboard", subtitle: "Overview & Key Business Metrics" },
  "/sales-overview": { title: "Sales Overview", subtitle: "Retail Store Performance" },
  "/operations": { title: "Daily Operations", subtitle: "Daily Submissions & Metrics" },
  "/operations/submit": { title: "New Submission", subtitle: "Log Daily Store Operations" },
  "/team-leaders": { title: "Team Leaders", subtitle: "Leader Performance & Target Tracking" },
  "/leads": { title: "Leads", subtitle: "Lead Pipeline & Conversions" },
  "/campaigns": { title: "Campaigns", subtitle: "Marketing & Channel Performance" },
  "/tasks": { title: "Tasks", subtitle: "Action Items & Assignments" },
  "/investments": { title: "Investments", subtitle: "CapEx & Operational Spend" },
  "/performance": { title: "Performance", subtitle: "KPI Scores & Incentive Bands" },
  "/reports": { title: "Reports", subtitle: "Leaderboards & Data Exports" },
  "/settings/roles": { title: "Roles & Permissions", subtitle: "Access Control & Security" },
  "/settings/users": { title: "Users", subtitle: "System Users & Store Assignments" },
  "/settings/kpi-weights": { title: "KPI Weights", subtitle: "Scoring Formula & Bands" },
  "/settings/data-sync": { title: "Data Sync", subtitle: "Google Sheets Integrations" },
  "/settings/currency": { title: "Currencies", subtitle: "Exchange Rates & Base Currency" },
  "/settings/instagram-forms": { title: "Instagram Forms", subtitle: "Lead Capture Form Builder" },
  "/settings/ai-providers": { title: "AI Providers", subtitle: "Claude & ChatGPT Configuration" },
  "/instagram": { title: "Instagram", subtitle: "Instagram Automation Dashboard" },
  "/instagram/setup": { title: "IG Setup", subtitle: "Connect & Configure Instagram Account" },
  "/instagram/conversations": { title: "Conversations", subtitle: "Instagram DM Conversations" },
  "/instagram/rules": { title: "Comment Rules", subtitle: "Automated Comment Response Rules" },
  "/instagram/submissions": { title: "Form Submissions", subtitle: "Instagram Form Submissions" },
  "/leads/update": { title: "Leads Update", subtitle: "Update tele-call leads from the city sheets" },
  "/crm": { title: "Today", subtitle: "Telecalling · your plan for today" },
  "/crm/leads": { title: "Leads", subtitle: "Telecalling · statuses, owners and follow-ups" },
  "/crm/pipeline": { title: "Pipeline", subtitle: "Telecalling · leads by stage" },
  "/crm/appointments": { title: "Appointments", subtitle: "Telecalling · store visits and attendance" },
  "/crm/tasks": { title: "Tasks", subtitle: "Telecalling · follow-ups due" },
  "/crm/reports": { title: "Reports", subtitle: "Telecalling · agent performance" },
  "/crm/alerts": { title: "Alerts", subtitle: "Telecalling · manager inbox" },
  "/crm/automation": { title: "Automation", subtitle: "Telecalling · contact workflow rules" },
  "/crm/pricing": { title: "Pricing", subtitle: "Telecalling · phone model price book" },
  "/settings/crm": { title: "Telecalling Settings", subtitle: "Access, integrations and data quality" },
};

export function Header() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const toggleMobileMenu = useUIStore((s) => s.toggleMobileMenu);
  const location = useLocation();
  const [isMd, setIsMd] = useState(false);
  const { theme, toggleTheme } = useTheme();

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 768px)");
    const handler = (e: MediaQueryListEvent | MediaQueryList) => setIsMd(e.matches);
    handler(mql);
    mql.addEventListener("change", handler as (e: MediaQueryListEvent) => void);
    return () => mql.removeEventListener("change", handler as (e: MediaQueryListEvent) => void);
  }, []);

  const currentRoute = ROUTE_MAP[location.pathname] || {
    title: "Analytics Platform",
    subtitle: "BreakProtection Platform",
  };

  const [searchParams, setSearchParams] = useSearchParams();
  const currentTab = searchParams.get("tab") || (location.pathname === "/dashboard" ? "dashboard" : "main");

  const hasTabs = [
    "/dashboard", "/sales-overview", "/operations", "/team-leaders", 
    "/leads", "/campaigns", "/tasks", "/investments", "/performance", "/reports"
  ].includes(location.pathname);

  const isDashboard = location.pathname === "/dashboard";
  const mainTabId = isDashboard ? "dashboard" : "main";
  const secondTabId = isDashboard ? "summary" : "analytics";
  const secondTabLabel = isDashboard ? "Summary" : "Analytics";

  return (
    <header
      style={{
        position: "sticky",
        top: 0,
        zIndex: 30,
        height: "64px",
        borderBottom: "1px solid var(--border-subtle)",
        backgroundColor: "var(--bg-glass)",
        backdropFilter: "blur(12px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 24px",
        flexShrink: 0,
      }}
    >
      {/* Left: Mobile Menu + Page Title */}
      <div style={{ display: "flex", alignItems: "center", gap: "12px", minWidth: 0 }}>
        {!isMd && (
          <button
            onClick={toggleMobileMenu}
            style={{
              padding: "8px",
              borderRadius: "8px",
              backgroundColor: "var(--bg-card)",
              border: "1px solid var(--border-subtle)",
              color: "var(--text-secondary)",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
            aria-label="Toggle Menu"
          >
            <Menu size={20} />
          </button>
        )}

        <div style={{ minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "var(--text-muted)", fontWeight: 500 }}>
            <span>BP Analytics</span>
            <ChevronRight size={12} style={{ color: "var(--text-muted)" }} />
            <span style={{ color: "var(--accent-blue)", fontWeight: 600 }}>{currentRoute.title}</span>
          </div>
          {hasTabs ? (
            <div style={{ display: "flex", alignItems: "center", gap: "16px", marginTop: "2px" }}>
              <button
                onClick={() => setSearchParams({ tab: mainTabId })}
                style={{
                  fontSize: "18px",
                  fontWeight: 700,
                  color: currentTab === mainTabId ? "var(--text-primary)" : "var(--text-muted)",
                  background: "none",
                  border: "none",
                  padding: 0,
                  cursor: "pointer",
                  letterSpacing: "-0.01em",
                  lineHeight: 1.3,
                  transition: "color 0.2s"
                }}
              >
                {currentRoute.title}
              </button>
              <button
                onClick={() => setSearchParams({ tab: secondTabId })}
                style={{
                  fontSize: "18px",
                  fontWeight: 700,
                  color: currentTab === secondTabId ? "var(--text-primary)" : "var(--text-muted)",
                  background: "none",
                  border: "none",
                  padding: 0,
                  cursor: "pointer",
                  letterSpacing: "-0.01em",
                  lineHeight: 1.3,
                  transition: "color 0.2s"
                }}
              >
                {secondTabLabel}
              </button>
            </div>
          ) : (
            <h1
              style={{
                fontSize: "18px",
                fontWeight: 700,
                color: "var(--text-primary)",
                letterSpacing: "-0.01em",
                lineHeight: 1.3,
                margin: 0,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {currentRoute.title}
            </h1>
          )}
        </div>
      </div>

      {/* Right: User Info & Logout */}
      <div style={{ display: "flex", alignItems: "center", gap: "12px", flexShrink: 0 }}>
        <button
          onClick={toggleTheme}
          style={{
            padding: "8px",
            borderRadius: "8px",
            backgroundColor: "var(--bg-card)",
            border: "1px solid var(--border-subtle)",
            color: "var(--text-secondary)",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
          title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          aria-label="Toggle theme"
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>

        {user?.role_name && (
          <span
            style={{
              fontSize: "12px",
              fontWeight: 600,
              padding: "4px 12px",
              borderRadius: "999px",
              backgroundColor: "rgba(59,130,246,0.1)",
              color: "#3b82f6",
              border: "1px solid rgba(59,130,246,0.2)",
              textTransform: "capitalize",
              whiteSpace: "nowrap",
            }}
          >
            {user.role_name}
          </span>
        )}

        <div
          style={{
            width: "36px",
            height: "36px",
            borderRadius: "50%",
            background: "linear-gradient(135deg, #3b82f6, #6366f1)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#fff",
            fontWeight: 700,
            fontSize: "13px",
            border: "2px solid rgba(255,255,255,0.15)",
            flexShrink: 0,
          }}
        >
          {user?.name ? user.name.charAt(0).toUpperCase() : <User size={16} />}
        </div>

        <div className="hidden sm:flex" style={{ flexDirection: "column" }}>
          <span style={{ fontSize: "13px", fontWeight: 600, color: "var(--text-primary)", lineHeight: 1.3 }}>
            {user?.name || "User"}
          </span>
          <span style={{ fontSize: "11px", color: "var(--text-muted)", lineHeight: 1.3 }}>
            {user?.role_name || ""}
          </span>
        </div>

        <button
          onClick={logout}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "6px",
            padding: "6px 12px",
            fontSize: "12px",
            fontWeight: 500,
            borderRadius: "8px",
            border: "1px solid var(--border-subtle)",
            backgroundColor: "var(--bg-card)",
            color: "var(--text-secondary)",
            cursor: "pointer",
            transition: "all 0.2s",
            whiteSpace: "nowrap",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.color = "#ef4444";
            e.currentTarget.style.borderColor = "rgba(239,68,68,0.3)";
            e.currentTarget.style.backgroundColor = "rgba(239,68,68,0.08)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.color = "var(--text-secondary)";
            e.currentTarget.style.borderColor = "var(--border-subtle)";
            e.currentTarget.style.backgroundColor = "var(--bg-card)";
          }}
          title="Sign out"
        >
          <LogOut size={15} />
          <span className="hidden md:inline">Logout</span>
        </button>
      </div>
    </header>
  );
}
