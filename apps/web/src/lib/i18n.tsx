"use client";

/** Tiny i18n: English + Hinglish (hi-Latn), stored per device. Missing keys fall back to English. */
import * as React from "react";
import { STRINGS, type StringKey } from "./i18n-strings";

export type Lang = "en" | "hi-Latn";
const KEY = "partsmith.lang";
const EVENT = "partsmith:lang";

function read(): Lang {
  try {
    return window.localStorage.getItem(KEY) === "hi-Latn" ? "hi-Latn" : "en";
  } catch {
    return "en";
  }
}

export function setLang(l: Lang): void {
  try {
    window.localStorage.setItem(KEY, l);
  } catch {
    /* storage blocked */
  }
  window.dispatchEvent(new Event(EVENT));
}

export function useLang(): Lang {
  return React.useSyncExternalStore(
    (cb) => {
      window.addEventListener(EVENT, cb);
      window.addEventListener("storage", cb);
      return () => {
        window.removeEventListener(EVENT, cb);
        window.removeEventListener("storage", cb);
      };
    },
    read,
    () => "en",
  );
}

export function translate(lang: Lang, key: string, vars?: Record<string, string | number>): string {
  const dict = STRINGS[lang] as Record<string, string>;
  let s = dict[key] ?? (STRINGS.en as Record<string, string>)[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v));
  return s;
}

export function useT() {
  const lang = useLang();
  const t = React.useCallback((key: StringKey | string, vars?: Record<string, string | number>) => translate(lang, key, vars), [lang]);
  return { t, lang };
}

/** Sets the `lang` attribute on a translated region so screen readers pronounce it correctly. */
export function I18nRegion({ children, className }: { children: React.ReactNode; className?: string }) {
  const lang = useLang();
  return (
    <div lang={lang === "hi-Latn" ? "hi-Latn" : "en"} className={className}>
      {children}
    </div>
  );
}

export function LangToggle({ className }: { className?: string }) {
  const lang = useLang();
  const opts: { v: Lang; label: string; full: string }[] = [
    { v: "en", label: "EN", full: "English" },
    { v: "hi-Latn", label: "Hinglish", full: "Hinglish (Hindi in Latin script)" },
  ];
  return (
    <div
      role="radiogroup"
      aria-label="Language"
      className={className ?? "inline-flex rounded-md border border-border bg-surface-2 p-0.5"}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
          e.preventDefault();
          setLang(lang === "en" ? "hi-Latn" : "en");
        }
      }}
    >
      {opts.map((o) => (
        <button
          key={o.v}
          type="button"
          role="radio"
          aria-checked={lang === o.v}
          aria-label={o.full}
          lang={o.v}
          tabIndex={lang === o.v ? 0 : -1}
          onClick={() => setLang(o.v)}
          className={
            "h-6 rounded-[4px] px-2 text-[11.5px] font-medium " + (lang === o.v ? "bg-surface text-fg shadow-sm" : "text-muted hover:text-fg")
          }
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
