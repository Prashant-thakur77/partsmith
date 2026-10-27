"use client";

import { Rotate3D } from "lucide-react";
import * as React from "react";
import { Button } from "../ui/button";

// The dialog (Radix) and @google/model-viewer load only when someone asks for AR.
const ArDialog = React.lazy(() => import("./ar-dialog"));

export function ArView({ glbUrl, title }: { glbUrl: string | null | undefined; title: string }) {
  const [wanted, setWanted] = React.useState(false);
  if (wanted)
    return (
      <React.Suspense
        fallback={
          <Button variant="outline" size="sm" disabled>
            <Rotate3D aria-hidden /> View at real size (AR)
          </Button>
        }
      >
        <ArDialog glbUrl={glbUrl} title={title} />
      </React.Suspense>
    );
  return (
    <Button variant="outline" size="sm" disabled={!glbUrl} onClick={() => setWanted(true)} aria-haspopup="dialog">
      <Rotate3D aria-hidden /> View at real size (AR)
    </Button>
  );
}
