import { useMemo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from "recharts";
import { processMcpOpsData, pct, ragColor, formatINR, formatNum, shortStore } from "./types";
import { useMcpOpsReport } from "./useMcpOpsReport";
import { useSocketRefresh } from "../../hooks/useSocketRefresh";

export function OverviewTab({ data }: { data: any }) {
  useSocketRefresh(["sheets-data"]);
  const { branchBreakdown, tlBreakdown } = useMcpOpsReport();
  const ops = useMemo(() => processMcpOpsData(branchBreakdown, tlBreakdown), [branchBreakdown, tlBreakdown]);
  const staff = data?.staff || [];
  const intlStaff = data?.intl_staff || [];
  const reviews = data?.reviews || [];
  const configV2 = data?.store_config_v2 || [];

  if (!ops) {
    return <div style={{ padding: 40, textAlign: "center", color: "var(--text-secondary)" }}>No operations data available</div>;
  }

  // KPI cards
  const kpis = [
    { label: "India MTD Revenue", value: formatINR(ops.totalRevenue), sub: `vs ${formatINR(ops.totalTarget)} target`, color: "#3b82f6" },
    { label: "India Achievement", value: `${ops.overallAch}%`, sub: `${ops.tlList.length} TLs · ${ops.storeAchievements.length} stores`, color: ops.overallAch >= 50 ? "#10b981" : "#f59e0b" },
    { label: "Walk-ins (Month)", value: formatNum(ops.totalWalkins), sub: `${formatNum(ops.totalConversions)} conversions · ${ops.overallConv}%`, color: "#10b981" },
    { label: "Critical Stores", value: String(ops.rag.red), sub: `${ops.rag.red} below 35% target`, color: "#ef4444" },
    { label: "Green Stores (≥65%)", value: String(ops.rag.green), sub: `${ops.rag.green} stores on track`, color: "#10b981" },
    { label: "Amber Stores (35-64%)", value: String(ops.rag.amber), sub: `${ops.rag.amber} need attention`, color: "#f59e0b" },
  ];

  // TL overview chart data
  const tlChartData = ops.tlList.map((t) => ({
    name: t.name, achPct: t.achPct, color: t.color,
  }));

  // RAG donut data
  const ragData = [
    { name: "Green ≥65%", value: ops.rag.green },
    { name: "Amber 35–64%", value: ops.rag.amber },
    { name: "Red <35%", value: ops.rag.red },
  ];

  // Top WA walkins from store achievements (using walkins as proxy)
  const waTop = [...ops.storeAchievements]
    .filter((s) => s.walkins > 0)
    .sort((a, b) => b.walkins - a.walkins)
    .slice(0, 12)
    .map((s) => ({ name: shortStore(s.store), walkins: s.walkins }));

  return (
    <div>
      {/* KPI Grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(155px, 1fr))", gap: 14, marginBottom: 20 }}>
        {kpis.map((k, i) => (
          <div key={i} style={{
            background: "linear-gradient(135deg, var(--bg-card), var(--bg-card-hover))", border: "1px solid var(--border-subtle)",
            borderRadius: 10, padding: 16, position: "relative", overflow: "hidden",
          }}>
            <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 3, background: k.color }} />
            <div style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6 }}>{k.label}</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: "var(--text-primary)" }}>{k.value}</div>
            <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4 }}>{k.sub}</div>
          </div>
        ))}
      </div>

      {/* Charts Row 1: Store Ach + TL Ach */}
      <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 16, marginBottom: 20 }}>
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 10, padding: 16 }}>
          <h3 style={{ fontSize: 12, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>
            Store MTD Achievement %
          </h3>
          <ResponsiveContainer width="100%" height={400}>
            <BarChart data={ops.storeAchievements} layout="vertical" margin={{ left: 10, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
              <XAxis type="number" domain={[0, 120]} tick={{ fill: "var(--text-muted)", fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
              <YAxis type="category" dataKey="store" tick={{ fill: "var(--text-secondary)", fontSize: 9 }} width={130} tickFormatter={shortStore} />
              <Tooltip formatter={(v: any) => [`${v}%`, "Achievement"]} contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} />
              <Bar dataKey="achPct" radius={[0, 4, 4, 0]}>
                {ops.storeAchievements.map((s, i) => (
                  <Cell key={i} fill={ragColor(s.achPct)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 10, padding: 16 }}>
          <h3 style={{ fontSize: 12, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>
            TL Achievement %
          </h3>
          <ResponsiveContainer width="100%" height={400}>
            <BarChart data={tlChartData} margin={{ left: 0, right: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
              <XAxis dataKey="name" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
              <YAxis domain={[0, 100]} tick={{ fill: "var(--text-muted)", fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
              <Tooltip formatter={(v: any) => [`${v}%`, "Achievement"]} contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} />
              <Bar dataKey="achPct" radius={[6, 6, 0, 0]}>
                {tlChartData.map((t, i) => (
                  <Cell key={i} fill={ragColor(t.achPct)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Charts Row 2: RAG + WA Walkins */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 20 }}>
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 10, padding: 16 }}>
          <h3 style={{ fontSize: 12, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>RAG Status Distribution</h3>
          <ResponsiveContainer width="100%" height={240}>
            <PieChart>
              <Pie data={ragData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} dataKey="value" stroke="var(--bg-card)" strokeWidth={2}>
                {ragData.map((_, i) => (
                  <Cell key={i} fill={["#10b981", "#f59e0b", "#ef4444"][i]} />
                ))}
              </Pie>
              <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} />
              {/* A bare <Legend> next to a single <Pie> doesn't reliably map each
                  slice's color to its label — an explicit payload guarantees the
                  right color swatch next to the right label, with the count included. */}
              <Legend
                wrapperStyle={{ fontSize: 11, color: "var(--text-secondary)" }}
                {...({
                  payload: ragData.map((r, i) => ({ value: `${r.name} (${r.value})`, type: "square", color: ["#10b981", "#f59e0b", "#ef4444"][i] })),
                } as any)}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 10, padding: 16 }}>
          <h3 style={{ fontSize: 12, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>Walk-ins — Top Stores</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={waTop} layout="vertical" margin={{ left: 10, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
              <XAxis type="number" tick={{ fill: "var(--text-muted)", fontSize: 10 }} />
              <YAxis type="category" dataKey="name" tick={{ fill: "var(--text-secondary)", fontSize: 9 }} width={100} />
              <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} />
              <Bar dataKey="walkins" fill="#25d366" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 10, padding: 16 }}>
          <h3 style={{ fontSize: 12, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>TL Target vs Achieved (₹L)</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={ops.tlList.map(t => ({ name: t.name, target: +(t.target / 100000).toFixed(1), achieved: +(t.achieved / 100000).toFixed(1) }))}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
              <XAxis dataKey="name" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
              <YAxis tick={{ fill: "var(--text-muted)", fontSize: 10 }} tickFormatter={(v) => `₹${v}L`} />
              <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} formatter={(v: any) => `₹${v}L`} />
              <Legend wrapperStyle={{ fontSize: 11, color: "var(--text-secondary)" }} />
              <Bar dataKey="target" fill="var(--track)" radius={[4, 4, 0, 0]} />
              <Bar dataKey="achieved" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Strategic Insights */}
      <div style={{ fontSize: 14, fontWeight: 700, color: "var(--tone-blue-fg)", marginBottom: 14, paddingBottom: 6, borderBottom: "1px solid var(--border-subtle)" }}>
        Store Performance Summary
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14 }}>
        {ops.storeAchievements.slice(0, 6).map((sa, i) => (
          <div key={i} style={{
            borderRadius: 10, padding: 16, borderLeft: `4px solid ${ragColor(sa.achPct)}`,
            background: sa.achPct >= 65 ? "var(--tone-green-bg)" : sa.achPct >= 35 ? "var(--tone-amber-bg)" : "var(--tone-red-bg)",
          }}>
            <h4 style={{ fontSize: 12, fontWeight: 700, color: sa.achPct >= 65 ? "var(--tone-green-fg)" : sa.achPct >= 35 ? "var(--tone-amber-fg)" : "var(--tone-red-fg)", marginBottom: 6 }}>
              {sa.store}
            </h4>
            <p style={{ fontSize: 11, color: "var(--text-secondary)", lineHeight: 1.5 }}>
              {sa.achPct}% achieved · {formatINR(sa.mtd)} / {formatINR(sa.target)} · {sa.walkins} walkins · {sa.sales} conversions
            </p>
            <span style={{
              display: "inline-block", marginTop: 4, padding: "3px 8px", borderRadius: 4,
              background: "var(--track)", border: "1px solid var(--border-subtle)", fontSize: 10, color: "var(--tone-blue-fg)",
            }}>
              TL: {sa.tl}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
