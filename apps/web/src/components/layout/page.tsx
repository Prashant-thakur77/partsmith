import * as React from "react";
import { cn } from "@/lib/utils";

export function Container({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("mx-auto w-full max-w-[1200px] px-4 sm:px-6", className)} {...props} />;
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  className,
  children,
}: {
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className={cn("border-b border-border bg-surface/40", className)}>
      <Container className="flex flex-col gap-5 py-10 sm:py-12 md:flex-row md:items-end md:justify-between">
        <div className="max-w-2xl space-y-3">
          {eyebrow ? <div className="text-[12px] font-medium uppercase tracking-[0.08em] text-accent-text">{eyebrow}</div> : null}
          <h1 className="text-[28px] leading-[1.15] font-semibold tracking-[-0.025em] text-fg sm:text-[34px]">{title}</h1>
          {description ? <p className="text-[15px] leading-6 text-muted">{description}</p> : null}
          {children}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
      </Container>
    </div>
  );
}

export function Section({
  title,
  description,
  actions,
  className,
  children,
  id,
}: {
  title?: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
  id?: string;
}) {
  return (
    <section id={id} className={cn("min-w-0 space-y-5", className)} aria-labelledby={id && title ? `${id}-title` : undefined}>
      {title || actions ? (
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="space-y-1">
            {title ? (
              <h2 id={id ? `${id}-title` : undefined} className="text-lg font-semibold tracking-tight text-fg">
                {title}
              </h2>
            ) : null}
            {description ? <p className="max-w-2xl text-[14px] leading-6 text-muted">{description}</p> : null}
          </div>
          {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}

/** Label/value row for fact tables. */
export function Fact({ label, children, className }: { label: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-4 border-b border-border py-2.5 last:border-b-0", className)}>
      <dt className="text-[13px] text-muted">{label}</dt>
      <dd className="text-right text-[13px] text-fg">{children}</dd>
    </div>
  );
}
