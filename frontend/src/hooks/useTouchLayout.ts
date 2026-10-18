import { useEffect, useState } from "react";

// Phones and tablets: a narrow screen, or a touch-first device of any width
// (an iPad in landscape is ~1180px wide but has no mouse). Laptops with a
// touchscreen still report a fine primary pointer, so they keep the desktop.
const QUERY = "(max-width: 1023px), (hover: none) and (pointer: coarse)";

export function useTouchLayout(): boolean {
  const [match, setMatch] = useState(() => typeof window !== "undefined" && window.matchMedia(QUERY).matches);

  useEffect(() => {
    const mql = window.matchMedia(QUERY);
    const handler = () => setMatch(mql.matches);
    handler();
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  return match;
}
