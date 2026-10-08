import { useMemo } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, Legend } from "recharts";
import { processMcpOpsData, pct, ragColor, formatINR, formatNum, shortStore } from "./types";
import { useMcpOpsReport } from "./useMcpOpsReport";
import { useSocketRefresh } from "../../hooks/useSocketRefresh";

export function TLWiseTab({ data }: { data: any }) {
  useSocketRefresh(["sheets-data"]);
  const { branchBreakdown, tlBreakdown } = useMcpOpsReport();
  const ops = useMemo(() => processMcpOpsData(branchBreakdown, tlBreakdown), [branchBreakdown, tlBreakdown]);

  if (!ops) {
    return <div style={{ padding: 40, textAlign: "center", color: "var(--text-secondary)" }}>No operations data available</div>;
  }

  const kpis = [
    { label: "India Grand Total", value: formatINR(ops.totalRevenue), sub: `vs ${formatINR(ops.totalTarget)} · ${ops.overallAch}%`, color: "#3b82f6" },
    { label: "Total Walk-ins", value: formatNum(ops.totalWalkins), sub: `${formatNum(ops.totalConversions)} conversions`, color: "#10b981" },
    { label: "Overall Conv%", value: `${ops.overallConv}%`, sub: "India average", color: "#f59e0b" },
    { label: "Best TL", value: ops.tlList[0]?.name || "—", sub: `${ops.tlList[0]?.achPct || 0}% · ${ops.tlList[0]?.stores.length || 0} stores`, color: "#8b5cf6" },
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

      {/* TL Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14, marginBottom: 20 }}>
        {ops.tlList.map((tl, i) => {
          const p = tl.achPct;
          return (
            <div key={i} style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 10, padding: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <span style={{ fontSize: 15, fontWeight: 700, color: "var(--text-primary)" }}>{tl.name}</span>
                <span style={{ fontSize: 22, fontWeight: 800, color: tl.color }}>{p}%</span>
              </div>
              <div style={{ fontSize: 11, color: "var(--text-secondary)", display: "flex", gap: 14, flexWrap: "wrap", marginBottom: 8 }}>
                <span>🎯 {formatINR(tl.target)} target</span>
                <span>✅ {formatINR(tl.achieved)} achieved</span>
                <span>👣 {tl.walkins} walkins</span>
                <span>🤝 {tl.conv} conv ({tl.convPct}%)</span>
              </div>
              <div style={{ width: "100%", background: "var(--track)", borderRadius: 4, height: 8, overflow: "hidden", marginBottom: 10 }}>
                <div style={{ height: "100%", borderRadius: 4, width: `${Math.min(p, 100)}%`, background: tl.color }} />
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)" }}>Stores: <span style={{ color: "var(--text-secondary)" }}>{tl.stores.map((s: any) => s.s).join(", ")}</span></div>
            </div>
          );
        })}
      </div>

      {/* Charts */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 20 }}>
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 10, padding: 16 }}>
          <h3 style={{ fontSize: 12, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>TL Target vs Achieved (₹ Lakhs)</h3>
          <ResponsiveContainer width="100%" height={280}>
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

        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 10, padding: 16 }}>
          <h3 style={{ fontSize: 12, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>TL Conversion Rate (%)</h3>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={ops.tlList.map(t => ({ name: t.name, convPct: t.convPct }))}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
              <XAxis dataKey="name" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
              <YAxis domain={[0, 100]} tick={{ fill: "var(--text-muted)", fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
              <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} formatter={(v: any) => `${v}%`} />
              <Bar dataKey="convPct" radius={[6, 6, 0, 0]}>
                {ops.tlList.map((t, i) => <Cell key={i} fill={ragColor(t.convPct)} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Store Drill-down Table */}
      <div style={{ fontSize: 14, fontWeight: 700, color: "var(--tone-blue-fg)", marginBottom: 14, paddingBottom: 6, borderBottom: "1px solid var(--border-subtle)" }}>Store Drill-down by TL</div>
      <div style={{ overflowX: "auto", marginBottom: 20 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              {["TL", "Store", "Target (₹)", "Achieved (₹)", "Ach%", "Walk-ins", "Conv", "Conv%", "Status"].map((h) => (
                <th key={h} style={{ background: "var(--bg-subtle)", color: "var(--text-secondary)", padding: "9px 10px", textAlign: "left", borderBottom: "1px solid var(--border-subtle)", fontSize: 11, textTransform: "uppercase" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ops.tlList.map((tl: any) =>
              tl.stores.map((s: any, j: number) => {
                const p = pct(s.a, s.t);
                return (
                  <tr key={`${tl.name}-${j}`} style={{ borderBottom: "1px solid var(--border-subtle)" }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--border-subtle)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>
                    <td style={{ padding: "8px 10px", fontWeight: 600, color: "var(--text-primary)" }}>{j === 0 ? tl.name : ""}</td>
                    <td style={{ padding: "8px 10px", color: "var(--text-primary)" }}>{s.s}</td>
                    <td style={{ padding: "8px 10px", color: "var(--text-primary)", textAlign: "right" }}>{s.t.toLocaleString("en-IN")}</td>
                    <td style={{ padding: "8px 10px", color: "var(--text-primary)", textAlign: "right" }}>{s.a.toLocaleString("en-IN")}</td>
                    <td style={{ padding: "8px 10px", textAlign: "left" }}>
                      <div style={{ width: "100%", background: "var(--track)", borderRadius: 4, height: 6, overflow: "hidden", marginBottom: 2 }}>
                        <div style={{ height: "100%", borderRadius: 4, width: `${Math.min(p, 100)}%`, background: ragColor(p) }} />
                      </div>
                      <span style={{ fontSize: 10, color: "var(--text-secondary)" }}>{p}%</span>
                    </td>
                    <td style={{ padding: "8px 10px", color: "var(--text-primary)", textAlign: "center" }}>{s.wi || "—"}</td>
                    <td style={{ padding: "8px 10px", color: "var(--text-primary)", textAlign: "center" }}>{s.cv || "—"}</td>
                    <td style={{ padding: "8px 10px", color: "var(--text-primary)", textAlign: "center" }}>{s.cp > 0 ? `${s.cp}%` : "—"}</td>
                    <td style={{ padding: "8px 10px" }}>
                      <span style={{ padding: "2px 8px", borderRadius: 12, fontSize: 10, fontWeight: 700, background: p >= 65 ? "var(--tone-green-bg)" : p >= 35 ? "var(--tone-amber-bg)" : p > 0 ? "var(--tone-red-bg)" : "var(--track)", color: p >= 65 ? "var(--tone-green-fg)" : p >= 35 ? "var(--tone-amber-fg)" : p > 0 ? "var(--tone-red-fg)" : "var(--text-muted)" }}>
                        {p >= 65 ? "✅ Green" : p >= 35 ? "⚡ Amber" : p > 0 ? "🔴 Red" : "⚫ None"}
                      </span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
