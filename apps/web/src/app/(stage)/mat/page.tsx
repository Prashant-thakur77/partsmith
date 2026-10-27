import type { Metadata } from "next";
import { Suspense } from "react";
import { MatClient } from "./mat-client";

export const metadata: Metadata = { title: "Screen mat", description: "A full-screen ArUco calibration mat drawn at true 1:1 size." };

export default function MatPage() {
  return (
    <Suspense>
      <MatClient />
    </Suspense>
  );
}
