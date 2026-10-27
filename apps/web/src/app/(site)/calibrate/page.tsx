import type { Metadata } from "next";
import { Suspense } from "react";
import { CalibrateClient } from "./calibrate-client";

export const metadata: Metadata = {
  title: "Calibrate screen",
  description: "Match a bank or ID card on screen once so PartSmith can draw the measuring mat at true 1:1 size.",
};

export default function CalibratePage() {
  return (
    <Suspense>
      <CalibrateClient />
    </Suspense>
  );
}
