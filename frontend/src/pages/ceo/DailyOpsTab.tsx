import { useMemo } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, Legend } from "recharts";
import { processMcpOpsData, pct, ragColor, ragBg, formatINR, formatNum, shortStore } from "./types";
import { useMcpOpsReport } from "./useMcpOpsReport";
import { useSocketRefresh } from "../../hooks/useSocketRefresh";

export function DailyOpsTab({ data }: { data: any }) {
  useSocketRefresh(["sheets-data"]);
  const { branchBreakdown, tlBreakdown } = useMcpOpsReport();
  const ops = useMemo(() => processMcpOpsData(branchBreakdown, tlBreakdown), [branchBreakdown, tlBreakdown]);

  if (!ops) {
    return <div style={{ padding: 40, textAlign: "center", color: "var(--text-secondary)" }}>No operations data available</div>;
  }

  const zeroRevStores = ops.storeAchievements.filter((s) => s.mtd === 0).length;

  const kpis = [
    { label: "India MTD Revenue", value: formatINR(ops.totalRevenue), sub: `vs ${formatINR(ops.totalTarget)} target`, color: "#3b82f6" },
    { label: "Walk-ins (Month)", value: formatNum(ops.totalWalkins), sub: `${formatNum(ops.totalConversions)} converted · ${ops.overallConv}%`, color: "#10b981" },
    { label: "Overall Achievement", value: `${ops.overallAch}%`, sub: `${ops.tlList.length} TLs · ${ops.storeAchievements.length} stores`, color: "#f59e0b" },
    { label: "Zero Revenue Stores", value: String(zeroRevStores), sub: "stores with ₹0 revenue", color: "#ef4444" },
  ];

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(155px, 1fr))", gap: 14, marginBottom: 20 }}>
        {kpis.map((k, i) => (
          <div key={i} style={{ background: "linear-gradient(135deg, var(--bg-card), var(--bg-card-hover))", border: "1px solid var(--border-subtle)", borderRadius: 10, padding: 16, position: "relative", overflow: "hidden" }}>
            <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 3, background: k.color }} />
            <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>{k.label}</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)" }}>{k.value}</div>
            <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4 }}>{k.sub}</div>
          </div>
        ))}
      </div>

      {/* Store Table */}
      <div style={{ overflowX: "auto", marginBottom: 20 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              {["Store", "TL", "MTD Rev (₹)", "Walk-ins", "Sales", "Conv%", "Target (₹)", "Ach%", "Status"].map((h) => (
                <th key={h} style={{ background: "var(--bg-subtle)", color: "var(--text-secondary)", padding: "9px 10px", textAlign: "left", borderBottom: "1px solid var(--border-subtle)", fontSize: 11, textTransform: "uppercase", letterSpacing: 0.3, whiteSpace: "nowrap" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ops.storeAchievements.map((sa, i) => (
              <tr key={i} style={{ borderBottom: "1px solid var(--border-subtle)", transition: "background 0.15s" }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--border-subtle)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>
                <td style={{ padding: "8px 10px", color: "var(--text-primary)", fontWeight: 500 }}>{sa.store}</td>
                <td style={{ padding: "8px 10px", color: "var(--text-primary)" }}>{sa.tl}</td>
                <td style={{ padding: "8px 10px", color: "var(--text-primary)", textAlign: "right" }}>{sa.mtd.toLocaleString("en-IN")}</td>
                <td style={{ padding: "8px 10px", color: "var(--text-primary)", textAlign: "center" }}>{sa.walkins}</td>
                <td style={{ padding: "8px 10px", color: "var(--text-primary)", textAlign: "center" }}>{sa.sales}</td>
                <td style={{ padding: "8px 10px", color: "var(--text-primary)", textAlign: "center" }}>{sa.convPct}%</td>
                <td style={{ padding: "8px 10px", color: "var(--text-primary)", textAlign: "right" }}>{sa.target.toLocaleString("en-IN")}</td>
                <td style={{ padding: "8px 10px", textAlign: "left" }}>
                  <div style={{ width: "100%", background: "var(--track)", borderRadius: 4, height: 6, overflow: "hidden", marginBottom: 2 }}>
                    <div style={{ height: "100%", borderRadius: 4, width: `${Math.min(sa.achPct, 100)}%`, background: ragColor(sa.achPct) }} />
                  </div>
                  <span style={{ fontSize: 10, color: "var(--text-secondary)" }}>{sa.achPct}%</span>
                </td>
                <td style={{ padding: "8px 10px" }}>
                  <span style={{
                    display: "inline-block", padding: "2px 8px", borderRadius: 12, fontSize: 10, fontWeight: 700,
                    background: sa.achPct >= 65 ? "var(--tone-green-bg)" : sa.achPct >= 35 ? "var(--tone-amber-bg)" : "var(--tone-red-bg)",
                    color: sa.achPct >= 65 ? "var(--tone-green-fg)" : sa.achPct >= 35 ? "var(--tone-amber-fg)" : "var(--tone-red-fg)",
                  }}>
                    {sa.achPct >= 65 ? "✅ Green" : sa.achPct >= 35 ? "⚡ Amber" : sa.achPct > 0 ? "🔴 Red" : "⚫ None"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Charts */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 20 }}>
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 10, padding: 16 }}>
          <h3 style={{ fontSize: 12, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>MTD Achievement % — All Stores</h3>
          <ResponsiveContainer width="100%" height={400}>
            <BarChart data={ops.storeAchievements} layout="vertical" margin={{ left: 10, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
              <XAxis type="number" domain={[0, 120]} tick={{ fill: "var(--text-muted)", fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
              <YAxis type="category" dataKey="store" tick={{ fill: "var(--text-secondary)", fontSize: 9 }} width={130} tickFormatter={shortStore} />
              <Tooltip formatter={(v: any) => [`${v}%`, "Achievement"]} contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} />
              <Bar dataKey="achPct" radius={[0, 4, 4, 0]}>
                {ops.storeAchievements.map((s, i) => <Cell key={i} fill={ragColor(s.achPct)} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 10, padding: 16 }}>
          <h3 style={{ fontSize: 12, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>Walk-in vs Conversion</h3>
          <ResponsiveContainer width="100%" height={400}>
            <BarChart data={ops.storeAchievements.filter((s) => s.walkins > 0)}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
              <XAxis dataKey="store" tick={{ fill: "var(--text-secondary)", fontSize: 9 }} tickFormatter={shortStore} angle={-45} textAnchor="end" height={80} />
              <YAxis tick={{ fill: "var(--text-muted)", fontSize: 10 }} />
              <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} />
              <Legend wrapperStyle={{ fontSize: 11, color: "var(--text-secondary)" }} />
              <Bar dataKey="walkins" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              <Bar dataKey="sales" fill="#10b981" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
