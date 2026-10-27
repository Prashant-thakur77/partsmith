import type { Metadata } from "next";
import { Suspense } from "react";
import { PartsClient } from "./parts-client";

export const metadata: Metadata = {
  title: "Registry",
  description: "Search verified parametric replacement parts with typed knobs, verification records and provenance.",
};

export default function PartsPage() {
  return (
    <Suspense>
      <PartsClient />
    </Suspense>
  );
}
