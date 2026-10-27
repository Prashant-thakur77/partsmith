"use client";

import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as React from "react";
import { cn } from "@/lib/utils";

export const Tabs = TabsPrimitive.Root;

export function TabsList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      className={cn("no-scrollbar flex items-center gap-1 overflow-x-auto border-b border-border", className)}
      {...props}
    />
  );
}

export function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "relative -mb-px inline-flex h-9 shrink-0 items-center gap-1.5 border-b-2 border-transparent px-2.5 text-[13px] font-medium text-muted transition-colors hover:text-fg data-[state=active]:border-accent data-[state=active]:text-fg [&_svg]:size-3.5",
        className,
      )}
      {...props}
    />
  );
}

export function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content className={cn("pt-4 focus-visible:outline-none", className)} {...props} />;
}

/** Pill-style segmented control built on Radix tabs semantics (use for small view switches). */
export function SegmentList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return <TabsPrimitive.List className={cn("inline-flex rounded-md border border-border bg-surface-2 p-0.5", className)} {...props} />;
}

export function SegmentTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-[5px] px-2.5 text-[12px] font-medium text-muted transition-colors hover:text-fg data-[state=active]:bg-surface data-[state=active]:text-fg data-[state=active]:shadow-sm [&_svg]:size-3.5",
        className,
      )}
      {...props}
    />
  );
}
