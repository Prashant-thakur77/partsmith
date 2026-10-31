/**
 * Picking which stored runs to show first, from the `/replays` list alone (no ids typed here). Pure, so `node --test`
 * can load it.
 */
import type { Replay } from "./api-types";

export type ReplayPick = { replay: Replay; why: string };

/** "· review round 4" in a replay title → 4. */
export function reviewRound(title: string): number | null {
  const m = /review round (\d+)/i.exec(title);
  return m ? Number(m[1]) : null;
}

/** "Hinge leaf (synthetic, clean) · review round 4" → "Hinge leaf · review round 4" (presets and origin dropped). */
export function replayTitle(title: string, split: (t: string) => { title: string }): string {
  const n = reviewRound(title);
  const base = split(title.replace(/\s*·\s*review round \d+\s*$/i, "")).title;
  return n != null ? `${base} · review round ${n}` : base;
}

/**
 * Card word for a stored run's verdict. The list only carries `verified`; a run that is not verified but has a max error
 * produced a model, which is what the pipeline calls best effort. With no error recorded there was no model to compare.
 */
export function replayVerdict(r: Pick<Replay, "verified" | "max_error_mm">): "verified" | "best effort" | "no model" {
  if (r.verified) return "verified";
  return r.max_error_mm != null ? "best effort" : "no model";
}

/**
 * Up to three instructive runs, in this order:
 *  1. a verified run that needed fixing (most rounds, then the smallest error);
 *  2. the latest round of a human review chain (the highest "review round N"), verified first;
 *  3. a near miss: best effort after several rounds, with the smallest error (the check is strict).
 * Everything else, in the API's order, is `rest`.
 */
export function curateReplays(replays: readonly Replay[]): { featured: ReplayPick[]; rest: Replay[] } {
  const used = new Set<string>();
  const featured: ReplayPick[] = [];
  const take = (r: Replay | undefined, why: string) => {
    if (!r || used.has(r.id)) return;
    used.add(r.id);
    featured.push({ replay: r, why });
  };
  const err = (r: Replay) => r.max_error_mm ?? Number.POSITIVE_INFINITY;

  const fixed = replays
    .filter((r) => r.verified && reviewRound(r.title) == null)
    .sort((a, b) => b.iterations - a.iterations || err(a) - err(b))[0];
  take(fixed, fixed && fixed.iterations > 1 ? `Verified after ${fixed.iterations} rounds` : "Verified on the first build");

  const reviewed = replays
    .filter((r) => reviewRound(r.title) != null)
    .sort((a, b) => Number(b.verified) - Number(a.verified) || reviewRound(b.title)! - reviewRound(a.title)!)[0];
  take(reviewed, reviewed ? `Sent back in review (a scripted test review, not a person); round ${reviewRound(reviewed.title)}` : "");

  const nearMiss = replays
    .filter((r) => !r.verified && r.max_error_mm != null && r.iterations > 1 && reviewRound(r.title) == null && !used.has(r.id))
    .sort((a, b) => err(a) - err(b))[0];
  take(nearMiss, `Best effort after ${nearMiss?.iterations ?? 0} rounds: the check said not yet`);

  return { featured, rest: replays.filter((r) => !used.has(r.id)) };
}
