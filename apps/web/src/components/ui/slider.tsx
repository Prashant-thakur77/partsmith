"use client";

import * as SliderPrimitive from "@radix-ui/react-slider";
import * as React from "react";
import { cn } from "@/lib/utils";

export function Slider({ className, ...props }: React.ComponentProps<typeof SliderPrimitive.Root>) {
  return (
    <SliderPrimitive.Root className={cn("relative flex h-5 w-full touch-none items-center select-none", className)} {...props}>
      <SliderPrimitive.Track className="relative h-1 grow overflow-hidden rounded-full bg-surface-3">
        <SliderPrimitive.Range className="absolute h-full bg-fg" />
      </SliderPrimitive.Track>
      {(props.value ?? props.defaultValue ?? [0]).map((_, i) => (
        <SliderPrimitive.Thumb
          key={i}
          aria-label={props["aria-label"]}
          className="block size-4 rounded-full border-2 border-fg bg-surface shadow-sm transition-transform hover:scale-110 focus-visible:scale-110 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        />
      ))}
    </SliderPrimitive.Root>
  );
}
