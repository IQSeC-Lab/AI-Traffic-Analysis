// Appearance chosen in the sidebar or Settings → Appearance, kept in this browser.
// Theme: light, dark, or following the OS. Accent: one of ACCENTS.
// The CSS lives in app/globals.css under :root[data-theme] and :root[data-accent].

export const ACCENTS = [
  { id: "violet", label: "Violet", swatch: "#4a3aa7", swatchDark: "#9085e9" },
  { id: "green", label: "Green", swatch: "#008300", swatchDark: "#0ca30c" },
  { id: "blue", label: "Blue", swatch: "#2a78d6", swatchDark: "#3987e5" },
  { id: "mono", label: "Mono", swatch: "#2c2c2a", swatchDark: "#d6d5ce" },
] as const;

export type Accent = (typeof ACCENTS)[number]["id"];
export type ThemePref = "light" | "dark" | "system";

const ACCENT_KEY = "mallm-accent";
const THEME_KEY = "mallm-theme";
export const DEFAULT_ACCENT: Accent = "violet";

/**
 * Runs in <head> before the first paint so the saved theme and accent never flash.
 * With "system" it keeps following the OS while the page is open.
 */
export const APPEARANCE_INIT_SCRIPT = `(function(){try{
var d=document.documentElement,m=matchMedia("(prefers-color-scheme: dark)");
function apply(){var t=localStorage.getItem("${THEME_KEY}")||"system";d.setAttribute("data-theme-pref",t);d.setAttribute("data-theme",t==="dark"||(t!=="light"&&m.matches)?"dark":"light")}
apply();m.addEventListener("change",apply);
var a=localStorage.getItem("${ACCENT_KEY}");if(a)d.setAttribute("data-accent",a);
}catch(e){document.documentElement.setAttribute("data-theme","light")}})()`;

function save(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Storage unavailable (private mode): the choice lasts for this page only.
  }
}

export function applyAccent(accent: Accent) {
  document.documentElement.dataset.accent = accent;
  save(ACCENT_KEY, accent);
}

export function currentAccent(): Accent {
  const value = document.documentElement.dataset.accent;
  return ACCENTS.some((a) => a.id === value) ? (value as Accent) : DEFAULT_ACCENT;
}

export function applyTheme(pref: ThemePref) {
  save(THEME_KEY, pref);
  const dark = pref === "dark" || (pref === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.themePref = pref;
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export function currentThemePref(): ThemePref {
  const value = document.documentElement.dataset.themePref;
  return value === "light" || value === "dark" ? value : "system";
}

/** Re-render when the theme or accent attributes on <html> change (for useSyncExternalStore). */
export function subscribeAppearance(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-accent", "data-theme-pref"],
  });
  return () => observer.disconnect();
}
