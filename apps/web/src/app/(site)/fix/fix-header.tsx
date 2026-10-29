"use client";

import { FlaskConical } from "lucide-react";
import Link from "next/link";
import { Container } from "@/components/layout/page";
import { PhoneHandoff, PhoneJobWatcher } from "@/components/phone-handoff";
import { Button } from "@/components/ui/button";
import { useMediaQuery } from "@/lib/hooks";
import { LangToggle, useT } from "@/lib/i18n";

export function FixHeader() {
  const { t } = useT();
  const wide = useMediaQuery("(min-width: 768px)");
  return (
    <Container className="space-y-6 pt-8 sm:pt-10">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-2xl space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <div className="text-[12px] font-medium uppercase tracking-[0.08em] text-accent-text">{t("fix.eyebrow")}</div>
            <LangToggle />
          </div>
          <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.025em] sm:text-[34px]">{t("fix.title")}</h1>
          <p className="text-[15px] leading-6 text-muted">{t("fix.lead")}</p>
          <p className="text-[12.5px] leading-5 text-subtle">{t("fix.privacy")}</p>
          <Button asChild variant="outline" className="mt-2">
            <Link href="/jobs/demo">
              <FlaskConical aria-hidden /> {t("fix.trySample")}
            </Link>
          </Button>
        </div>
        <PhoneHandoff path="/fix" compact />
      </div>
      {wide ? <PhoneJobWatcher /> : null}
    </Container>
  );
}
