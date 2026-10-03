import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";

/** One store's social + reputation figures for a month, built from the
 * "Daily Input" rows of the BP Store Daily Tracker sheet. */
export interface SocialStore {
  store: string;
  country: string;
  videos: number;
  viewsTarget: number;
  views: number;
  /** Views as % of target; null when the store reported no social data. */
  viewsPct: number | null;
  followers: number;
  newFollowers: number;
  likes: number;
  comments: number;
  saves: number;
  shares: number;
  reposts: number;
  engagement: number;
  dms: number;
  manychat: number;
  posts: number;
  ytViews: number;
  ttViews: number;
  scViews: number;
  waChats: number;
  walkins: number;
  rating: number | null;
  reviews: number;
  /** "Yes" | "Partial" | "No" | "" */
  replied: string;
  hasSocial: boolean;
}

export type Status = "good" | "warn" | "crit" | "none";

export const STATUS_COLOR: Record<Status, string> = {
  good: "#0ca30c",
  warn: "#fab219",
  crit: "#d03b3b",
  none: "var(--border-subtle)",
};
export const STATUS_ICON: Record<Status, string> = { good: "✓", warn: "!", crit: "✕", none: "–" };
export const STATUS_LABEL: Record<Status, string> = { good: "On track", warn: "At risk", crit: "Critical", none: "No data" };

export const COUNTRY_LABEL: Record<string, string> = {
  IN: "India", ABD: "Abu Dhabi", DXB: "Dubai", OMN: "Oman",
  MLY: "Malaysia", UK: "UK", BAH: "Bahrain", QAT: "Qatar",
};

// Thresholds from the tracker sheet's own colour guide.
export const VIEWS_GOOD = 90;
export const VIEWS_WARN = 65;
export const RATING_GOOD = 4.8;
export const RATING_WARN = 4.5;

export function viewsStatus(pct: number | null): Status {
  if (pct === null) return "none";
  return pct >= VIEWS_GOOD ? "good" : pct >= VIEWS_WARN ? "warn" : "crit";
}
export function ratingStatus(r: number | null): Status {
  if (r === null) return "none";
  return r >= RATING_GOOD ? "good" : r >= RATING_WARN ? "warn" : "crit";
}
export function repliedStatus(r: string): Status {
  if (r === "Yes") return "good";
  if (r === "Partial") return "warn";
  if (r === "No") return "crit";
  return "none";
}

const RANK: Record<Status, number> = { crit: 3, warn: 2, good: 1, none: 0 };

/** A store's overall status is its worst signal among video views, Google
 * rating and review replies — whichever it actually reports. */
export function overallStatus(s: SocialStore): Status {
  const parts = [viewsStatus(s.viewsPct), ratingStatus(s.rating), repliedStatus(s.replied)];
  return parts.reduce<Status>((worst, p) => (RANK[p] > RANK[worst] ? p : worst), "none");
}
export function statusRank(s: Status) {
  return RANK[s];
}

/** Plain-language reasons a store needs attention, worst first. */
export function attentionReasons(s: SocialStore): string[] {
  const out: string[] = [];
  if (viewsStatus(s.viewsPct) === "crit") out.push(`Video views ${Math.round(s.viewsPct!)}% of target`);
  if (ratingStatus(s.rating) === "crit") out.push(`Google rating ${s.rating!.toFixed(1)} ★`);
  if (repliedStatus(s.replied) === "crit") out.push("Not replying to reviews");
  if (viewsStatus(s.viewsPct) === "warn") out.push(`Video views ${Math.round(s.viewsPct!)}% of target`);
  if (ratingStatus(s.rating) === "warn") out.push(`Google rating ${s.rating!.toFixed(1)} ★`);
  if (repliedStatus(s.replied) === "warn") out.push("Replying to some reviews only");
  return out;
}

export function fmtCompact(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n >= 1e7) return `${(n / 1e7).toFixed(1)} Cr`;
  if (n >= 1e5) return `${(n / 1e5).toFixed(1)} L`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return String(Math.round(n));
}

export function monthLabel(m: string) {
  const [y, mo] = m.split("-").map(Number);
  return new Date(y, mo - 1, 1).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
}

const n = (v: unknown) => (typeof v === "number" && isFinite(v) ? v : 0);

/** Collapse tracker rows (newest first) into one record per store. Flow
 * figures (views, likes, DMs, reviews…) are summed across the month's rows;
 * point-in-time figures (followers, rating, reply status, views target) come
 * from the store's latest row — so this works whether the sheet holds one
 * row per day or one summary row per month. */
