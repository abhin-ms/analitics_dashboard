import { useMemo } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { shortStore } from "./types";
import { useSocketRefresh } from "../../hooks/useSocketRefresh";

export function ReviewsTab({ data }: { data: any }) {
  useSocketRefresh(["sheets-data"]);
  const reviews = data?.reviews || [];
  const actionPlan = data?.gr_action_plan || [];

  const validReviews = useMemo(() => {
    return reviews.filter((r: any) => r.store && r.store !== "store" && typeof r.rating === "number");
  }, [reviews]);

  const validPlan = useMemo(() => {
    return actionPlan.filter((r: any) => r.store && r.store !== "Branch" && r.store !== "Branch" && r.current_rating);
  }, [actionPlan]);

  const sorted = useMemo(() => [...validReviews].sort((a: any, b: any) => (b.rating || 0) - (a.rating || 0)), [validReviews]);

  const fiveStar = sorted.find((r: any) => r.rating >= 4.9);
  const mostReviewed = [...sorted].sort((a: any, b: any) => (b.total_reviews || 0) - (a.total_reviews || 0))[0];
  const leastReviewed = [...sorted].filter((r: any) => r.total_reviews > 0).sort((a: any, b: any) => (a.total_reviews || 0) - (b.total_reviews || 0))[0];

  const kpis = [
    { label: "5-Star Store", value: fiveStar ? shortStore(fiveStar.store) : "—", sub: fiveStar ? `${fiveStar.rating} ★ · ${fiveStar.total_reviews} reviews` : "No 5-star stores", color: "#10b981" },
    { label: "Most Reviewed", value: mostReviewed ? shortStore(mostReviewed.store) : "—", sub: mostReviewed ? `${mostReviewed.total_reviews} reviews · ${mostReviewed.rating} ★` : "—", color: "#10b981" },
    { label: "Needs Reviews", value: leastReviewed ? shortStore(leastReviewed.store) : "—", sub: leastReviewed ? `${leastReviewed.rating} ★ but only ${leastReviewed.total_reviews} reviews` : "—", color: "#f59e0b" },
    { label: "Total Stores", value: String(validReviews.length), sub: "with Google ratings", color: "#3b82f6" },
  ];

  const barData = sorted.map((r: any) => ({
    name: shortStore(r.store),
    rating: r.rating,
    reviews: r.total_reviews || 0,
  }));

  return (
    <div>
      <div style={{ background: "var(--tone-lime-bg)", border: "1px solid var(--tone-lime-border)", borderRadius: 6, padding: "10px 14px", fontSize: 11, color: "var(--tone-lime-fg)", marginBottom: 16 }}>
        ✅ All Google rating data sourced live from your Google Sheets tracker.
      </div>

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

      {/* Table */}
      <div style={{ overflowX: "auto", marginBottom: 20 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              {["Store", "Rating", "Total Reviews", "New Reviews", "Rating Bar"].map((h) => (
                <th key={h} style={{ background: "var(--bg-subtle)", color: "var(--text-secondary)", padding: "9px 10px", textAlign: "left", borderBottom: "1px solid var(--border-subtle)", fontSize: 11, textTransform: "uppercase" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((r: any, i: number) => {
              const col = r.rating >= 4.8 ? "var(--tone-green-fg)" : r.rating >= 4.5 ? "var(--tone-blue-fg)" : r.rating >= 4.3 ? "var(--tone-amber-fg)" : "var(--tone-red-fg)";
              return (
                <tr key={i} style={{ borderBottom: "1px solid var(--border-subtle)" }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "var(--border-subtle)")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>
                  <td style={{ padding: "8px 10px", color: "var(--text-primary)", fontWeight: 500 }}>{r.store}</td>
                  <td style={{ padding: "8px 10px", color: col, fontWeight: 700, fontSize: 14 }}>{r.rating} ★</td>
                  <td style={{ padding: "8px 10px", color: "var(--text-primary)" }}>{r.total_reviews || 0}</td>
                  <td style={{ padding: "8px 10px", color: "var(--text-primary)" }}>{r.new_reviews || 0}</td>
                  <td style={{ padding: "8px 10px" }}>
                    <div style={{ width: 120, background: "var(--track)", borderRadius: 4, height: 6, overflow: "hidden" }}>
                      <div style={{ height: "100%", borderRadius: 4, width: `${((r.rating || 0) / 5) * 100}%`, background: col }} />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Charts */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 20 }}>
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 10, padding: 16 }}>
          <h3 style={{ fontSize: 12, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>Google Rating by Store (Sorted)</h3>
          <ResponsiveContainer width="100%" height={400}>
            <BarChart data={barData} layout="vertical" margin={{ left: 10, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
              <XAxis type="number" domain={[3.5, 5.2]} tick={{ fill: "var(--text-muted)", fontSize: 10 }} />
              <YAxis type="category" dataKey="name" tick={{ fill: "var(--text-secondary)", fontSize: 9 }} width={110} />
              <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} />
              <Bar dataKey="rating" radius={[0, 4, 4, 0]}>
                {barData.map((r: any, i: number) => <Cell key={i} fill={r.rating >= 4.8 ? "#10b981" : r.rating >= 4.5 ? "#3b82f6" : r.rating >= 4.3 ? "#f59e0b" : "#ef4444"} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 10, padding: 16 }}>
          <h3 style={{ fontSize: 12, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>Review Count by Store</h3>
          <ResponsiveContainer width="100%" height={400}>
            <BarChart data={barData} layout="vertical" margin={{ left: 10, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
              <XAxis type="number" tick={{ fill: "var(--text-muted)", fontSize: 10 }} />
              <YAxis type="category" dataKey="name" tick={{ fill: "var(--text-secondary)", fontSize: 9 }} width={110} />
              <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} />
              <Bar dataKey="reviews" fill="#8b5cf6" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* GR Action Plan from sheet */}
      {validPlan.length > 0 && (
        <>
          <div style={{ fontSize: 14, fontWeight: 700, color: "var(--tone-blue-fg)", marginBottom: 14, paddingBottom: 6, borderBottom: "1px solid var(--border-subtle)" }}>
            Google Review Action Plans
          </div>
          <div style={{ overflowX: "auto", marginBottom: 20 }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr>
                  {["Store", "Tier", "Rating", "Current Reviews", "Needed", "Weekly Target", "Timeline"].map((h) => (
                    <th key={h} style={{ background: "var(--bg-subtle)", color: "var(--text-secondary)", padding: "9px 10px", textAlign: "left", borderBottom: "1px solid var(--border-subtle)", fontSize: 11, textTransform: "uppercase", whiteSpace: "nowrap" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {validPlan.map((r: any, i: number) => (
                  <tr key={i} style={{ borderBottom: "1px solid var(--border-subtle)" }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--border-subtle)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>
                    <td style={{ padding: "8px 10px", color: "var(--text-primary)", fontWeight: 500 }}>{r.store}</td>
                    <td style={{ padding: "8px 10px" }}>
                      <span style={{
                        padding: "2px 8px", borderRadius: 12, fontSize: 10, fontWeight: 700,
                        background: r.tier === "Star" ? "var(--tone-green-bg)" : r.tier === "Good" ? "var(--tone-blue-bg)" : "var(--tone-amber-bg)",
                        color: r.tier === "Star" ? "var(--tone-green-fg)" : r.tier === "Good" ? "var(--tone-blue-fg)" : "var(--tone-amber-fg)",
                      }}>
                        {r.tier}
                      </span>
                    </td>
                    <td style={{ padding: "8px 10px", color: "var(--text-primary)", fontWeight: 700 }}>{r.current_rating}</td>
                    <td style={{ padding: "8px 10px", color: "var(--text-primary)", textAlign: "center" }}>{r.current_reviews}</td>
                    <td style={{ padding: "8px 10px", color: "var(--text-primary)", textAlign: "center" }}>{r.reviews_needed}</td>
                    <td style={{ padding: "8px 10px", color: "var(--text-primary)", textAlign: "center" }}>{r.weekly_target}</td>
                    <td style={{ padding: "8px 10px", color: "var(--text-primary)" }}>{r.timeline}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
