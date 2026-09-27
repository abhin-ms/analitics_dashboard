import { NavLink, useLocation } from "react-router-dom";
import { useState } from "react";
import { useAuthStore } from "@/lib/authStore";
import { useUIStore } from "@/lib/uiStore";
import {
  LayoutDashboard, ShoppingCart, Users, Phone,
  Megaphone, CheckSquare, BarChart3, FileText, Settings,
  DollarSign, TrendingUp, X, ChevronLeft, ChevronRight, ShieldCheck,
  Camera, MessageCircle, Shield, Table, Settings2, ChevronDown,
  RefreshCw, Brain, Package, Globe, PhoneCall, MapPin,
  Sun, Columns3, CalendarDays, ListChecks, Bell, Zap, IndianRupee, Headset,
} from "lucide-react";

interface NavItem {
  to: string;
  label: string;
  icon: React.ComponentType<{ size?: number; style?: React.CSSProperties }>;
  resource: string;
  /** Only these roles see the item (default: every role that sees the section). */
  roles?: string[];
}

const MAIN_NAV_ITEMS: NavItem[] = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, resource: "dashboard" },
  { to: "/sales-overview", label: "Sales Overview", icon: TrendingUp, resource: "operations" },
  { to: "/operations", label: "Operations", icon: ShoppingCart, resource: "operations" },
  { to: "/team-leaders", label: "Team Leaders", icon: Users, resource: "team_leaders" },
  { to: "/leads", label: "Leads", icon: Phone, resource: "leads" },
  { to: "/leads/update", label: "Leads Update", icon: PhoneCall, resource: "leads" },
  { to: "/campaigns", label: "Campaigns", icon: Megaphone, resource: "campaigns" },
  { to: "/tasks", label: "Tasks", icon: CheckSquare, resource: "tasks" },
  { to: "/investments", label: "Investments", icon: DollarSign, resource: "investments" },
  { to: "/performance", label: "Performance", icon: BarChart3, resource: "performance" },
  { to: "/reports", label: "Reports", icon: FileText, resource: "reports" },
  { to: "/stock-position", label: "Stock Position", icon: Package, resource: "dashboard" },
  { to: "/country-comparison", label: "Country Comparison", icon: Globe, resource: "dashboard" },
  { to: "/sales-reports", label: "Sales Reports", icon: BarChart3, resource: "dashboard" },
];

const INSTAGRAM_NAV_ITEMS: NavItem[] = [
  { to: "/instagram", label: "Dashboard", icon: BarChart3, resource: "instagram" },
  { to: "/instagram/setup", label: "Setup", icon: Settings2, resource: "instagram" },
  { to: "/instagram/conversations", label: "Conversations", icon: MessageCircle, resource: "instagram" },
  { to: "/instagram/rules", label: "Comment Rules", icon: Shield, resource: "instagram" },
  { to: "/instagram/submissions", label: "Submissions", icon: Table, resource: "instagram" },
];

const SETTINGS_NAV_ITEMS: NavItem[] = [
  { to: "/settings/roles", label: "Roles & Permissions", icon: Shield, resource: "settings" },
  // Gated on "users" rather than the blanket "settings" permission so a CEO
  // (who can create accounts but shouldn't see Roles/KPI-Weights/Currency)
  // gets just this one item instead of the whole Settings area.
  { to: "/settings/users", label: "Users", icon: Users, resource: "users" },
  { to: "/settings/branch-assignment", label: "Team Leaders & Branches", icon: MapPin, resource: "settings" },
  { to: "/settings/sheet-assignments", label: "Sheet Assignments", icon: PhoneCall, resource: "leads" },
  { to: "/settings/kpi-weights", label: "KPI Weights", icon: BarChart3, resource: "settings" },
  { to: "/settings/data-sync", label: "Data Sync", icon: RefreshCw, resource: "settings" },
  { to: "/settings/currency", label: "Currency", icon: DollarSign, resource: "settings" },
  { to: "/settings/instagram-forms", label: "Instagram Forms", icon: FileText, resource: "settings" },
  { to: "/settings/ai-providers", label: "AI Providers", icon: Brain, resource: "settings" },
  { to: "/settings/crm", label: "Telecalling Settings", icon: Headset, resource: "settings" },
  { to: "/crm/automation", label: "Telecalling Automation", icon: Zap, resource: "settings" },
];

