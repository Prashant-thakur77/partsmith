import type { Metadata } from "next";
import { DemoClient } from "./demo-client";

export const metadata: Metadata = { title: "Synthetic sample", description: "Run PartSmith on a bundled synthetic sample, labelled as such." };

export default function DemoPage() {
  return <DemoClient />;
}
