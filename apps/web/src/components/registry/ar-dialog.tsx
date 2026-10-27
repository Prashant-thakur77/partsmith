"use client";

import { Rotate3D } from "lucide-react";
import * as React from "react";
import { Button } from "../ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "../ui/dialog";
import { Spinner } from "../ui/spinner";

declare module "react" {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    interface IntrinsicElements {
      "model-viewer": React.DetailedHTMLProps<React.HTMLAttributes<HTMLElement>, HTMLElement> & {
        src?: string;
        alt?: string;
        ar?: boolean;
        "ar-modes"?: string;
        "ar-scale"?: string;
        "ar-placement"?: string;
        "camera-controls"?: boolean;
        "touch-action"?: string;
        "shadow-intensity"?: string;
        exposure?: string;
      };
    }
  }
}

/** True-size AR (Quick Look / Scene Viewer / WebXR) from the part's GLB, which is in metres so `ar-scale="fixed"` is 1:1. */
export default function ArDialog({ glbUrl, title, initiallyOpen = true }: { glbUrl: string | null | undefined; title: string; initiallyOpen?: boolean }) {
  const [ready, setReady] = React.useState(false);
  const [open, setOpen] = React.useState(initiallyOpen);
  React.useEffect(() => {
    if (!open || ready) return;
    void import("@google/model-viewer").then(() => setReady(true));
  }, [open, ready]);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" disabled={!glbUrl}>
          <Rotate3D aria-hidden /> View at real size (AR)
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogTitle>View at real size</DialogTitle>
        <DialogDescription>On a phone, tap the AR button to place the part at 1:1 next to the broken original.</DialogDescription>
        <div className="relative aspect-square w-full overflow-hidden rounded-lg border border-border bg-[var(--viewer-bg)]">
          {ready && glbUrl ? (
            <model-viewer
              src={glbUrl}
              alt={`3D model of ${title}`}
              ar
              ar-modes="webxr scene-viewer quick-look"
              ar-scale="fixed"
              ar-placement="floor"
              camera-controls
              touch-action="pan-y"
              shadow-intensity="0.8"
              style={{ width: "100%", height: "100%" }}
            />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center">
              <Spinner label="Loading AR viewer" />
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
