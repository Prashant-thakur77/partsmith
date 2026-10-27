"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import * as React from "react";
import { applyTheme, type ThemePref } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { radioGroupKeys } from "@/lib/a11y";

function subscribe(cb: () => void) {
  window.addEventListener("partsmith:theme", cb);
  return () => window.removeEventListener("partsmith:theme", cb);
}

export function ThemeToggle({ className }: { className?: string }) {
  const pref = React.useSyncExternalStore(
    subscribe,
    () => (document.documentElement.dataset.themePref as ThemePref | undefined) ?? "system",
    () => "system" as ThemePref,
  );
  React.useEffect(() => {
    if (pref !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => applyTheme("system");
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [pref]);
  const opts: { v: ThemePref; icon: typeof Sun; label: string }[] = [
    { v: "system", icon: Monitor, label: "System theme" },
    { v: "light", icon: Sun, label: "Light theme" },
    { v: "dark", icon: Moon, label: "Dark theme" },
  ];
  return (
    <div role="radiogroup" onKeyDown={radioGroupKeys} aria-label="Theme" className={cn("inline-flex rounded-md border border-border bg-surface-2 p-0.5", className)}>
      {opts.map(({ v, icon: Icon, label }) => (
        <button
          key={v}
          type="button"
          role="radio"
          aria-checked={pref === v}
          aria-label={label}
          title={label}
          onClick={() => applyTheme(v)}
          className={cn(
            "inline-flex size-6 items-center justify-center rounded-[4px] text-subtle transition-colors hover:text-fg",
            pref === v && "bg-surface text-fg shadow-sm",
          )}
        >
          <Icon className="size-3.5" aria-hidden />
        </button>
      ))}
    </div>
  );
}
