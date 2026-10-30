"use client";

import { Check, CornerUpLeft, ImagePlus, MapPin, X } from "lucide-react";
import * as React from "react";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Spinner } from "@/components/ui/spinner";
import { TranscribeButton } from "@/components/voice-button";
import { cn } from "@/lib/utils";

/** A pasted or chosen image on its way to (or already in) the API's attachment store. */
export type Attachment = { id: number; preview: string; key: string | null; error: string | null };

export const MAX_ATTACHMENTS = 4;

/** Image files from a paste or drop (screenshots arrive as `image/png` items). */
export function imagesFrom(data: DataTransfer | null): File[] {
  if (!data) return [];
  const files = [...data.files].filter((f) => f.type.startsWith("image/"));
  if (files.length) return files;
  return [...data.items].filter((i) => i.kind === "file" && i.type.startsWith("image/")).flatMap((i) => (i.getAsFile() ? [i.getAsFile()!] : []));
}

/**
 * The reviewer's controls, pinned to the bottom of the screen so they never scroll away: how many pins, a note (paste a
 * screenshot straight into it), attached pictures, and the three decisions with their keys.
 */
export function DecisionBar({
  pins,
  note,
  onNote,
  why,
  onWhy,
  noteRef,
  attachments,
  onAddImages,
  onRemoveAttachment,
  onAccept,
  onImprove,
  onReject,
  pending,
  hint,
  nextRound,
  verified,
}: {
  pins: number;
  note: string;
  onNote: (v: string) => void;
  why: string;
  onWhy: (v: string) => void;
  noteRef: React.RefObject<HTMLTextAreaElement | null>;
  attachments: Attachment[];
  onAddImages: (files: File[]) => void;
  onRemoveAttachment: (id: number) => void;
  onAccept: () => void;
  onImprove: () => void;
  onReject: () => void;
  pending: "accept" | "improve" | "reject" | null;
  hint: string | null;
  nextRound: number;
  /** The code passed it: accepting is the usual step. Otherwise improving is, and accepting is the exception. */
  verified: boolean;
}) {
  const file = React.useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = React.useState(false);
  const uploading = attachments.some((a) => !a.key && !a.error);
  const full = attachments.length >= MAX_ATTACHMENTS;
  return (
    <div
      role="region"
      aria-label="Your decision"
      className={cn(
        "z-20 space-y-2 rounded-lg border border-border bg-bg/95 px-3 py-2.5 md:sticky md:bottom-0 md:-mx-1 md:rounded-b-none md:border-b-0 shadow-[0_-8px_24px_-12px_rgba(0,0,0,0.25)] backdrop-blur",
        dragging && "ring-2 ring-accent",
      )}
      onDragOver={(e) => {
        if (imagesFrom(e.dataTransfer).length || [...e.dataTransfer.types].includes("Files")) {
          e.preventDefault();
          setDragging(true);
        }
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        const imgs = imagesFrom(e.dataTransfer);
        setDragging(false);
        if (!imgs.length) return;
        e.preventDefault();
        onAddImages(imgs);
      }}
    >
      <div className="flex flex-wrap items-start gap-2">
        <span
          className={cn("inline-flex h-9 shrink-0 items-center gap-1 rounded-md border px-2 text-[12px] tnum", pins ? "border-bad-border bg-bad-soft text-fg" : "border-border text-muted")}
          title={pins ? undefined : "Click the photo where something is wrong"}
        >
          <MapPin className="size-3.5" aria-hidden />
          {pins ? `${pins} pin${pins === 1 ? "" : "s"}` : "no pins"}
        </span>
        <textarea
          id="review-note"
          ref={noteRef}
          value={note}
          maxLength={600}
          rows={1}
          aria-label="Note for the builder"
          placeholder="What should change? Paste a screenshot here (Ctrl+V) or drop a picture"
          onChange={(e) => onNote(e.target.value)}
          onPaste={(e) => {
            const imgs = imagesFrom(e.clipboardData);
            if (!imgs.length) return;
            e.preventDefault();
            onAddImages(imgs);
          }}
          className="field-sizing-content max-h-32 min-h-9 min-w-[12rem] flex-1 resize-none rounded-md border border-border bg-surface px-3 py-2 text-[13px] focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        />
        <TranscribeButton label="Speak" onText={(t) => onNote(note.trim() ? `${note.trim()} ${t}` : t)} />
        <Button type="button" variant="outline" size="sm" className="h-9 shrink-0" disabled={full} onClick={() => file.current?.click()} aria-label="Attach a picture" title="Attach a picture">
          <ImagePlus aria-hidden />
        </Button>
        <input
          ref={file}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          multiple
          hidden
          onChange={(e) => {
            const imgs = [...(e.target.files ?? [])];
            e.target.value = "";
            if (imgs.length) onAddImages(imgs);
          }}
        />
        <div className="flex shrink-0 items-center gap-2">
          <Button variant={verified ? "solid" : "outline"} size="sm" className="h-9" disabled={!!pending || uploading} onClick={onAccept}>
            {pending === "accept" ? <Spinner label="Saving" /> : <Check aria-hidden />} {verified ? "Accept" : "Accept anyway"}{" "}
            <Kbd className="ml-1 hidden sm:inline-flex">A</Kbd>
          </Button>
          <Button
            variant={verified ? "outline" : "solid"}
            size="sm"
            className="h-9"
            disabled={!!pending || uploading}
            onClick={onImprove}
            title={`Starts round ${nextRound} from this model with your pins, note and pictures`}
          >
            {pending === "improve" ? <Spinner label="Sending" /> : <CornerUpLeft aria-hidden />} Improve <Kbd className="ml-1 hidden sm:inline-flex">I</Kbd>
          </Button>
          <Button variant="outline" size="sm" className="h-9" disabled={!!pending} onClick={onReject}>
            <X aria-hidden /> Reject <Kbd className="ml-1 hidden sm:inline-flex">R</Kbd>
          </Button>
        </div>
      </div>
      <input
        value={why}
        maxLength={500}
        onChange={(e) => onWhy(e.target.value)}
        aria-label="Why it matters"
        placeholder="Why it matters (optional, kept in the feedback log): e.g. it must take an M3 screw so the cover closes"
        className="h-8 w-full rounded-md border border-border bg-surface px-3 text-[12.5px] focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
      />
      {attachments.length ? (
        <ul className="flex flex-wrap gap-2" aria-label="Attached pictures">
          {attachments.map((a, i) => (
            <li key={a.id} className="relative">
              {/* eslint-disable-next-line @next/next/no-img-element -- a local preview of the attached picture */}
              <img
                src={a.preview}
                alt={`Attached picture ${i + 1}`}
                className={cn("size-14 rounded-md border object-cover", a.error ? "border-bad opacity-60" : "border-border", !a.key && !a.error && "opacity-60")}
              />
              {!a.key && !a.error ? (
                <span className="absolute inset-0 flex items-center justify-center">
                  <Spinner label="Uploading" />
                </span>
              ) : null}
              {a.error ? <span className="absolute inset-x-0 bottom-0 truncate rounded-b-md bg-bad px-1 text-[10px] text-white">{a.error}</span> : null}
              <button
                type="button"
                onClick={() => onRemoveAttachment(a.id)}
                aria-label={`Remove attached picture ${i + 1}`}
                className="absolute -top-1.5 -right-1.5 flex size-5 items-center justify-center rounded-full border border-border bg-surface text-muted shadow hover:text-fg"
              >
                <X className="size-3" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {hint || uploading ? (
        <p className={cn("text-[12px]", hint ? "text-warn" : "text-subtle")} role={hint ? "alert" : undefined}>
          {hint ?? "Uploading the picture…"}
        </p>
      ) : null}
    </div>
  );
}
