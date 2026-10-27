import type { Metadata } from "next";
import { BenchClient } from "./bench-client";

export const metadata: Metadata = { title: "Results", description: "PartSmith-Bench: accuracy against synthetic ground truth, published reference-object specs and ruler-measured real parts." };

export default function BenchPage() {
  return <BenchClient />;
}
