import { useState } from "react";
import { Phone, Copy, Check } from "lucide-react";

// Some source rows have a stray letter stuck onto the number (e.g. a
// data-entry/export artifact like "p+919845012345"), which a dialer can't
// handle at all. Strips everything except digits and a single leading "+"
// so what reaches the dialer, the display, and the clipboard is always a
// clean, dialable number.
export function sanitizePhone(phone: string): string {
  const hasPlus = phone.includes("+");
  const digits = phone.replace(/\D/g, "");
  return (hasPlus ? "+" : "") + digits;
}

// A phone number with a copy button and a call button, reused everywhere
// a lead's number is shown (Telecaller Dashboard, Manage Leads, Lead
// Detail). The call button is a plain tel: link — the only way a web page
// can hand a number to the device's own dialer, but that's genuinely all
// that's needed: on a phone it opens the native dialer pre-filled with
// the number, ready to place the call in one more tap.
export function PhoneActions({
  phone,
  size = "sm",
  className = "",
}: {
  phone: string;
  size?: "sm" | "md";
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  if (!phone) return null;
  const clean = sanitizePhone(phone);
  if (!clean.replace("+", "")) return <span className={`text-xs text-[var(--text-muted)] ${className}`}>{phone}</span>;

  const copy = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(clean);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API can be unavailable (non-HTTPS, older browser, denied
      // permission) — fail silently rather than show a broken error state
      // for a convenience feature.
    }
  };

  const iconSize = size === "md" ? 14 : 12;
  const textSize = size === "md" ? "text-sm" : "text-xs";

  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      <a
        href={`tel:${clean}`}
        onClick={(e) => e.stopPropagation()}
        className={`inline-flex items-center gap-1 ${textSize} text-[var(--accent-blue)] hover:underline font-mono`}
        title="Call this number"
      >
        {clean}
      </a>
      <a
        href={`tel:${clean}`}
        onClick={(e) => e.stopPropagation()}
        className="p-1 rounded-md text-emerald-400 hover:bg-emerald-500/15 shrink-0"
        title="Call"
      >
        <Phone size={iconSize} />
      </a>
      <button
        onClick={copy}
        className="p-1 rounded-md text-[var(--text-muted)] hover:text-white hover:bg-white/10 shrink-0"
        title="Copy number"
      >
        {copied ? <Check size={iconSize} className="text-emerald-400" /> : <Copy size={iconSize} />}
      </button>
    </span>
  );
}
