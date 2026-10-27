import type { Metadata } from "next";
import { I18nRegion } from "@/lib/i18n";
import { FixClient } from "./fix-client";
import { FixHeader } from "./fix-header";

export const metadata: Metadata = {
  title: "Fix a part",
  description: "Calibrate your screen, photograph the broken part on the mat, and start a verified fix job.",
};

export default function FixPage() {
  return (
    <I18nRegion>
      <FixHeader />
      <div className="h-8" aria-hidden />
      <FixClient />
    </I18nRegion>
  );
}