const SIDEBAR_EXPANDED = 256;
const SIDEBAR_COLLAPSED = 80;

function NavItemLink({
  item,
  collapsed,
  mobileOpen,
  onNavigate,
  indent,
}: {
  item: NavItem;
  collapsed: boolean;
  mobileOpen: boolean;
  onNavigate: () => void;
  indent?: boolean;
}) {
  return (
    <NavLink
      to={item.to}
      end={item.to === "/instagram" || item.to === "/leads"}
      onClick={onNavigate}
      style={({ isActive }) => ({
        display: "flex",
        alignItems: "center",
        gap: "12px",
        padding: collapsed && !mobileOpen ? "10px 0" : indent ? "8px 14px 8px 28px" : "10px 14px",
        justifyContent: collapsed && !mobileOpen ? "center" : "flex-start",
        borderRadius: "12px",
        fontSize: indent ? "13px" : "14px",
        fontWeight: isActive ? 600 : 500,
        color: isActive ? "#3b82f6" : "var(--text-secondary)",
        backgroundColor: isActive ? "rgba(59,130,246,0.12)" : "transparent",
        border: isActive ? "1px solid rgba(59,130,246,0.25)" : "1px solid transparent",
        textDecoration: "none",
        transition: "all 0.2s",
        position: "relative",
        whiteSpace: "nowrap",
        overflow: "hidden",
      })}
      onMouseEnter={(e) => {
        if (!e.currentTarget.style.backgroundColor?.includes("59,130,246")) {
          e.currentTarget.style.backgroundColor = "var(--bg-card-hover)";
          e.currentTarget.style.color = "var(--text-primary)";
        }
      }}
      onMouseLeave={(e) => {
        const isActive = e.currentTarget.getAttribute("aria-current") === "page";
        if (!isActive) {
          e.currentTarget.style.backgroundColor = "transparent";
          e.currentTarget.style.color = "var(--text-secondary)";
        }
      }}
    >
      <item.icon size={indent ? 16 : 20} style={{ flexShrink: 0 }} />
      {(!collapsed || mobileOpen) && (
        <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{item.label}</span>
      )}
    </NavLink>
  );
}

