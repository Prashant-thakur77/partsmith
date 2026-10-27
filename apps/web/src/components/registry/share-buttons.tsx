"use client";

import { Link2, MessageCircle } from "lucide-react";
import { toast } from "../ui/toast";
import { Button } from "../ui/button";

/** Copy link + WhatsApp share (wa.me with text and the current URL, knob values included). */
export function ShareButtons({ title, verified }: { title: string; verified: boolean }) {
  const text = verified ? `${title} — verified replacement part on PartSmith` : `${title} — replacement part on PartSmith`;
  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={() => {
          void navigator.clipboard?.writeText(window.location.href);
          toast("Link copied", { description: "Includes the current knob values." });
        }}
      >
        <Link2 aria-hidden /> Copy link
      </Button>
      <Button
        variant="outline"
        size="sm"
        onClick={() => window.open(`https://wa.me/?text=${encodeURIComponent(`${text}: ${window.location.href}`)}`, "_blank", "noopener,noreferrer")}
      >
        <MessageCircle aria-hidden /> WhatsApp
      </Button>
    </>
  );
}
