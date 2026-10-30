import type { Metadata } from "next";
import { Suspense } from "react";
import { ReviewClient } from "./review-client";

export const metadata: Metadata = { title: "Review", description: "A person accepts, sends back with pins, or rejects every finished fix. The measurements still decide pass or fail." };

export default function ReviewPage() {
  return (
    <Suspense>
      <ReviewClient />
    </Suspense>
  );
}
