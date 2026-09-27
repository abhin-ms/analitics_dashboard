import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import Globe, { GlobeMethods } from "react-globe.gl";
import { Globe as GlobeIcon, ArrowLeft, MapPin } from "lucide-react";
import { formatByCountry as fmtByCountry } from "@/lib/formatMoney";

export interface GlobeBranch {
  shop: string;
  country: string;
  target: number;
  actual: number;
  achievement_pct: number;
  stock_units?: number;
  tl?: string;
  walk_ins?: number;
  conversions?: number;
}

interface BranchGlobeProps {
  branches: GlobeBranch[];
}

interface CountryFeature {
  type: "Feature";
  properties: { NAME?: string; ADMIN?: string; ISO_A2?: string; [k: string]: any };
  geometry: any;
}

function shortStore(name: string) {
  return name
    .replace("Kerala ", "")
    .replace("Chennai ", "")
    .replace("Bangalore ", "")
    .replace("Hyderabad ", "")
    .replace("TN ", "")
    .replace("Mumbai ", "")
    .replace("Delhi ", "")
    .replace(" Lajpat Nagar", "")
    .replace(" Mall", "")
    .trim();
}

function ragColor(p: number) {
  return p >= 65 ? "#10b981" : p >= 35 ? "#f59e0b" : "#ef4444";
}


const COUNTRY_COLORS: Record<string, string> = {
  India: "#3b82f6",
  UAE: "#10b981",
  Oman: "#f59e0b",
  Qatar: "#a855f7",
  Pakistan: "#ef4444",
  Malaysia: "#06b6d4",
  UK: "#ec4899",
  Bahrain: "#f97316",
};

// City-level coordinates only exist for India's originally-seeded branches.
// Every other country's shops share one center point since there's no
// per-shop geocoding for them yet.
const STORE_COORDS: Record<string, [number, number]> = {
  "Kerala Kasargod":     [74.9952, 12.4992],
  "Kerala Kannur":       [75.3704, 11.8745],
  "Kerala Calicut":      [75.7873, 11.2588],
  "Kerala Wayanad":      [76.1320, 11.6854],
  "Kerala Thrissur":     [76.2144, 10.5270],
  "Kerala Palakkad":     [76.6548, 10.7867],
  "Kerala Kottkal":      [76.5226,  9.5916],
  "Kerala Kochi":        [76.2674,  9.9312],
  "Kerala Pathanamthitta":[76.8346,  9.2648],
  "Kerala Kollam":       [76.6284,  8.8932],
  "Kerala Trivandrum":   [76.9366,  8.5241],
  "Chennai Kodambakam":  [80.2253, 13.0524],
  "Chennai Velachery":   [80.2181, 12.9830],
  "Tn Coimbatore":       [76.9558, 11.0168],
  "Bangalore Indiranagar":[77.6408, 12.9784],
  "Bangalore Marathahalli":[77.6971, 12.9562],
  "Mangalore":           [74.8560, 12.9141],
  "Mysore":              [76.6394, 12.2958],
  "Hyderabad Kukatpally":[78.4042, 17.4847],
  "Hyderabad Hitech":    [78.3772, 17.4435],
  "Mumbai Bandra":       [72.8372, 19.0544],
  "Mumbai Korum":        [72.9273, 19.2850],
  "Delhi Lajpat Nagar":  [77.2406, 28.5679],
  "Guwahati":            [91.7362, 26.1445],
};

const COUNTRY_CENTERS: Record<string, [number, number]> = {
  India: [78.9629, 20.5937],
  UAE: [54.3773, 24.4539],
  Oman: [56.0, 21.0],
  Qatar: [51.1839, 25.2854],
  Pakistan: [69.3451, 30.3753],
  Malaysia: [101.9758, 4.2105],
  UK: [-1.5, 52.5],
  Bahrain: [50.5577, 26.0667],
};

// Where the country pin sits at the zoomed-out view. The Gulf countries are
// so close together that their pins would overlap at their real centres,
// so Bahrain and Qatar are nudged out to the side over the sea.
const COUNTRY_PIN_POS: Record<string, [number, number]> = {
  Bahrain: [48.2, 28.4],
  Qatar: [48.8, 24.2],
  UAE: [55.8, 25.6],
  Oman: [57.8, 21.2],
};

