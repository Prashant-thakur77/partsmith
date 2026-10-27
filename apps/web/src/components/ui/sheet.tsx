"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;
export const SheetClose = DialogPrimitive.Close;
export const SheetTitle = DialogPrimitive.Title;
export const SheetDescription = DialogPrimitive.Description;

const sides = {
  right: "inset-y-0 right-0 h-dvh w-[min(420px,100vw)] border-l",
  left: "inset-y-0 left-0 h-dvh w-[min(320px,100vw)] border-r",
  bottom: "inset-x-0 bottom-0 max-h-[85dvh] w-full rounded-t-xl border-t",
} as const;

export function SheetContent({
  side = "right",
  className,
  children,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content> & { side?: keyof typeof sides }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/40 data-[state=open]:animate-fade-in" />
      <DialogPrimitive.Content
        className={cn(
          "fixed z-50 flex flex-col overflow-y-auto border-border bg-surface shadow-lg data-[state=open]:animate-fade-in",
          sides[side],
          className,
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close
          className="absolute top-3 right-3 inline-flex size-8 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg"
          aria-label="Close"
        >
          <X className="size-4" />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
