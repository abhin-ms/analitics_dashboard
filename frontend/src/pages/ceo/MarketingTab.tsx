import { useMemo } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, Legend } from "recharts";
import { shortStore } from "./types";
import { useSocketRefresh } from "../../hooks/useSocketRefresh";

function fmtNum(n: number) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return String(n);
}

export function MarketingTab({ data }: { data: any }) {
  useSocketRefresh(["sheets-data"]);
  const dailyTracker = data?.daily_tracker || [];
  const storeDashboard = data?.store_dashboard || [];

  const storeAgg = useMemo(() => {
    // dailyTracker rows are ordered by date desc, so the first row seen per
    // store is its latest snapshot — mtd_revenue is already a cumulative
    // running total as of that date, so it must be read once, never summed.
    const map: Record<string, any> = {};
    for (const r of dailyTracker) {
      const s = r.store;
      if (!s) continue;
      if (!map[s]) {
        map[s] = {
          store: s, country: r.country, storeType: r.store_type,
          dailyRevenue: 0, mtdRevenue: r.mtd_revenue || 0, monthlyTarget: r.monthly_target || 0, unitsSold: 0, carePlus: 0, prebookings: 0,
          igVideos: 0, igViewsTarget: 0, igViewsAchieved: 0, igFollowers: 0, igNewFollowers: 0,
          igLikes: 0, igComments: 0, igSaves: 0, igShares: 0, igDms: 0, igManychat: 0, igPosts: 0,
          ytViews: 0, ytLikes: 0, ytComments: 0,
          ttViews: 0, ttLikes: 0, ttFollowers: 0,
          scViews: 0, scShares: 0,
          waChats: 0, waWalkins: 0,
          googleRating: null as number | null, googleReviews: 0, googleResponse: "",
        };
      }
      const m = map[s];
      m.dailyRevenue += r.daily_revenue || 0;
      m.unitsSold += r.units_sold || 0;
      m.carePlus += r.care_plus_attached || 0;
      m.prebookings += r.prebookings || 0;
      m.igVideos += r.ig_videos_posted || 0;
      m.igViewsTarget += r.ig_views_target || 0;
      m.igViewsAchieved += r.ig_views_achieved || 0;
      m.igFollowers = r.ig_followers || m.igFollowers;
      m.igNewFollowers += r.ig_new_followers || 0;
      m.igLikes += r.ig_likes || 0;
      m.igComments += r.ig_comments || 0;
      m.igSaves += r.ig_saves || 0;
      m.igShares += r.ig_shares || 0;
      m.igDms += r.ig_dms_received || 0;
      m.igManychat += r.ig_manychat_handled || 0;
      m.igPosts += r.ig_posts_published || 0;
      m.ytViews += r.yt_views || 0;
      m.ytLikes += r.yt_likes || 0;
      m.ytComments += r.yt_comments || 0;
      m.ttViews += r.tt_views || 0;
      m.ttLikes += r.tt_likes || 0;
      m.ttFollowers = r.tt_followers || m.ttFollowers;
      m.scViews += r.sc_views || 0;
      m.scShares += r.sc_shares || 0;
      m.waChats += r.wa_chats_received || 0;
      m.waWalkins += r.wa_walkins_booked || 0;
      if (r.google_rating) m.googleRating = r.google_rating;
      m.googleReviews += r.google_new_reviews || 0;
      if (r.google_review_response) m.googleResponse = r.google_review_response;
    }
    return Object.values(map);
  }, [dailyTracker]);

  const dashMap = useMemo(() => {
    const m: Record<string, any> = {};
    for (const r of storeDashboard) {
      m[r.store] = r;
    }
    return m;
  }, [storeDashboard]);

  const totals = useMemo(() => {
    return storeAgg.reduce(
      (acc, s) => ({
        mtdRevenue: acc.mtdRevenue + s.mtdRevenue,
        monthlyTarget: acc.monthlyTarget + s.monthlyTarget,
        totalViews: acc.totalViews + s.igViewsAchieved + s.ytViews + s.ttViews + s.scViews,
        totalEngagements: acc.totalEngagements + s.igLikes + s.igComments + s.igSaves + s.igShares + s.ytLikes + s.ttLikes,
        totalDms: acc.totalDms + s.igDms,
        totalWaChats: acc.totalWaChats + s.waChats,
        totalWaWalkins: acc.totalWaWalkins + s.waWalkins,
        totalPrebookings: acc.totalPrebookings + s.prebookings,
        totalIgFollowers: acc.totalIgFollowers + s.igFollowers,
        totalGoogleReviews: acc.totalGoogleReviews + s.googleReviews,
      }),
      { mtdRevenue: 0, monthlyTarget: 0, totalViews: 0, totalEngagements: 0, totalDms: 0, totalWaChats: 0, totalWaWalkins: 0, totalPrebookings: 0, totalIgFollowers: 0, totalGoogleReviews: 0 }
    );
  }, [storeAgg]);

  const kpis = [
    { label: "MTD Revenue", value: `₹${fmtNum(totals.mtdRevenue)}`, sub: `of ₹${fmtNum(totals.monthlyTarget)} target`, color: "#3b82f6" },
    { label: "Total Reach", value: fmtNum(totals.totalViews), sub: "IG + YT + TT + SC views", color: "#10b981" },
    { label: "Total Engagements", value: fmtNum(totals.totalEngagements), sub: "likes + comments + saves", color: "#a855f7" },
    { label: "IG Followers", value: fmtNum(totals.totalIgFollowers), sub: "across all stores", color: "#ec4899" },
    { label: "WA Chats", value: fmtNum(totals.totalWaChats), sub: `${totals.totalWaWalkins} walkins booked`, color: "#25d366" },
    { label: "Prebookings", value: String(totals.totalPrebookings), sub: "₹99 paid intent", color: "#f97316" },
    { label: "Google Reviews", value: fmtNum(totals.totalGoogleReviews), sub: "new this period", color: "#f59e0b" },
    { label: "Stores Tracked", value: String(storeAgg.length), sub: "from xlsx tracker", color: "#06b6d4" },
  ];

  const igBarData = storeAgg
    .filter((s) => s.igViewsAchieved > 0)
    .sort((a, b) => b.igViewsAchieved - a.igViewsAchieved)
    .slice(0, 15)
    .map((s) => ({ name: shortStore(s.store), views: s.igViewsAchieved, target: s.igViewsTarget, likes: s.igLikes }));

  const waBarData = storeAgg
    .filter((s) => s.waWalkins > 0 || s.waChats > 0)
    .sort((a, b) => b.waWalkins - a.waWalkins)
    .slice(0, 15)
    .map((s) => ({ name: shortStore(s.store), chats: s.waChats, walkins: s.waWalkins }));

  const platformData = useMemo(() => {
    const totalIG = storeAgg.reduce((s, r) => s + r.igViewsAchieved, 0);
    const totalYT = storeAgg.reduce((s, r) => s + r.ytViews, 0);
    const totalTT = storeAgg.reduce((s, r) => s + r.ttViews, 0);
    const totalSC = storeAgg.reduce((s, r) => s + r.scViews, 0);
    return [
      { name: "Instagram", value: totalIG, color: "#E1306C" },
      { name: "YouTube", value: totalYT, color: "#FF0000" },
      { name: "TikTok", value: totalTT, color: "#00f2ea" },
      { name: "Snapchat", value: totalSC, color: "#FFFC00" },
    ].filter((p) => p.value > 0);
  }, [storeAgg]);

  return (
    <div>
      <div style={{ background: "var(--tone-lime-bg)", border: "1px solid var(--tone-lime-border)", borderRadius: 6, padding: "10px 14px", fontSize: 11, color: "var(--tone-lime-fg)", marginBottom: 16 }}>
        All data sourced from BP Daily Tracker (xlsx) — synced every 1 min. Includes Instagram, YouTube, TikTok, Snapchat, WhatsApp, and Google Reviews.
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

      {/* Full Marketing Table */}
      <div style={{ overflowX: "auto", marginBottom: 20 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              {["#", "Store", "Ctry", "MTD Rev", "Target%", "IG Views", "IG Likes", "IG Followers", "YT Views", "TT Views", "WA Chats", "WA Walkins", "Google ★", "Reviews", "Status"].map((h) => (
                <th key={h} style={{ background: "var(--bg-subtle)", color: "var(--text-secondary)", padding: "9px 8px", textAlign: "left", borderBottom: "1px solid var(--border-subtle)", fontSize: 10, textTransform: "uppercase", whiteSpace: "nowrap" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {storeAgg
              .sort((a, b) => b.mtdRevenue - a.mtdRevenue)
              .map((s, i) => {
                const tgtPct = s.monthlyTarget > 0 ? Math.round((s.mtdRevenue / s.monthlyTarget) * 100) : 0;
                const dash = dashMap[s.store] || {};
                const salesStatus = dash.sales_status || "";
                return (
                  <tr key={i} style={{ borderBottom: "1px solid var(--border-subtle)" }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--border-subtle)")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>
                    <td style={{ padding: "7px 8px", color: "var(--text-primary)", textAlign: "center" }}>{i + 1}</td>
                    <td style={{ padding: "7px 8px", color: "var(--text-primary)", fontWeight: 500, maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.store}</td>
                    <td style={{ padding: "7px 8px", color: "var(--text-primary)" }}>{s.country}</td>
                    <td style={{ padding: "7px 8px", color: "#3b82f6", fontWeight: 700, textAlign: "right" }}>₹{fmtNum(s.mtdRevenue)}</td>
                    <td style={{ padding: "7px 8px", color: tgtPct >= 65 ? "#10b981" : tgtPct >= 35 ? "#f59e0b" : "#ef4444", fontWeight: 700, textAlign: "right" }}>{tgtPct}%</td>
                    <td style={{ padding: "7px 8px", color: "#E1306C", textAlign: "right" }}>{fmtNum(s.igViewsAchieved)}</td>
                    <td style={{ padding: "7px 8px", color: "var(--text-primary)", textAlign: "right" }}>{fmtNum(s.igLikes)}</td>
                    <td style={{ padding: "7px 8px", color: "#ec4899", textAlign: "right" }}>{fmtNum(s.igFollowers)}</td>
                    <td style={{ padding: "7px 8px", color: "#FF0000", textAlign: "right" }}>{fmtNum(s.ytViews)}</td>
                    <td style={{ padding: "7px 8px", color: "#00f2ea", textAlign: "right" }}>{fmtNum(s.ttViews)}</td>
                    <td style={{ padding: "7px 8px", color: "#25d366", textAlign: "right" }}>{s.waChats}</td>
                    <td style={{ padding: "7px 8px", color: "#25d366", fontWeight: 700, textAlign: "right" }}>{s.waWalkins}</td>
                    <td style={{ padding: "7px 8px", color: s.googleRating ? (s.googleRating >= 4.5 ? "var(--tone-green-fg)" : s.googleRating >= 4.0 ? "var(--tone-amber-fg)" : "var(--tone-red-fg)") : "var(--track)", fontWeight: 700, textAlign: "right" }}>
                      {s.googleRating ? `${s.googleRating} ★` : "—"}
                    </td>
                    <td style={{ padding: "7px 8px", color: "var(--text-primary)", textAlign: "right" }}>{s.googleReviews || "—"}</td>
                    <td style={{ padding: "7px 8px", textAlign: "center" }}>
                      <span style={{ fontSize: 11 }}>{salesStatus}</span>
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
          <h3 style={{ fontSize: 12, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>Instagram Views — Top Stores</h3>
          <ResponsiveContainer width="100%" height={350}>
            <BarChart data={igBarData} layout="vertical" margin={{ left: 10, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
              <XAxis type="number" tick={{ fill: "var(--text-muted)", fontSize: 10 }} />
              <YAxis type="category" dataKey="name" tick={{ fill: "var(--text-secondary)", fontSize: 9 }} width={100} />
              <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} />
              <Legend wrapperStyle={{ fontSize: 11, color: "var(--text-secondary)" }} />
              <Bar dataKey="views" fill="#E1306C" radius={[0, 4, 4, 0]} />
              <Bar dataKey="likes" fill="#a855f7" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 10, padding: 16 }}>
          <h3 style={{ fontSize: 12, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>WhatsApp Funnel — Top Stores</h3>
          <ResponsiveContainer width="100%" height={350}>
            <BarChart data={waBarData} layout="vertical" margin={{ left: 10, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
              <XAxis type="number" tick={{ fill: "var(--text-muted)", fontSize: 10 }} />
              <YAxis type="category" dataKey="name" tick={{ fill: "var(--text-secondary)", fontSize: 9 }} width={100} />
              <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} />
              <Legend wrapperStyle={{ fontSize: 11, color: "var(--text-secondary)" }} />
              <Bar dataKey="chats" fill="#25d366" radius={[0, 4, 4, 0]} />
              <Bar dataKey="walkins" fill="#3b82f6" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Platform breakdown */}
      {platformData.length > 0 && (
        <div style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)", borderRadius: 10, padding: 16 }}>
          <h3 style={{ fontSize: 12, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 12 }}>Platform Reach Breakdown</h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={platformData} margin={{ left: 20, right: 20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
              <XAxis dataKey="name" tick={{ fill: "var(--text-secondary)", fontSize: 11 }} />
              <YAxis tick={{ fill: "var(--text-muted)", fontSize: 10 }} />
              <Tooltip contentStyle={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }} labelStyle={{ color: "var(--text-primary)" }} itemStyle={{ color: "var(--text-primary)" }} />
              <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                {platformData.map((p, i) => <Cell key={i} fill={p.color} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
