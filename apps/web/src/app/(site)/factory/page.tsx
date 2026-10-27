import type { Metadata } from "next";
import { Suspense } from "react";
import { SteerClient } from "./steer-client";

export const metadata: Metadata = { title: "Factory", description: "One-line brief to a planned family of parts, built and verified by agents, approved by a human." };

export default function SteerPage() {
  return (
    <Suspense>
      <SteerClient />
    </Suspense>
  );
}
