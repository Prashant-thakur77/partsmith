/** Theme preference (system | light | dark), applied as `data-theme` on <html> before paint by THEME_SCRIPT. */
export type ThemePref = "system" | "light" | "dark";
export const THEME_KEY = "partsmith.theme";

export const THEME_SCRIPT = `(()=>{try{var p=localStorage.getItem("${THEME_KEY}")||"system";var d=p==="dark"||(p==="system"&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.dataset.theme=d?"dark":"light";document.documentElement.dataset.themePref=p}catch(e){document.documentElement.dataset.theme="light"}})()`;

export function applyTheme(pref: ThemePref): void {
  const dark = pref === "dark" || (pref === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.dataset.themePref = pref;
  try {
    window.localStorage.setItem(THEME_KEY, pref);
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event("partsmith:theme"));
}
