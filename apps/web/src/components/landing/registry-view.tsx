import { Boxes } from "lucide-react";
import Link from "next/link";
import type { PartCard as PartCardT } from "@/lib/api-types";
import { PartCard, PartCardSkeleton } from "../registry/part-card";
import { EmptyState } from "../ui/empty-state";

export function RegistryView({ items }: { items: PartCardT[] | null }) {
  if (items && items.length === 0)
    return (
      <EmptyState
        icon={Boxes}
        title="No parts published yet"
        action={
          <>
            <Link href="/jobs/demo" className="text-[13px] font-medium text-accent-text hover:underline">
              Try a sample
            </Link>
            <span aria-hidden className="text-subtle">·</span>
            <Link href="/fix" className="text-[13px] font-medium text-accent-text hover:underline">
              Fix a part
            </Link>
          </>
        }
      >
        A part shows up here once its model passes the photo check.
      </EmptyState>
    );
  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
      {items ? items.map((p) => <PartCard key={p.slug} part={p} />) : Array.from({ length: 4 }, (_, i) => <PartCardSkeleton key={i} />)}
    </div>
  );
}
