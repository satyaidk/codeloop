import { useEffect } from "react";
import type { Theme } from "../lib/types";

/** Puts the chosen theme on <html data-theme>, where global.css picks it up. "system" follows the OS, live. */
export function useTheme(theme: Theme) {
  useEffect(() => {
    const root = document.documentElement;
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = theme === "dark" || (theme === "system" && Boolean(media?.matches));
      root.dataset.theme = dark ? "dark" : "light";
    };
    apply();
    if (theme !== "system" || !media) return;
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);
}