// The public world-countries GeoJSON uses full country names, while this
// app uses short ones (UAE, UK) — this maps between the two so polygon
// clicks/highlighting can match a branch's country to its map polygon.
const GEOJSON_NAME_FOR_COUNTRY: Record<string, string> = {
  India: "India",
  UAE: "United Arab Emirates",
  Oman: "Oman",
  Qatar: "Qatar",
  Pakistan: "Pakistan",
  Malaysia: "Malaysia",
  UK: "United Kingdom",
  Bahrain: "Bahrain",
};

// City keywords found in MCP shop names ("GUARDX INNOVATIONS - Indiranagar",
// "FORTISAFE - Kottakkal", "… - Dubai Mall") → [lng, lat]. Lets MCP-named
// shops, which aren't in STORE_COORDS, still land in the right city.
const CITY_COORDS: [string, [number, number]][] = [
  // India
  ["indiranagar", [77.6408, 12.9784]], ["marathahalli", [77.6971, 12.9562]], ["koramangala", [77.6245, 12.9352]],
  ["whitefield", [77.7500, 12.9698]], ["jayanagar", [77.5838, 12.9250]], ["bangalore", [77.5946, 12.9716]],
  ["bengaluru", [77.5946, 12.9716]], ["velachery", [80.2181, 12.9830]], ["kodambakkam", [80.2253, 13.0524]],
  ["kodambakam", [80.2253, 13.0524]], ["anna nagar", [80.2101, 13.0850]], ["chennai", [80.2707, 13.0827]],
  ["coimbatore", [76.9558, 11.0168]], ["hitech", [78.3772, 17.4435]], ["kukatpally", [78.4042, 17.4847]],
  ["hyderabad", [78.4867, 17.3850]], ["bandra", [72.8372, 19.0544]], ["korum", [72.9273, 19.2850]],
  ["thane", [72.9781, 19.2183]], ["mumbai", [72.8777, 19.0760]], ["lajpat", [77.2406, 28.5679]],
  ["delhi", [77.2090, 28.6139]], ["noida", [77.3910, 28.5355]], ["gurgaon", [77.0266, 28.4595]],
  ["guwahati", [91.7362, 26.1445]], ["kasargod", [74.9952, 12.4992]], ["kasaragod", [74.9952, 12.4992]],
  ["kannur", [75.3704, 11.8745]], ["clt", [75.7873, 11.2588]], ["calicut", [75.7873, 11.2588]],
  ["kozhikode", [75.7873, 11.2588]], ["kottakkal", [75.9978, 10.9990]], ["wayanad", [76.1320, 11.6854]],
  ["thrissur", [76.2144, 10.5270]], ["palakkad", [76.6548, 10.7867]], ["kochi", [76.2674, 9.9312]],
  ["cochin", [76.2674, 9.9312]], ["pathanamthitta", [76.8346, 9.2648]], ["kollam", [76.6284, 8.8932]],
  ["trivandrum", [76.9366, 8.5241]], ["thiruvananthapuram", [76.9366, 8.5241]], ["mangalore", [74.8560, 12.9141]],
  ["mysore", [76.6394, 12.2958]], ["pune", [73.8567, 18.5204]],
  // Gulf and others
  ["karama", [55.3032, 25.2360]], ["al ghurair", [55.3169, 25.2677]], ["qusais", [55.3869, 25.2771]],
  ["dubai", [55.2708, 25.2048]], ["deira", [55.3200, 25.2711]], ["abu dhabi", [54.3773, 24.4539]],
  ["auh", [54.3773, 24.4539]], ["bawabat", [54.6130, 24.4040]], ["shbaiya", [54.5480, 24.3470]],
  ["shabiya", [54.5480, 24.3470]], ["(aln)", [55.7447, 24.2075]], ["sharjah", [55.4209, 25.3463]], ["ajman", [55.5136, 25.4052]], ["al ain", [55.7447, 24.2075]],
  ["ras al", [55.9432, 25.8007]], ["fujairah", [56.3265, 25.1288]], ["muscat", [58.4059, 23.5880]],
  ["seeb", [58.1890, 23.6700]], ["sohar", [56.7075, 24.3470]], ["salalah", [54.0924, 17.0151]],
  ["nizwa", [57.5301, 22.9333]], ["doha", [51.5310, 25.2854]], ["manama", [50.5860, 26.2285]],
  ["stratford", [-0.0035, 51.5416]], ["london", [-0.1276, 51.5072]], ["karachi", [67.0011, 24.8607]], ["lahore", [74.3587, 31.5204]],
  ["islamabad", [73.0479, 33.6844]], ["kuala lumpur", [101.6869, 3.1390]],
];

