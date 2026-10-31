import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { cn } from "@/lib/utils";

export const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium transition-[background-color,border-color,color,box-shadow,transform,opacity] duration-[var(--dur-hover)] ease-[var(--ease-out)] select-none disabled:pointer-events-none disabled:opacity-50 active:translate-y-px active:scale-[0.985] [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "bg-accent text-accent-fg shadow-sm hover:bg-accent-hover hover:shadow-md",
        solid: "bg-inverse text-inverse-fg shadow-sm hover:opacity-90",
        outline: "border border-border-strong bg-surface text-fg shadow-sm hover:border-ink/50 hover:bg-surface-2",
        ghost: "text-fg hover:bg-surface-2",
        subtle: "bg-surface-2 text-fg hover:bg-surface-3",
        danger: "bg-bad text-white hover:opacity-90",
        link: "h-auto px-0 text-accent-text underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-8 px-3 text-[13px] [&_svg]:size-3.5",
        md: "h-9 px-4 text-sm [&_svg]:size-4",
        lg: "h-11 px-5 text-[15px] [&_svg]:size-4",
        icon: "size-9 [&_svg]:size-4",
        "icon-sm": "size-8 [&_svg]:size-3.5",
      },
    },
    defaultVariants: { variant: "outline", size: "md" },
  },
);

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean };

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, asChild = false, type, ...props },
  ref,
) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      {...(asChild ? {} : { type: type ?? "button" })}
      {...props}
    />
  );
});
