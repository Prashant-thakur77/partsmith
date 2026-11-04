import type { Metadata } from "next";
import { CompareClient } from "./compare-client";

export const metadata: Metadata = {
  title: "Compare",
  description: "Stretch a mesh against turning a knob on the same real part, and how PartSmith differs from what people use today.",
};

export default function ComparePage() {
  return <CompareClient />;
}
