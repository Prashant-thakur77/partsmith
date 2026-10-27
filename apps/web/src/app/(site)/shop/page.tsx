import type { Metadata } from "next";
import { Suspense } from "react";
import { ShopClient } from "./shop-client";

export const metadata: Metadata = { title: "Repair shops", description: "Batch mode for repair shops: one batch per day, a line per customer, job statuses and a printable job sheet." };

export default function ShopPage() {
  return (
    <Suspense>
      <ShopClient />
    </Suspense>
  );
}
