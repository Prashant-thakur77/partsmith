/** The words the site explains wherever they appear, in one plain sentence each. Numbers stay with the page that measured them. */
export const GLOSSARY = {
  hausdorff: {
    title: "Hausdorff (the gap)",
    text: "The biggest gap between the photo's outline and the model's outline, in millimetres. Smaller is better.",
  },
  iou: {
    title: "IoU",
    text: "How much the two outlines overlap: 1 means they cover exactly the same area, 0 means they do not touch.",
  },
  parametric: {
    title: "Parametric",
    text: "The part is a small program with named sizes, called knobs. Change a knob and it rebuilds with its holes in the right places, unlike stretching a mesh.",
  },
  verifier: {
    title: "Verifier",
    text: "Plain code with no AI in it. It lays the model over the photo and measures the gap, and only it can mark a part verified.",
  },
  mat: {
    title: "Screen mat",
    text: "A pattern of black squares your screen draws at true size, after a one-time match against a bank card. The squares give the photo its scale.",
  },
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;
export const GLOSSARY_KEYS = Object.keys(GLOSSARY) as GlossaryKey[];

const WORDS: readonly (readonly [RegExp, GlossaryKey])[] = [
  [/\bHausdorff\b|\b(?:outline|largest) gap\b/i, "hausdorff"],
  [/\bIoU\b/, "iou"],
  [/\bparametric\b/i, "parametric"],
  [/\bverifier(?:'s)?\b/i, "verifier"],
  [/\b(?:screen )?mat\b/i, "mat"],
];

export type TermPiece = string | { key: GlossaryKey; word: string };

/** Splits a sentence around the first use of each glossary word, so a view can explain it once and leave the rest as text. */
export function splitTerms(text: string): TermPiece[] {
  const hits = WORDS.flatMap(([re, key]) => {
    const m = re.exec(text);
    return m ? [{ at: m.index, word: m[0], key }] : [];
  }).sort((a, b) => a.at - b.at);
  const pieces: TermPiece[] = [];
  let from = 0;
  for (const hit of hits) {
    if (hit.at < from) continue;
    if (hit.at > from) pieces.push(text.slice(from, hit.at));
    pieces.push({ key: hit.key, word: hit.word });
    from = hit.at + hit.word.length;
  }
  if (from < text.length) pieces.push(text.slice(from));
  return pieces;
}