function CollapsibleSection({
  label,
  icon: Icon,
  items,
  collapsed,
  mobileOpen,
  onNavigate,
  isOpen,
  onToggle,
  accentColor,
}: {
  label: string;
  icon: React.ComponentType<{ size?: number; style?: React.CSSProperties }>;
  items: NavItem[];
  collapsed: boolean;
  mobileOpen: boolean;
  onNavigate: () => void;
  isOpen: boolean;
  onToggle: () => void;
  accentColor: string;
}) {
  const location = useLocation();
  const isAnyActive = items.some((item) => location.pathname === item.to || location.pathname.startsWith(item.to + "/"));

  if (items.length === 0) return null;

  return (
    <div>
      <button
        onClick={onToggle}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "12px",
          width: "100%",
          padding: collapsed && !mobileOpen ? "10px 0" : "10px 14px",
          justifyContent: collapsed && !mobileOpen ? "center" : "flex-start",
          borderRadius: "12px",
          fontSize: "14px",
          fontWeight: isAnyActive ? 600 : 500,
          color: isAnyActive ? accentColor : "var(--text-secondary)",
          backgroundColor: isAnyActive ? `${accentColor}18` : "transparent",
          border: isAnyActive ? `1px solid ${accentColor}40` : "1px solid transparent",
          cursor: "pointer",
          transition: "all 0.2s",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textAlign: "left",
          background: isAnyActive ? `${accentColor}18` : "transparent",
        }}
        onMouseEnter={(e) => {
          if (!isAnyActive) {
            e.currentTarget.style.backgroundColor = "var(--bg-card-hover)";
            e.currentTarget.style.color = "var(--text-primary)";
          }
        }}
        onMouseLeave={(e) => {
          if (!isAnyActive) {
            e.currentTarget.style.backgroundColor = "transparent";
            e.currentTarget.style.color = "var(--text-secondary)";
          }
        }}
      >
        <Icon size={20} style={{ flexShrink: 0 }} />
        {(!collapsed || mobileOpen) && (
          <>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", flex: 1 }}>{label}</span>
            <ChevronDown
              size={14}
              style={{
                flexShrink: 0,
                transition: "transform 0.2s",
                transform: isOpen ? "rotate(180deg)" : "rotate(0deg)",
                opacity: 0.5,
              }}
            />
          </>
        )}
      </button>
      {isOpen && (!collapsed || mobileOpen) && (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "2px",
            marginTop: "2px",
            paddingLeft: "4px",
            borderLeft: `2px solid ${accentColor}30`,
            marginLeft: "24px",
          }}
        >
          {items.map((item) => (
            <NavItemLink
              key={item.to}
              item={item}
              collapsed={collapsed}
              mobileOpen={mobileOpen}
              onNavigate={onNavigate}
              indent
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function Sidebar() {
  const collapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const mobileOpen = useUIStore((s) => s.mobileMenuOpen);
  const setMobileOpen = useUIStore((s) => s.setMobileMenuOpen);
  const hasPermission = useAuthStore((s) => s.hasPermission);
  const user = useAuthStore((s) => s.user);
  const location = useLocation();

  const role = user?.role_name || "";
  const isTelecaller = role === "Telecaller";
  const isTeamLeader = role === "Team Leader";

  const [igOpen, setIgOpen] = useState(() => location.pathname.startsWith("/instagram"));
  const [settingsOpen, setSettingsOpen] = useState(() => location.pathname.startsWith("/settings"));


  // team-leaders/reports/performance/leads all pull from the unscoped,
  // company-wide sheets-data endpoint (every branch, every team leader) —
  // a Team Leader has their own scoped dashboard/leads-update pages instead.
  // "/leads" is the tabbed telecalling Leads page (role-scoped), so team
  // leaders and telecallers see it too.
  const HIDDEN_FOR_TL = ["/operations", "/stock-position", "/country-comparison", "/investments", "/instagram", "/sales-overview", "/sales-reports", "/team-leaders", "/reports", "/performance"];
  const HIDDEN_FOR_TELECALLER = ["/operations", "/stock-position", "/country-comparison", "/investments", "/instagram", "/sales-overview", "/sales-reports", "/team-leaders", "/campaigns", "/tasks", "/performance", "/reports"];

  const visibleMainItems = MAIN_NAV_ITEMS.filter((item) => {
    if (!hasPermission(item.resource, "view")) return false;
    if (isTelecaller) return !HIDDEN_FOR_TELECALLER.includes(item.to);
    if (isTeamLeader) return !HIDDEN_FOR_TL.includes(item.to);
    return true;
  });
  const visibleIgItems = isTelecaller || isTeamLeader ? [] : INSTAGRAM_NAV_ITEMS.filter((item) =>
    hasPermission(item.resource, "view")
  );
  const visibleSettingsItems = isTelecaller || isTeamLeader ? [] : SETTINGS_NAV_ITEMS.filter((item) =>
    hasPermission(item.resource, "view")
  );

  const sidebarWidth = collapsed ? SIDEBAR_COLLAPSED : SIDEBAR_EXPANDED;

  return (
    <>
      {/* Mobile Drawer Overlay */}
      {mobileOpen && (
        <div
          onClick={() => setMobileOpen(false)}
          style={{
            position: "fixed",
            inset: 0,
            backgroundColor: "rgba(0,0,0,0.7)",
            backdropFilter: "blur(2px)",
            zIndex: 40,
          }}
          className="md:hidden"
        />
      )}

      {/* Sidebar */}
      <aside
        style={{
          position: "fixed",
          left: 0,
          top: 0,
          height: "100vh",
          width: mobileOpen ? SIDEBAR_EXPANDED : sidebarWidth,
          backgroundColor: "var(--bg-card)",
          borderRight: "1px solid var(--border-subtle)",
          zIndex: 50,
          display: "flex",
          flexDirection: "column",
          transition: "width 0.3s ease, transform 0.3s ease",
          transform: mobileOpen ? "translateX(0)" : undefined,
          boxShadow: "4px 0 24px rgba(0,0,0,0.3)",
          overflow: "hidden",
        }}
        className={mobileOpen ? "" : "-translate-x-full md:translate-x-0"}
      >
        {/* Brand Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: collapsed && !mobileOpen ? "center" : "space-between",
            height: "64px",
            padding: "0 16px",
            borderBottom: "1px solid var(--border-subtle)",
            flexShrink: 0,
          }}
        >
          {(!collapsed || mobileOpen) && (
            <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <div
                style={{
                  width: "36px",
                  height: "36px",
                  borderRadius: "10px",
                  background: "rgba(59,130,246,0.15)",
                  border: "1px solid rgba(59,130,246,0.3)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#3b82f6",
                  flexShrink: 0,
                }}
              >
                <ShieldCheck size={20} />
              </div>
              <div>
                <span
                  style={{
                    display: "block",
                    fontSize: "15px",
                    fontWeight: 700,
                    color: "var(--text-primary)",
                    lineHeight: 1.2,
                    whiteSpace: "nowrap",
                  }}
                >
                  BP Analytics
                </span>
                <span
                  style={{
                    display: "block",
                    fontSize: "10px",
                    fontWeight: 600,
                    textTransform: "uppercase",
                    letterSpacing: "0.08em",
                    color: "var(--text-muted)",
                  }}
                >
                  Enterprise
                </span>
              </div>
            </div>
          )}

          {collapsed && !mobileOpen && (
            <div
              style={{
                width: "40px",
                height: "40px",
                borderRadius: "10px",
                background: "rgba(59,130,246,0.15)",
                border: "1px solid rgba(59,130,246,0.3)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#3b82f6",
              }}
            >
              <ShieldCheck size={22} />
            </div>
          )}

          {/* Desktop Collapse Button */}
          <button
            onClick={toggleSidebar}
            className="hidden md:flex"
            style={{
              padding: "6px",
              borderRadius: "8px",
              border: "none",
              background: "transparent",
              color: "var(--text-muted)",
              cursor: "pointer",
              transition: "color 0.2s, background 0.2s",
              flexShrink: 0,
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = "var(--text-primary)";
              e.currentTarget.style.background = "var(--border-subtle)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = "var(--text-muted)";
              e.currentTarget.style.background = "transparent";
            }}
            title={collapsed ? "Expand Sidebar" : "Collapse Sidebar"}
          >
            {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
          </button>

          {/* Mobile Close */}
          <button
            onClick={() => setMobileOpen(false)}
            className="md:hidden"
            style={{
              padding: "6px",
              borderRadius: "8px",
              border: "none",
              background: "transparent",
              color: "var(--text-muted)",
              cursor: "pointer",
            }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Nav Items */}
        <nav
          style={{
            flex: 1,
            padding: "16px 8px",
            overflowY: "auto",
            display: "flex",
            flexDirection: "column",
            gap: "4px",
          }}
        >
          {/* Main Nav Items */}
          {visibleMainItems.map((item) => (
            <NavItemLink
              key={item.to}
              item={item}
              collapsed={collapsed}
              mobileOpen={mobileOpen}
              onNavigate={() => setMobileOpen(false)}
            />
          ))}

          {/* Instagram Section */}
          {visibleIgItems.length > 0 && (
            <>
              {(!collapsed || mobileOpen) && (
                <div
                  style={{
                    height: "1px",
                    background: "var(--border-subtle)",
                    margin: "8px 8px",
                  }}
                />
              )}
              <CollapsibleSection
                label="Instagram"
                icon={Camera}
                items={visibleIgItems}
                collapsed={collapsed}
                mobileOpen={mobileOpen}
                onNavigate={() => setMobileOpen(false)}
                isOpen={igOpen}
                onToggle={() => setIgOpen(!igOpen)}
                accentColor="#e879f9"
              />
            </>
          )}

          {/* Settings Section */}
          {visibleSettingsItems.length > 0 && (
            <>
              {(!collapsed || mobileOpen) && (
                <div
                  style={{
                    height: "1px",
                    background: "var(--border-subtle)",
                    margin: "8px 8px",
                  }}
                />
              )}
              <CollapsibleSection
                label="Settings"
                icon={Settings}
                items={visibleSettingsItems}
                collapsed={collapsed}
                mobileOpen={mobileOpen}
                onNavigate={() => setMobileOpen(false)}
                isOpen={settingsOpen}
                onToggle={() => setSettingsOpen(!settingsOpen)}
                accentColor="#3b82f6"
              />
            </>
          )}
        </nav>
      </aside>
    </>
  );
}
