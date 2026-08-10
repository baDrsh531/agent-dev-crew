import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";
const KEY = "adc-theme";

/**
 * The viewer's theme, and a way to change it.
 *
 * The OS preference is the default rather than a hardcoded dark: someone who
 * has never touched the toggle gets what the rest of their machine does. An
 * explicit choice is remembered and wins from then on, in both directions —
 * "I want light on a dark desktop" has to be expressible.
 */
export function useTheme(): [Theme, (next: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = localStorage.getItem(KEY);
    if (stored === "light" || stored === "dark") return stored;
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const choose = useCallback((next: Theme) => {
    localStorage.setItem(KEY, next);
    setTheme(next);
  }, []);

  return [theme, choose];
}
