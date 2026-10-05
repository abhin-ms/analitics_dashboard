import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/apiClient";

/** Platforms with a monthly views target, set per store by an admin. */
export type Platform = "instagram" | "youtube" | "facebook";
export const PLATFORMS: Platform[] = ["instagram", "youtube", "facebook"];
export const PLATFORM_LABEL: Record<Platform, string> = { instagram: "Instagram", youtube: "YouTube", facebook: "Facebook" };
export const PLATFORM_COLOR: Record<Platform, string> = { instagram: "#E1306C", youtube: "#FF0000", facebook: "#1877F2" };

export interface PlatformViews {
  views: number;
  target: number;
  /** Views as % of target; null when the store hasn't reported this platform. */
  pct: number | null;
  hasData: boolean;
}

/** One store's social + reputation figures for a month, built from the
 * "Daily Input" rows of the BP Store Daily Tracker sheet. */
export interface SocialStore {
  storeId: number;
  store: string;
  country: string;
  teamLeader: string;
  platforms: Record<Platform, PlatformViews>;
  videos: number;
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
  waChats: number;
  walkins: number;
  rating: number | null;
  reviews: number;
  /** "Yes" | "Partial" | "No" | "" */
  replied: string;
  /** Any Instagram activity reported this month. */
  hasSocial: boolean;
  /** When this store's row last changed in the sheet (any month), ISO. */
  lastUpdatedAt: string | null;
  /** Latest period the store has filled ("2026-08-31"). */
  lastPeriod: string | null;
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
// Store managers are asked to fill the sheet daily.
export const FRESH_DAYS = 1;
export const STALE_DAYS = 3;

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
/** How recently the store updated the sheet. */
export function freshnessStatus(iso: string | null): Status {
  if (!iso) return "none";
  const days = (Date.now() - new Date(iso).getTime()) / 86_400_000;
  return days <= FRESH_DAYS ? "good" : days <= STALE_DAYS ? "warn" : "crit";
}

const RANK: Record<Status, number> = { crit: 3, warn: 2, good: 1, none: 0 };

/** A store's overall status is its worst signal among views on each platform
 * it reports, Google rating and review replies. */
export function overallStatus(s: SocialStore): Status {
  const parts = [
    ...PLATFORMS.map((p) => viewsStatus(s.platforms[p].pct)),
    ratingStatus(s.rating),
    repliedStatus(s.replied),
  ];
  return parts.reduce<Status>((worst, p) => (RANK[p] > RANK[worst] ? p : worst), "none");
}
export function statusRank(s: Status) {
  return RANK[s];
}

/** Plain-language reasons a store needs attention, worst first. */
export function attentionReasons(s: SocialStore): string[] {
  const out: string[] = [];
  for (const level of ["crit", "warn"] as Status[]) {
    for (const p of PLATFORMS) {
      const pv = s.platforms[p];
      if (viewsStatus(pv.pct) === level) out.push(`${PLATFORM_LABEL[p]} views ${Math.round(pv.pct!)}% of target`);
    }
    if (ratingStatus(s.rating) === level) out.push(`Google rating ${s.rating!.toFixed(1)} ★`);
    if (repliedStatus(s.replied) === level) out.push(level === "crit" ? "Not replying to reviews" : "Replying to some reviews only");
  }
  return out;
}

export function fmtCompact(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (n >= 1e7) return `${+(n / 1e7).toFixed(2)} Cr`;
  if (n >= 1e5) return `${+(n / 1e5).toFixed(1)} L`;
  if (n >= 1e3) return `${+(n / 1e3).toFixed(1)}K`;
  return String(Math.round(n));
}

export function monthLabel(m: string) {
  const [y, mo] = m.split("-").map(Number);
  return new Date(y, mo - 1, 1).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
}

export function fmtDateTime(iso: string | null) {
  if (!iso) return "Never";
  return new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
}

export function fmtPeriod(d: string | null) {
  if (!d) return "—";
  return new Date(`${d}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function timeAgo(iso: string | null) {
  if (!iso) return "never";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  const days = Math.round(hrs / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

const n = (v: unknown) => (typeof v === "number" && isFinite(v) ? v : 0);

interface ApiStore {
  store_id: number;
  store: string;
  country: string;
  team_leader: string;
  targets: Record<Platform, number>;
  last_updated_at: string | null;
  last_period: string | null;
}

/** One record per store in scope (including stores with no rows this
 * month). Flow figures (views, likes, DMs, reviews…) are summed across the
 * month's rows; point-in-time figures (followers, rating, reply status) come
 * from the store's latest row — so this works whether the sheet holds one
 * row per day or one summary row per month. */
export function buildStores(apiStores: ApiStore[], rows: any[]): SocialStore[] {
  const stores = new Map<number, SocialStore>();
  const views = new Map<number, Record<Platform, number>>();
  for (const a of apiStores) {
    stores.set(a.store_id, {
      storeId: a.store_id, store: a.store, country: a.country || "", teamLeader: a.team_leader || "",
      platforms: {} as Record<Platform, PlatformViews>,
      videos: 0, followers: 0, newFollowers: 0, likes: 0, comments: 0, saves: 0, shares: 0, reposts: 0,
      engagement: 0, dms: 0, manychat: 0, posts: 0, waChats: 0, walkins: 0,
      rating: null, reviews: 0, replied: "", hasSocial: false,
      lastUpdatedAt: a.last_updated_at, lastPeriod: a.last_period,
    });
  }
  for (const r of rows) {
    const s = stores.get(r.store_id);
    if (!s) continue;
    let v = views.get(r.store_id);
    if (!v) {
      // Rows arrive newest first: the first one per store is its latest snapshot.
      v = { instagram: 0, youtube: 0, facebook: 0 };
      views.set(r.store_id, v);
      s.followers = n(r.ig_followers);
      s.rating = typeof r.google_rating === "number" && r.google_rating > 0 ? r.google_rating : null;
      s.replied = (r.google_review_response || "").trim();
      if (r.country) s.country = r.country;
    }
    v.instagram += n(r.ig_views_achieved);
    v.youtube += n(r.yt_views);
    v.facebook += n(r.fb_views);
    s.videos += n(r.ig_videos_posted);
    s.newFollowers += n(r.ig_new_followers);
    s.likes += n(r.ig_likes);
    s.comments += n(r.ig_comments);
    s.saves += n(r.ig_saves);
    s.shares += n(r.ig_shares);
    s.reposts += n(r.ig_reposts);
    s.dms += n(r.ig_dms_received);
    s.manychat += n(r.ig_manychat_handled);
    s.posts += n(r.ig_posts_published);
    s.waChats += n(r.wa_chats_received);
    s.walkins += n(r.wa_walkins_booked);
    s.reviews += n(r.google_new_reviews);
  }
  for (const a of apiStores) {
    const s = stores.get(a.store_id)!;
    const v = views.get(a.store_id) || { instagram: 0, youtube: 0, facebook: 0 };
    s.engagement = s.likes + s.comments + s.saves + s.shares + s.reposts;
    s.hasSocial = s.videos > 0 || v.instagram > 0 || s.followers > 0 || s.posts > 0;
    const has: Record<Platform, boolean> = { instagram: s.hasSocial, youtube: v.youtube > 0, facebook: v.facebook > 0 };
    for (const p of PLATFORMS) {
      const target = n(a.targets?.[p]);
      s.platforms[p] = { views: v[p], target, hasData: has[p], pct: has[p] && target > 0 ? (v[p] / target) * 100 : null };
    }
  }
  return [...stores.values()];
}

export interface PlatformTotal {
  views: number;
  target: number;
  pct: number;
  storesReporting: number;
}

export interface SocialTotals {
  stores: number;
  socialStores: number;
  platforms: Record<Platform, PlatformTotal>;
  /** Platforms at least one store in view has reported — only these are shown. */
  activePlatforms: Platform[];
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
  freshCounts: Record<Status, number>;
}

export function totalsOf(stores: SocialStore[]): SocialTotals {
  const social = stores.filter((s) => s.hasSocial);
  const rated = stores.filter((s) => s.rating !== null);
  const sum = (a: SocialStore[], f: (s: SocialStore) => number) => a.reduce((t, s) => t + f(s), 0);
  const statusCounts: Record<Status, number> = { good: 0, warn: 0, crit: 0, none: 0 };
  const freshCounts: Record<Status, number> = { good: 0, warn: 0, crit: 0, none: 0 };
  stores.forEach((s) => {
    statusCounts[overallStatus(s)]++;
    freshCounts[freshnessStatus(s.lastUpdatedAt)]++;
  });
  const platforms = {} as Record<Platform, PlatformTotal>;
  for (const p of PLATFORMS) {
    // Every store in view counts towards the target, reporting or not —
    // a team leader with 5 stores carries all 5 stores' targets.
    const target = sum(stores, (s) => s.platforms[p].target);
    const views = sum(stores, (s) => s.platforms[p].views);
    platforms[p] = { views, target, pct: target ? (views / target) * 100 : 0, storesReporting: stores.filter((s) => s.platforms[p].hasData).length };
  }
  return {
    stores: stores.length,
    socialStores: social.length,
    platforms,
    activePlatforms: PLATFORMS.filter((p) => platforms[p].storesReporting > 0),
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
    freshCounts,
  };
}

export interface SocialScope {
  kind: "company" | "team_leader" | "store";
  label: string;
  can_sync: boolean;
}

/** Social performance for the logged-in user's stores (all stores for
 * admin-tier roles, a team leader's own stores, or a store account's
 * store). With no month it opens on the latest month that has data. Keyed
 * under "sheets-data" so the sheet-sync socket refresh reloads it. */
export function useSocialPerformance(month?: string) {
  const q = useQuery({
    queryKey: ["sheets-data", "social-performance", month || "latest"],
    queryFn: async () => {
      const res = await api.fetchRaw(`/social/performance${month ? `?month=${month}` : ""}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
  });
  const d = q.data;
  return {
    scope: (d?.scope || null) as SocialScope | null,
    months: (d?.months || []) as string[],
    month: d?.month as string | undefined,
    lastSyncedAt: (d?.last_synced_at || null) as string | null,
    stores: d ? buildStores(d.stores || [], d.rows || []) : [],
    isLoading: q.isLoading,
    error: q.error,
    empty: !!d && (d.stores || []).length === 0,
  };
}
