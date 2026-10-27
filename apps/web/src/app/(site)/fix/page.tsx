import type { Metadata } from "next";
import { FixClient } from "./fix-client";

export const metadata: Metadata = {
  title: "Fix a part",
  description: "Calibrate your screen, photograph the broken part on the mat, and start a verified fix job.",
};

export default function FixPage() {
  return <FixClient />;
}
