import { useCallback, useEffect, useState } from "react";

export type Theme = "dark" | "light";

const STORAGE_KEY = "bp-theme";

export function getInitialTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {}
  // Light by default; dark mode is a per-user choice remembered in localStorage.
  return "light";
}

function applyTheme(theme: Theme) {
  document.documentElement.setAttribute("data-theme", theme);
}

// Call this once, synchronously, before the app renders — avoids a flash of
// the wrong theme on load.
export function initTheme() {
  applyTheme(getInitialTheme());
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(getInitialTheme);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {}
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [theme, setTheme]);

  return { theme, setTheme, toggleTheme };
}

/** The theme currently applied to <html>, live: re-renders when it's toggled
 * anywhere (useTheme's own state is per-instance, so other components'
 * copies wouldn't see the header's toggle). For components that draw their
 * own colours, e.g. the WebGL globe. */
export function useAppliedTheme(): Theme {
  const read = (): Theme => (document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light");
  const [theme, setThemeState] = useState<Theme>(read);
  useEffect(() => {
    const mo = new MutationObserver(() => setThemeState(read()));
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => mo.disconnect();
  }, []);
  return theme;
}
