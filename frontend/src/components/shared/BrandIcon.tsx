import { useId, type CSSProperties } from "react";
import { Footprints, Globe, Phone, UserPlus, Users } from "lucide-react";
import {
  siFacebook, siGoogle, siInstagram, siMeta, siSnapchat, siTiktok, siWhatsapp, siYoutube,
} from "simple-icons";

/** Official brand marks (Simple Icons) for the platforms the dashboards
 * report on, in each brand's own colour. */
const ICONS = {
  instagram: siInstagram,
  facebook: siFacebook,
  whatsapp: siWhatsapp,
  youtube: siYoutube,
  google: siGoogle,
  meta: siMeta,
  tiktok: siTiktok,
  snapchat: siSnapchat,
} as const;

export type Brand = keyof typeof ICONS;

export function isBrand(name: string): name is Brand {
  return name in ICONS;
}

export function BrandIcon({ brand, size = 16, color, className, style }: {
  brand: Brand;
  size?: number;
  /** Override the brand colour (e.g. "currentColor" on a filled button). */
  color?: string;
  className?: string;
  style?: CSSProperties;
}) {
  const gradientId = useId();
  const icon = ICONS[brand];
  // Instagram's mark is its gradient; the rest are single-colour.
  const fill = color ?? (brand === "instagram" ? `url(#${gradientId})` : `#${icon.hex}`);
  return (
    <svg
      role="img" aria-label={icon.title} viewBox="0 0 24 24" width={size} height={size}
      className={className} style={{ flexShrink: 0, ...style }}
    >
      {brand === "instagram" && !color && (
        <defs>
          <radialGradient id={gradientId} cx="30%" cy="107%" r="150%">
            <stop offset="0" stopColor="#fdf497" />
            <stop offset="0.05" stopColor="#fdf497" />
            <stop offset="0.45" stopColor="#fd5949" />
            <stop offset="0.6" stopColor="#d6249f" />
            <stop offset="0.9" stopColor="#285AEB" />
          </radialGradient>
        </defs>
      )}
      <path d={icon.path} fill={fill} />
    </svg>
  );
}

/** Drop-in for lucide-style icon slots that pass `size` and `style`. */
export function InstagramIcon({ size = 20, style }: { size?: number; style?: CSSProperties }) {
  return <BrandIcon brand="instagram" size={size} style={style} />;
}

/** The icon for a CRM lead source key (crm.py SOURCE_LABELS). */
export function SourceIcon({ source, size = 12 }: { source: string; size?: number }) {
  const brand: Record<string, Brand> = {
    instagram: "instagram", facebook: "facebook", whatsapp: "whatsapp", meta_sheet: "meta",
  };
  if (brand[source]) return <BrandIcon brand={brand[source]} size={size} />;
  const Icon = { website: Globe, walk_in: Footprints, phone: Phone, referral: Users }[source] ?? UserPlus;
  return <Icon size={size} style={{ flexShrink: 0 }} />;
}
