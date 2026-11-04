"use client";

/**
 * A baked mesh in a box: only mounts three.js once near the screen and when the browser has WebGL, and says so plainly when
 * it cannot draw. With reduced motion it does not turn on its own; a drag still works.
 */
import dynamic from "next/dynamic";
import * as React from "react";
import { usePrefersReducedMotion, useInView } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { Skeleton } from "../ui/skeleton";

const Scene = dynamic(() => import("./baked-mesh-scene"), {
  ssr: false,
  loading: () => <Skeleton className="absolute inset-0 rounded-none" />,
});

function hasWebgl(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") ?? c.getContext("webgl"));
  } catch {
    return false;
  }
}

export function BakedMesh({
  file,
  sizeMm,
  label,
  className,
  turning = true,
  scale,
  view,
  poster,
}: {
  /** a baked `.bin` mesh, or the address of a part's view.json */
  file?: string | null;
  sizeMm?: number;
  /** what the picture shows, for people who cannot see it */
  label: string;
  className?: string;
  turning?: boolean;
  scale?: [number, number, number];
  view?: "iso" | "under";
  /** a still picture, shown until the 3D is ready and whenever it can't be drawn */
  poster?: string;
}) {
  const reduced = usePrefersReducedMotion();
  const { ref, seen } = useInView<HTMLDivElement>({ threshold: 0, rootMargin: "200px" });
  const [webgl, setWebgl] = React.useState(true);
  const [failed, setFailed] = React.useState(false);
  const [ready, setReady] = React.useState(false);
  React.useEffect(() => setWebgl(hasWebgl()), []);
  const broken = !webgl || failed;
  return (
    <div ref={ref} role="img" aria-label={label} className={cn("relative overflow-hidden", className)}>
      {poster && (broken || !ready) ? (
        // eslint-disable-next-line @next/next/no-img-element -- an API thumbnail behind the 3D view, already sized
        <img src={poster} alt="" className="absolute inset-0 size-full object-contain" loading="lazy" />
      ) : null}
      {broken ? (
        poster ? null : (
          <div className="absolute inset-0 flex items-center justify-center p-4 text-center text-[13px] text-muted">
            This browser can&apos;t draw the 3D model here.
          </div>
        )
      ) : seen && file ? (
        <Scene
          file={file}
          sizeMm={sizeMm}
          turning={turning && !reduced}
          scale={scale}
          view={view}
          onReady={() => setReady(true)}
          onError={() => setFailed(true)}
        />
      ) : poster ? null : (
        <Skeleton className="absolute inset-0 rounded-none" />
      )}
    </div>
  );
}
