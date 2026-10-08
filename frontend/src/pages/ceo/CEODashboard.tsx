import { useState, useEffect, useCallback } from "react";
import { OverviewTab } from "./OverviewTab";
import { DailyOpsTab } from "./DailyOpsTab";
import { TLWiseTab } from "./TLWiseTab";
import { InternationalTab } from "./InternationalTab";
import { MarketingTab } from "./MarketingTab";
import { ReviewsTab } from "./ReviewsTab";
import { PeopleTab } from "./PeopleTab";
import { ActionCenterTab } from "./ActionCenterTab";
import { useAuthStore } from "@/lib/authStore";
import { api } from "@/lib/apiClient";
import { useSocketRefresh } from "../../hooks/useSocketRefresh";

const TABS = [
  { id: "overview", label: "Overview", icon: "📊" },
  { id: "ops", label: "Daily Ops", icon: "⚡" },
  { id: "tl", label: "TL Wise", icon: "👥" },
  { id: "intl", label: "International", icon: "🌍" },
  { id: "marketing", label: "Marketing", icon: "📣" },
  { id: "reviews", label: "Reviews", icon: "⭐" },
  { id: "people", label: "People", icon: "👤" },
  { id: "actions", label: "Action Center", icon: "🎯" },
];

export default function CEODashboard() {
  useSocketRefresh(["sheets-data"]);
  const [activeTab, setActiveTab] = useState("overview");
  const [sheetsData, setSheetsData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const hasPermission = useAuthStore((s) => s.hasPermission);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.fetchRaw("/ceo-dashboard/sheets-data?tab=all");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setSheetsData(data);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  if (!hasPermission("dashboard", "view")) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: "var(--text-secondary)" }}>
        <p style={{ fontSize: 18 }}>You don't have permission to view the CEO Dashboard.</p>
      </div>
    );
  }

  const renderTab = () => {
    if (loading) {
      return (
        <div style={{ padding: 60, textAlign: "center", color: "var(--text-secondary)" }}>
          <div style={{ fontSize: 14, marginTop: 12 }}>Loading data from Google Sheets...</div>
        </div>
      );
    }
    if (error) {
      return (
        <div style={{ padding: 60, textAlign: "center", color: "#ef4444" }}>
          <p style={{ fontSize: 16, fontWeight: 600 }}>Failed to load data</p>
          <p style={{ fontSize: 13, marginTop: 8, color: "var(--text-secondary)" }}>{error}</p>
          <button
            onClick={fetchData}
            style={{
              marginTop: 16, padding: "8px 20px", borderRadius: 8,
              background: "#3b82f6", color: "#fff", border: "none",
              cursor: "pointer", fontSize: 13, fontWeight: 600,
            }}
          >
            Retry
          </button>
        </div>
      );
    }
    switch (activeTab) {
      case "overview": return <OverviewTab data={sheetsData} />;
      case "ops": return <DailyOpsTab data={sheetsData} />;
      case "tl": return <TLWiseTab data={sheetsData} />;
      case "intl": return <InternationalTab data={sheetsData} />;
      case "marketing": return <MarketingTab data={sheetsData} />;
      case "reviews": return <ReviewsTab data={sheetsData} />;
      case "people": return <PeopleTab data={sheetsData} />;
      case "actions": return <ActionCenterTab data={sheetsData} />;
      default: return null;
    }
  };

  return (
    <div style={{ minHeight: "100%" }}>
      {/* Header */}
      <div style={{
        background: "linear-gradient(135deg, var(--bg-card), var(--bg-card), var(--bg-card))",
        padding: "14px 24px", display: "flex", alignItems: "center",
        justifyContent: "space-between", borderRadius: "12px 12px 0 0",
        borderBottom: "2px solid #2563eb", marginBottom: 0,
      }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 800, color: "var(--tone-blue-fg)", letterSpacing: 1 }}>
            BP <span style={{ color: "#f59e0b" }}>Analytics</span>
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
            CEO Decision Dashboard
          </div>
        </div>
        <div style={{ textAlign: "right", fontSize: 12, color: "var(--text-secondary)" }}>
          <strong style={{ color: "var(--text-primary)", display: "block", fontSize: 14 }}>India · UAE · Oman</strong>
          <span>24 India + 19 Intl Stores</span>
        </div>
      </div>

      {/* Tabs */}
      <div style={{
        display: "flex", background: "var(--bg-card)", borderBottom: "2px solid var(--border-subtle)",
        overflowX: "auto", gap: 0,
      }}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              padding: "11px 14px", cursor: "pointer", fontSize: 12,
              fontWeight: 600, border: "none", whiteSpace: "nowrap",
              color: activeTab === tab.id ? "var(--tone-blue-fg)" : "var(--text-muted)",
              background: activeTab === tab.id ? "var(--border-subtle)" : "transparent",
              borderBottom: activeTab === tab.id ? "2px solid #2563eb" : "2px solid transparent",
              marginBottom: -2, transition: "all 0.2s",
            }}
          >
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ padding: "20px 24px" }}>
        {renderTab()}
      </div>
    </div>
  );
}
