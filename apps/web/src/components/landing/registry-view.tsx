import { Boxes } from "lucide-react";
import type { PartCard as PartCardT } from "@/lib/api-types";
import { PartCard, PartCardSkeleton } from "../registry/part-card";
import { EmptyState } from "../ui/empty-state";

export function RegistryView({ items }: { items: PartCardT[] | null }) {
  if (items && items.length === 0)
    return (
      <EmptyState icon={Boxes} title="The registry is empty">
        Verified parts appear here as soon as the first fix job passes.
      </EmptyState>
    );
  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
      {items ? items.map((p) => <PartCard key={p.slug} part={p} />) : Array.from({ length: 4 }, (_, i) => <PartCardSkeleton key={i} />)}
    </div>
  );
}
