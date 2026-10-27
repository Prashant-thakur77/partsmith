"use client";

/** Minimal toasts: a polite live region with up to 4 messages, each dismissible, auto-hiding after 5 s. */
import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

type ToastItem = { id: number; title: string; description?: string; tone: "info" | "ok" | "bad" };
type Listener = (items: ToastItem[]) => void;

let items: ToastItem[] = [];
let nextId = 1;
const listeners = new Set<Listener>();
const emit = () => listeners.forEach((l) => l(items));

function dismiss(id: number) {
  items = items.filter((t) => t.id !== id);
  emit();
}

/** Show a toast from anywhere (client side). */
export function toast(title: string, opts: { description?: string; tone?: ToastItem["tone"] } = {}): void {
  const id = nextId++;
  items = [...items, { id, title, description: opts.description, tone: opts.tone ?? "info" }].slice(-4);
  emit();
  setTimeout(() => dismiss(id), 5000);
}

const icons = { info: Info, ok: CheckCircle2, bad: XCircle } as const;
const toneCls = { info: "text-info", ok: "text-ok", bad: "text-bad" } as const;

export function Toaster() {
  const [list, setList] = React.useState<ToastItem[]>([]);
  React.useEffect(() => {
    listeners.add(setList);
    return () => {
      listeners.delete(setList);
    };
  }, []);
  return (
    <section aria-label="Notifications" aria-live="polite" className="pointer-events-none fixed right-0 bottom-0 z-[60] flex w-full max-w-sm flex-col gap-2 p-4">
      {list.map((t) => {
        const Icon = icons[t.tone];
        return (
          <div
            key={t.id}
            role={t.tone === "bad" ? "alert" : "status"}
            className="pointer-events-auto flex animate-fade-up items-start gap-3 rounded-lg border border-border bg-surface p-3.5 pr-2 shadow-lg"
          >
            <Icon className={cn("mt-0.5 size-4 shrink-0", toneCls[t.tone])} aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-medium text-fg">{t.title}</p>
              {t.description ? <p className="mt-0.5 text-[12px] leading-5 text-muted">{t.description}</p> : null}
            </div>
            <button type="button" onClick={() => dismiss(t.id)} aria-label="Dismiss" className="rounded p-1 text-subtle hover:bg-surface-2 hover:text-fg">
              <X className="size-3.5" aria-hidden />
            </button>
          </div>
        );
      })}
    </section>
  );
}
