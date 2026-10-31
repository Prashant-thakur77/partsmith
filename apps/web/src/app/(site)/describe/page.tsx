import type { Metadata } from "next";
import { Suspense } from "react";
import { DescribeClient } from "./describe-client";

export const metadata: Metadata = {
  title: "Describe a part",
  description: "Type or say what you need, with your numbers. PartSmith picks a part program, sets its knobs, builds it and checks every number you gave against the model.",
};

export default function DescribePage() {
  return (
    <Suspense>
      <DescribeClient />
    </Suspense>
  );
}
