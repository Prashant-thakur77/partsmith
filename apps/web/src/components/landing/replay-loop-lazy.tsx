"use client";

import dynamic from "next/dynamic";
import * as React from "react";

const ReplayLoop = dynamic(() => import("./replay-loop").then((m) => m.ReplayLoop), {
  ssr: false,
  loading: () => <Frame />,
});

/** The player's outline before it mounts, at the loaded player's height (header bar, picture box, caption row). */
function Frame() {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface" aria-hidden>
      <div className="h-[73px] border-b border-border sm:h-[45px]" />
      <div className="aspect-[16/10] bg-surface-2 sm:aspect-[16/7]" />
      <div className="h-14" />
    </div>
  );
}

/** Mounts the replay loop only when it scrolls near the viewport, so it never weighs on the first paint. */
export function ReplayLoopLazy(props: { id?: string | null; onStep?: (frame: string, chartStep: number) => void }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [show, setShow] = React.useState(false);
  React.useEffect(() => {
    const el = ref.current;
    if (!el || show) return;
    const io = new IntersectionObserver(([e]) => e?.isIntersecting && setShow(true), { rootMargin: "300px" });
    io.observe(el);
    return () => io.disconnect();
  }, [show]);
  return <div ref={ref}>{show ? <ReplayLoop {...props} /> : <Frame />}</div>;
}
