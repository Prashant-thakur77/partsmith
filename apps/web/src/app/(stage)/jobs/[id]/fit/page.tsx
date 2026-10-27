import type { Metadata } from "next";
import { Suspense } from "react";
import { FitClient } from "./fit-client";

export const metadata: Metadata = { title: "Screen fit check", robots: { index: false } };

export default async function FitPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Suspense>
      <FitClient id={decodeURIComponent(id)} />
    </Suspense>
  );
}
