"use client";

/**
 * The demo film as a picture with a play button. YouTube is contacted only after the press, then through its privacy-enhanced
 * host, so opening a page sends nothing to a third party.
 */
import { ExternalLink, Play } from "lucide-react";
import Image from "next/image";
import * as React from "react";
import { FILM_URL, filmEmbedUrl } from "@/lib/site-links";
import { cn } from "@/lib/utils";

export function FilmEmbed({ className }: { className?: string }) {
  const [playing, setPlaying] = React.useState(false);
  const src = filmEmbedUrl(FILM_URL);
  if (!src) return null;
  return (
    <figure className={cn("space-y-2", className)}>
      <div className="relative aspect-video overflow-hidden rounded-xl border border-border bg-inverse shadow-md">
        {playing ? (
          <iframe
            src={src}
            title="PartSmith demo film"
            className="absolute inset-0 size-full"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
            allowFullScreen
            referrerPolicy="strict-origin-when-cross-origin"
          />
        ) : (
          <button
            type="button"
            onClick={() => setPlaying(true)}
            className="group absolute inset-0 size-full cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            aria-label="Play the PartSmith demo film (loads YouTube)"
          >
            <Image src="/film/poster.jpg" alt="" fill sizes="(max-width: 1024px) 100vw, 640px" className="object-cover" unoptimized />
            <span className="absolute inset-0 flex items-center justify-center bg-black/10 transition-colors group-hover:bg-black/25">
              <span className="flex size-[72px] items-center justify-center rounded-full bg-accent text-accent-fg shadow-lg transition-transform group-hover:scale-105 motion-reduce:transform-none">
                <Play className="ml-1 size-8 fill-current" aria-hidden />
              </span>
            </span>
          </button>
        )}
      </div>
      <figcaption className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[12px] text-muted">
        <span>The demo film. YouTube loads only after you press play. Runs and photos in it are labelled on screen.</span>
        <a href={FILM_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-fg">
          Open on YouTube <ExternalLink className="size-3" aria-hidden />
        </a>
      </figcaption>
    </figure>
  );
}