function coordsForBranch(branch: GlobeBranch): [number, number] {
  if (branch.country === "India" && STORE_COORDS[branch.shop]) return STORE_COORDS[branch.shop];
  const name = (branch.shop || "").toLowerCase();
  for (const [key, coords] of CITY_COORDS) {
    if (name.includes(key)) return coords;
  }
  return COUNTRY_CENTERS[branch.country] ?? COUNTRY_CENTERS.India;
}

/** Shops that land on the same point (same city, or no city in the name)
 * are spread on a small ring so every pin stays visible and clickable. */
function spreadOverlaps<T extends { lat: number; lng: number }>(items: T[], radiusDeg: number): T[] {
  const groups = new Map<string, T[]>();
  for (const it of items) {
    const k = `${it.lat.toFixed(3)},${it.lng.toFixed(3)}`;
    groups.set(k, [...(groups.get(k) || []), it]);
  }
  const out: T[] = [];
  for (const g of groups.values()) {
    if (g.length === 1) { out.push(g[0]!); continue; }
    g.forEach((it, i) => {
      const angle = (2 * Math.PI * i) / g.length;
      const r = radiusDeg * (1 + Math.floor(i / 12) * 0.6);
      out.push({ ...it, lat: it.lat + r * Math.sin(angle), lng: it.lng + r * Math.cos(angle) });
    });
  }
  return out;
}

/** Opening view: zoomed on the region that holds most branches. Countries
 * far from it (e.g. a single UK branch) stay reachable from their chip
 * instead of forcing the whole map out to a tiny globe. */
function fitView(countries: string[], counts: Record<string, number>) {
  const all = countries.filter((c) => COUNTRY_CENTERS[c]);
  if (!all.length) return { lat: 20, lng: 70, altitude: 1.6 };
  const total = all.reduce((a, c) => a + (counts[c] || 1), 0);
  const cLng = all.reduce((a, c) => a + COUNTRY_CENTERS[c]![0] * (counts[c] || 1), 0) / total;
  const cLat = all.reduce((a, c) => a + COUNTRY_CENTERS[c]![1] * (counts[c] || 1), 0) / total;
  const core = all.filter((c) => Math.abs(COUNTRY_CENTERS[c]![0] - cLng) <= 40 && Math.abs(COUNTRY_CENTERS[c]![1] - cLat) <= 30);
  const pts = (core.length ? core : all).map((c) => COUNTRY_CENTERS[c]) as [number, number][];
  if (!pts.length) return { lat: 20, lng: 70, altitude: 1.6 };
  const lngs = pts.map((p) => p[0]), lats = pts.map((p) => p[1]);
  const lngSpan = Math.max(...lngs) - Math.min(...lngs);
  const latSpan = Math.max(...lats) - Math.min(...lats);
  const span = Math.max(lngSpan, latSpan * 1.6, 20);
  return {
    lat: (Math.max(...lats) + Math.min(...lats)) / 2,
    lng: (Math.max(...lngs) + Math.min(...lngs)) / 2,
    altitude: Math.min(2.2, Math.max(0.75, span / 30)),
  };
}
const COUNTRIES_URL =
  "https://raw.githubusercontent.com/vasturiano/globe.gl/master/example/datasets/ne_110m_admin_0_countries.geojson";