export function buildStores(rows: any[]): SocialStore[] {
  const map = new Map<string, SocialStore>();
  for (const r of rows) {
    const name = (r.store || "").trim();
    if (!name) continue;
    let s = map.get(name);
    if (!s) {
      s = {
        store: name, country: r.country || "",
        videos: 0, viewsTarget: n(r.ig_views_target), views: 0, viewsPct: null,
        followers: n(r.ig_followers), newFollowers: 0,
        likes: 0, comments: 0, saves: 0, shares: 0, reposts: 0, engagement: 0,
        dms: 0, manychat: 0, posts: 0, ytViews: 0, ttViews: 0, scViews: 0,
        waChats: 0, walkins: 0,
        rating: typeof r.google_rating === "number" && r.google_rating > 0 ? r.google_rating : null,
        reviews: 0, replied: (r.google_review_response || "").trim(), hasSocial: false,
      };
      map.set(name, s);
    }
    s.videos += n(r.ig_videos_posted);
    s.views += n(r.ig_views_achieved);
    s.newFollowers += n(r.ig_new_followers);
    s.likes += n(r.ig_likes);
    s.comments += n(r.ig_comments);
    s.saves += n(r.ig_saves);
    s.shares += n(r.ig_shares);
    s.reposts += n(r.ig_reposts);
    s.dms += n(r.ig_dms_received);
    s.manychat += n(r.ig_manychat_handled);
    s.posts += n(r.ig_posts_published);
    s.ytViews += n(r.yt_views);
    s.ttViews += n(r.tt_views);
    s.scViews += n(r.sc_views);
    s.waChats += n(r.wa_chats_received);
    s.walkins += n(r.wa_walkins_booked);
    s.reviews += n(r.google_new_reviews);
  }
  for (const s of map.values()) {
    s.engagement = s.likes + s.comments + s.saves + s.shares + s.reposts;
    s.hasSocial = s.videos > 0 || s.views > 0 || s.followers > 0 || s.posts > 0;
    s.viewsPct = s.hasSocial && s.viewsTarget > 0 ? (s.views / s.viewsTarget) * 100 : null;
  }
  return [...map.values()];
}

export interface SocialTotals {
  stores: number;
  socialStores: number;
  views: number;
  viewsTarget: number;
  videos: number;
  storesPosted: number;
  followers: number;
  newFollowers: number;
  engagement: number;
  dms: number;
  manychat: number;
  waChats: number;
  walkins: number;
  avgRating: number | null;
  ratedStores: number;
  ratingGood: number;
  ratingCrit: number;
  reviews: number;
  repliedAll: number;
  statusCounts: Record<Status, number>;
}

export function totalsOf(stores: SocialStore[]): SocialTotals {
  const social = stores.filter((s) => s.hasSocial);
  const rated = stores.filter((s) => s.rating !== null);
  const sum = (a: SocialStore[], f: (s: SocialStore) => number) => a.reduce((t, s) => t + f(s), 0);
  const statusCounts: Record<Status, number> = { good: 0, warn: 0, crit: 0, none: 0 };
  stores.forEach((s) => statusCounts[overallStatus(s)]++);
  return {
    stores: stores.length,
    socialStores: social.length,
    views: sum(social, (s) => s.views),
    viewsTarget: sum(social, (s) => s.viewsTarget),
    videos: sum(social, (s) => s.videos),
    storesPosted: social.filter((s) => s.videos > 0).length,
    followers: sum(social, (s) => s.followers),
    newFollowers: sum(social, (s) => s.newFollowers),
    engagement: sum(social, (s) => s.engagement),
    dms: sum(social, (s) => s.dms),
    manychat: sum(social, (s) => s.manychat),
    waChats: sum(stores, (s) => s.waChats),
    walkins: sum(stores, (s) => s.walkins),
    avgRating: rated.length ? sum(rated, (s) => s.rating!) / rated.length : null,
    ratedStores: rated.length,
    ratingGood: rated.filter((s) => s.rating! >= RATING_GOOD).length,
    ratingCrit: rated.filter((s) => s.rating! < RATING_WARN).length,
    reviews: sum(rated, (s) => s.reviews),
    repliedAll: rated.filter((s) => s.replied === "Yes").length,
    statusCounts,
  };
}

async function getJson(path: string) {
  const res = await api.fetchRaw(path);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** Months with tracker data plus the chosen month's per-store figures. With
 * no month given it opens on the latest month that has data. Query keys sit
 * under "sheets-data" so the sheet-sync socket refresh reloads them. */
export function useSocialPerformance(month?: string) {
  const monthsQ = useQuery({
    queryKey: ["sheets-data", "tracker-months"],
    queryFn: async () => ((await getJson("/ceo-dashboard/sheets-data?tab=tracker_months")).months || []) as string[],
  });
  const months = monthsQ.data || [];
  const active = month || months[0];
  const rowsQ = useQuery({
    queryKey: ["sheets-data", "social", active],
    enabled: !!active,
    queryFn: async () => (await getJson(`/ceo-dashboard/sheets-data?tab=daily_tracker&month=${active}`)).daily_tracker || [],
  });
  return {
    months,
    month: active,
    stores: rowsQ.data ? buildStores(rowsQ.data) : [],
    isLoading: monthsQ.isLoading || (!!active && rowsQ.isLoading),
    error: monthsQ.error || rowsQ.error,
    empty: monthsQ.isSuccess && months.length === 0,
  };
}
