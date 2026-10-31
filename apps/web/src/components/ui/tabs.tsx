"use client";

/**
 * WAI-ARIA tabs without a dependency: roving focus with ←/→/Home/End, `aria-selected`, `aria-controls`, inactive panels
 * unmounted. Same component names and props as before (Tabs, TabsList, TabsTrigger, TabsContent, SegmentList, SegmentTrigger).
 */
import * as React from "react";
import { cn } from "@/lib/utils";

type Ctx = { value: string; setValue: (v: string) => void; base: string };
const TabsCtx = React.createContext<Ctx | null>(null);
const useTabs = () => {
  const c = React.useContext(TabsCtx);
  if (!c) throw new Error("Tabs components must be inside <Tabs>");
  return c;
};

export function Tabs({
  defaultValue,
  value: controlled,
  onValueChange,
  className,
  children,
}: {
  defaultValue?: string;
  value?: string;
  onValueChange?: (v: string) => void;
  className?: string;
  children: React.ReactNode;
}) {
  const [inner, setInner] = React.useState(defaultValue ?? "");
  const value = controlled ?? inner;
  const base = React.useId();
  const setValue = (v: string) => {
    if (controlled === undefined) setInner(v);
    onValueChange?.(v);
  };
  return (
    <TabsCtx.Provider value={{ value, setValue, base }}>
      <div className={className}>{children}</div>
    </TabsCtx.Provider>
  );
}

function onListKey(e: React.KeyboardEvent<HTMLDivElement>) {
  const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
  if (!keys.includes(e.key)) return;
  const tabs = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="tab"]:not([disabled])'));
  const i = tabs.indexOf(document.activeElement as HTMLElement);
  if (i < 0) return;
  e.preventDefault();
  const n = tabs.length;
  const next = e.key === "Home" ? 0 : e.key === "End" ? n - 1 : e.key === "ArrowLeft" ? (i - 1 + n) % n : (i + 1) % n;
  tabs[next]!.focus();
  tabs[next]!.click();
}

function List({ className, children, label }: { className: string; children: React.ReactNode; label?: string }) {
  return (
    <div role="tablist" aria-label={label} onKeyDown={onListKey} className={className}>
      {children}
    </div>
  );
}

export function TabsList({ className, children, "aria-label": label }: { className?: string; children: React.ReactNode; "aria-label"?: string }) {
  return (
    <List label={label} className={cn("no-scrollbar flex items-center gap-1 overflow-x-auto border-b border-border", className)}>
      {children}
    </List>
  );
}

function Trigger({ value, className, children, disabled }: { value: string; className: string; children: React.ReactNode; disabled?: boolean }) {
  const t = useTabs();
  const active = t.value === value;
  return (
    <button
      type="button"
      role="tab"
      id={`${t.base}-tab-${value}`}
      aria-selected={active}
      aria-controls={`${t.base}-panel-${value}`}
      tabIndex={active ? 0 : -1}
      disabled={disabled}
      data-state={active ? "active" : "inactive"}
      onClick={() => t.setValue(value)}
      className={className}
    >
      {children}
    </button>
  );
}

export function TabsTrigger({ value, className, children, disabled }: { value: string; className?: string; children: React.ReactNode; disabled?: boolean }) {
  return (
    <Trigger
      value={value}
      disabled={disabled}
      className={cn(
        "relative -mb-px inline-flex h-9 shrink-0 items-center gap-1.5 border-b-2 border-transparent px-2.5 text-[13px] font-medium text-muted transition-[color,background-color,border-color,transform] duration-[var(--dur-hover)] ease-[var(--ease-out)] active:scale-[0.97] hover:text-fg data-[state=active]:border-accent data-[state=active]:text-fg [&_svg]:size-3.5",
        className,
      )}
    >
      {children}
    </Trigger>
  );
}

export function TabsContent({ value, className, children }: { value: string; className?: string; children: React.ReactNode }) {
  const t = useTabs();
  if (t.value !== value) return null;
  return (
    <div role="tabpanel" id={`${t.base}-panel-${value}`} aria-labelledby={`${t.base}-tab-${value}`} tabIndex={0} className={cn("pt-4 focus-visible:outline-none", className)}>
      {children}
    </div>
  );
}

export function SegmentList({ className, children, "aria-label": label }: { className?: string; children: React.ReactNode; "aria-label"?: string }) {
  return (
    <List label={label} className={cn("inline-flex rounded-md border border-border bg-surface-2 p-0.5", className)}>
      {children}
    </List>
  );
}

export function SegmentTrigger({ value, className, children }: { value: string; className?: string; children: React.ReactNode }) {
  return (
    <Trigger
      value={value}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-[5px] px-2.5 text-[12px] font-medium text-muted transition-[color,background-color,border-color,transform] duration-[var(--dur-hover)] ease-[var(--ease-out)] active:scale-[0.97] hover:text-fg data-[state=active]:bg-surface data-[state=active]:text-fg data-[state=active]:shadow-sm [&_svg]:size-3.5",
        className,
      )}
    >
      {children}
    </Trigger>
  );
}
