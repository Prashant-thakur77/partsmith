"use client";

import * as ToastPrimitive from "@radix-ui/react-toast";
import { CheckCircle2, Info, XCircle } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

type ToastItem = { id: number; title: string; description?: string; tone: "info" | "ok" | "bad" };
type Listener = (items: ToastItem[]) => void;

let items: ToastItem[] = [];
let nextId = 1;
const listeners = new Set<Listener>();
const emit = () => listeners.forEach((l) => l(items));

/** Show a toast from anywhere (client side). */
export function toast(title: string, opts: { description?: string; tone?: ToastItem["tone"] } = {}): void {
  items = [...items, { id: nextId++, title, description: opts.description, tone: opts.tone ?? "info" }].slice(-4);
  emit();
}

function dismiss(id: number) {
  items = items.filter((t) => t.id !== id);
  emit();
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
    <ToastPrimitive.Provider swipeDirection="right" duration={5000}>
      {list.map((t) => {
        const Icon = icons[t.tone];
        return (
          <ToastPrimitive.Root
            key={t.id}
            onOpenChange={(open) => !open && dismiss(t.id)}
            className="flex items-start gap-3 rounded-lg border border-border bg-surface p-3.5 pr-4 shadow-lg data-[state=open]:animate-fade-up data-[swipe=end]:animate-fade-in"
          >
            <Icon className={cn("mt-0.5 size-4 shrink-0", toneCls[t.tone])} aria-hidden />
            <div className="min-w-0">
              <ToastPrimitive.Title className="text-[13px] font-medium text-fg">{t.title}</ToastPrimitive.Title>
              {t.description ? (
                <ToastPrimitive.Description className="mt-0.5 text-[12px] leading-5 text-muted">{t.description}</ToastPrimitive.Description>
              ) : null}
            </div>
          </ToastPrimitive.Root>
        );
      })}
      <ToastPrimitive.Viewport className="fixed right-0 bottom-0 z-[60] flex w-full max-w-sm flex-col gap-2 p-4 outline-none" />
    </ToastPrimitive.Provider>
  );
}
