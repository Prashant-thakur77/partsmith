import type { Metadata } from "next";
import { Suspense } from "react";
import { PlaygroundClient } from "./playground-client";

export const metadata: Metadata = {
  title: "Playground",
  description: "Every PartSmith part is a program with knobs. Pick an example, drag its knobs, see the CadQuery program change, and download it at your values.",
};

export default function PlaygroundPage() {
  return (
    <Suspense>
      <PlaygroundClient />
    </Suspense>
  );
}