export default function BranchGlobe({ branches }: BranchGlobeProps) {
  const globeRef = useRef<GlobeMethods | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 600, height: 560 });
  const [countries, setCountries] = useState<CountryFeature[]>([]);
  const [selectedCountry, setSelectedCountry] = useState<string | null>(null);
  const [hoverCountry, setHoverCountry] = useState<CountryFeature | null>(null);
  const [selectedStore, setSelectedStore] = useState<(GlobeBranch & { lat: number; lng: number }) | null>(null);

  const branchCountries = useMemo(() => {
    const set = new Set<string>();
    for (const b of branches) if (b.country) set.add(b.country);
    return set;
  }, [branches]);

  const branchCountryList = useMemo(
    () => Array.from(branchCountries).sort((a, b) => a.localeCompare(b)),
    [branchCountries]
  );

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0].contentRect.width;
      setSize({ width: Math.max(320, Math.round(w)), height: 560 });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch(COUNTRIES_URL)
      .then((res) => res.json())
      .then((data) => {
        if (!cancelled) setCountries(data.features || []);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const homeView = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const b of branches) counts[b.country] = (counts[b.country] || 0) + 1;
    return fitView(branchCountryList, counts);
  }, [branchCountryList, branches]);

  // Opens zoomed to the branch countries and stays still (no auto-spin), so
  // the map is readable without dragging or scrolling first.
  useEffect(() => {
    const g = globeRef.current;
    if (!g) return;
    if (!selectedCountry) g.pointOfView(homeView, 0);
    // Frozen: no drag-rotate, no scroll-zoom, no pan (scrolling over the
    // map scrolls the page). Clicking a country pin still flies in, and
    // "All countries" flies back.
    const controls = g.controls();
    controls.autoRotate = false;
    controls.enableZoom = false;
    controls.enableRotate = false;
    controls.enablePan = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [countries.length, homeView]);

  const flyToCountry = useCallback((country: string) => {
    const g = globeRef.current;
    if (!g) return;
    const [lng, lat] = COUNTRY_CENTERS[country] ?? COUNTRY_CENTERS.India;
    g.controls().autoRotate = false;
    const small = ["Bahrain", "Qatar"].includes(country);
    g.pointOfView({ lat, lng, altitude: country === "India" ? 1.15 : small ? 0.25 : 0.6 }, 1400);
    setSelectedCountry(country);
    setSelectedStore(null);
  }, []);

  const flyToWorld = useCallback(() => {
    const g = globeRef.current;
    if (!g) return;
    g.pointOfView(homeView, 1400);
    g.controls().autoRotate = false;
    setSelectedCountry(null);
    setSelectedStore(null);
  }, [homeView]);

  const countryForFeature = useCallback(
    (feat: CountryFeature): string | null => {
      const geoName = feat.properties?.NAME || feat.properties?.ADMIN;
      for (const country of branchCountryList) {
        if (GEOJSON_NAME_FOR_COUNTRY[country] === geoName) return country;
      }
      return null;
    },
    [branchCountryList]
  );

  const handlePolygonClick = useCallback(
    (feat: object) => {
      const country = countryForFeature(feat as CountryFeature);
      if (country) flyToCountry(country);
    },
    [countryForFeature, flyToCountry]
  );

  const storeMarkers = useMemo(() => {
    if (!selectedCountry) return [];
    const pins = branches
      .filter((b) => b.country === selectedCountry)
      .map((b) => {
        const [lng, lat] = coordsForBranch(b);
        return { ...b, lat, lng };
      });
    const small = ["Bahrain", "Qatar"].includes(selectedCountry);
    return spreadOverlaps(pins, selectedCountry === "India" ? 0.35 : small ? 0.05 : 0.12);
  }, [branches, selectedCountry]);

  // World view: one pin per branch country (count + achievement), so every
  // country with a branch is visible — even Bahrain/Qatar, which are too
  // small to see as shapes at this zoom.
  const countryMarkers = useMemo(() => {
    if (selectedCountry) return [];
    return branchCountryList.map((country) => {
      const list = branches.filter((b) => b.country === country);
      const target = list.reduce((a, b) => a + (b.target || 0), 0);
      const actual = list.reduce((a, b) => a + (b.actual || 0), 0);
      const [lng, lat] = COUNTRY_PIN_POS[country] ?? COUNTRY_CENTERS[country] ?? COUNTRY_CENTERS.India;
      return { kind: "country", country, count: list.length, pct: target > 0 ? (actual / target) * 100 : null, lat, lng };
    });
  }, [branches, branchCountryList, selectedCountry]);

  const makeCountryEl = useCallback((d: object) => {
    const c = d as { country: string; count: number; pct: number | null; lat: number; lng: number };
    const color = COUNTRY_COLORS[c.country] || "#3b82f6";
    const el = document.createElement("div");
    el.dataset.lat = String(c.lat);
    el.dataset.lng = String(c.lng);
    el.style.cursor = "pointer";
    el.style.transform = "translate(-50%, -50%)";
    el.innerHTML = `
      <div style="display:flex;align-items:center;gap:6px;padding:3px 8px 3px 4px;border-radius:9999px;
        background:rgba(17,19,30,0.92);border:1px solid ${color};box-shadow:0 0 10px ${color}66;
        font-size:11px;font-weight:600;color:#fff;white-space:nowrap;font-family:inherit;">
        <span style="min-width:18px;height:18px;border-radius:9999px;background:${color};display:inline-flex;
          align-items:center;justify-content:center;font-size:10px;padding:0 4px;">${c.count}</span>
        ${c.country}${c.pct !== null ? ` · <span style="color:${ragColor(c.pct)}">${c.pct.toFixed(0)}%</span>` : ""}
      </div>`;
    el.onclick = (e) => {
      e.stopPropagation();
      flyToCountry(c.country);
    };
    return el;
  }, [flyToCountry]);

  const makeMarkerEl = useCallback((d: object) => {
    const branch = d as GlobeBranch & { lat: number; lng: number };
    const color = ragColor(branch.achievement_pct);
    const el = document.createElement("div");
    el.dataset.lat = String(branch.lat);
    el.dataset.lng = String(branch.lng);
    el.style.cursor = "pointer";
    el.style.display = "flex";
    el.style.flexDirection = "column";
    el.style.alignItems = "center";
    el.style.transform = "translate(-50%, -100%)";
    el.innerHTML = `
      <div style="
        width:10px;height:10px;border-radius:9999px;
        background:${color};
        box-shadow:0 0 0 3px ${color}33, 0 0 8px ${color};
        border:1.5px solid rgba(17,19,30,0.9);
      "></div>
      <div style="
        margin-top:4px;padding:2px 6px;border-radius:6px;
        background:rgba(17,19,30,0.92);border:1px solid rgba(255,255,255,0.08);
        font-size:10px;font-weight:600;color:#fff;white-space:nowrap;
        font-family:inherit;
      ">${shortStore(branch.shop)} · ${branch.achievement_pct.toFixed(0)}%</div>
    `;
    el.onclick = (e) => {
      e.stopPropagation();
      setSelectedStore(d as GlobeBranch & { lat: number; lng: number });
    };
    return el;
  }, []);

  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-card)] p-5 sm:p-6 min-w-0">
      <div className="flex items-start justify-between mb-3 flex-wrap gap-3">
        <div>
          <h3 className="text-base font-bold text-white tracking-tight flex items-center gap-2">
            <GlobeIcon size={18} className="text-[var(--accent-blue)]" />
            Branch Network
          </h3>
          <p className="text-xs text-[var(--text-muted)]">
            {selectedCountry
              ? `${storeMarkers.length} branches in ${selectedCountry} · click a pin for details`
              : `${branches.length} branches in ${branchCountryList.length} countries · click a country pin to see its branches`}
          </p>
        </div>
        {selectedCountry && (
          <button
            onClick={flyToWorld}
            className="flex items-center gap-1.5 text-xs font-semibold text-[var(--text-secondary)] hover:text-white bg-white/5 hover:bg-white/10 border border-[var(--border-subtle)] rounded-lg px-3 py-1.5 transition-colors"
          >
            <ArrowLeft size={13} /> All countries
          </button>
        )}
      </div>

      {/* Quick-select chips — a reliable way to pick a country, since some
          (Qatar, Bahrain) are tiny and hard to click precisely on the globe. */}
      {!selectedCountry && branchCountryList.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-3">
          {branchCountryList.map((country) => (
            <button
              key={country}
              onClick={() => flyToCountry(country)}
              className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border border-[var(--border-subtle)] bg-white/5 hover:bg-white/10 text-[var(--text-secondary)] hover:text-white transition-colors"
            >
              <span className="w-2 h-2 rounded-full" style={{ background: COUNTRY_COLORS[country] || "#6b7280" }} />
              {country} ({branches.filter((b) => b.country === country).length})
            </button>
          ))}
        </div>
      )}

      <div ref={containerRef} className="relative w-full rounded-xl overflow-hidden" style={{ height: 560 }}>
        <Globe
          ref={globeRef}
          width={size.width}
          height={size.height}
          backgroundColor="rgba(0,0,0,0)"
          globeImageUrl="//unpkg.com/three-globe/example/img/earth-night.jpg"
          polygonsData={countries}
          polygonAltitude={(f: object) => (countryForFeature(f as CountryFeature) ? 0.02 : 0.006)}
          polygonCapColor={(f: object) => {
            const feat = f as CountryFeature;
            const country = countryForFeature(feat);
            if (country) {
              const hex = COUNTRY_COLORS[country] || "#3b82f6";
              const r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16), b = parseInt(hex.slice(5, 7), 16);
              return `rgba(${r},${g},${b},0.65)`;
            }
            if (feat === hoverCountry) return "rgba(255,255,255,0.12)";
            return "rgba(255,255,255,0.04)";
          }}
          polygonSideColor={() => "rgba(0,0,0,0.2)"}
          polygonStrokeColor={(f: object) => (countryForFeature(f as CountryFeature) ? "#60a5fa" : "#1f2430")}
          polygonLabel={(f: object) => (f as CountryFeature).properties?.NAME || ""}
          onPolygonHover={(f: object | null) => setHoverCountry(f as CountryFeature | null)}
          onPolygonClick={handlePolygonClick}
          htmlElementsData={selectedCountry ? storeMarkers : countryMarkers}
          htmlLat={(d: object) => (d as { lat: number }).lat}
          htmlLng={(d: object) => (d as { lng: number }).lng}
          htmlAltitude={0.035}
          htmlTransitionDuration={0}
          // Keep every pin in the page and just fade the ones on the far side.
          // The library's default hides them outright, and it misjudged pins
          // sitting over a raised (highlighted) country such as India.
          htmlElementVisibilityModifier={(el: HTMLElement) => {
            // Own "facing the viewer" test: the library's check wrongly hid
            // pins sitting over a raised (highlighted) country such as India.
            const pov = globeRef.current?.pointOfView();
            const lat = Number(el.dataset.lat), lng = Number(el.dataset.lng);
            let visible = true;
            if (pov && Number.isFinite(lat) && Number.isFinite(lng)) {
              const r = Math.PI / 180;
              const cos = Math.sin(lat * r) * Math.sin(pov.lat * r)
                + Math.cos(lat * r) * Math.cos(pov.lat * r) * Math.cos((lng - pov.lng) * r);
              visible = cos > 0.15; // within ~80° of the view centre
            }
            el.style.opacity = visible ? "1" : "0";
            el.style.pointerEvents = visible ? "auto" : "none";
          }}
          htmlElement={(d: object) => ((d as { kind?: string }).kind === "country" ? makeCountryEl(d) : makeMarkerEl(d))}
        />

        {selectedStore && (
          <div className="absolute top-3 left-3 w-56 rounded-xl border border-[var(--border-subtle)] bg-[#11131e]/95 backdrop-blur p-3 shadow-xl">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-xs font-bold text-white">{shortStore(selectedStore.shop)}</span>
              <button onClick={() => setSelectedStore(null)} className="text-[var(--text-muted)] hover:text-white text-xs">
                &#10005;
              </button>
            </div>
            {selectedStore.tl && <p className="text-[10px] text-[var(--text-muted)] mb-2">TL: {selectedStore.tl}</p>}
            <div className="space-y-1 text-[11px] text-[var(--text-secondary)]">
              <div className="flex justify-between">
                <span>Revenue</span>
                <span className="font-semibold text-white">{fmtByCountry(selectedStore.actual, selectedStore.country)}</span>
              </div>
              <div className="flex justify-between">
                <span>Target</span>
                <span>{selectedStore.target > 0 ? fmtByCountry(selectedStore.target, selectedStore.country) : "—"}</span>
              </div>
              <div className="flex justify-between">
                <span>Achievement</span>
                <span className="font-semibold" style={{ color: ragColor(selectedStore.achievement_pct) }}>
                  {selectedStore.achievement_pct.toFixed(1)}%
                </span>
              </div>
              {selectedStore.walk_ins !== undefined && (
                <div className="flex justify-between">
                  <span>Walk-ins</span>
                  <span>{selectedStore.walk_ins}</span>
                </div>
              )}
              {selectedStore.conversions !== undefined && (
                <div className="flex justify-between">
                  <span>Conversions</span>
                  <span>{selectedStore.conversions}</span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
