/**
 * The eight steps on /how, each with the recorded run's real artifact, plain words and the reason that step can't be
 * faked. Pictures are files saved from the run; numbers come from public/deck/data.json, which scripts build from the
 * stored run and reports.
 */
import { z } from "zod/mini";

export const FlowDataSchema = z.object({
  limit_mm: z.number(),
  bypass: z.object({ attempts: z.number(), blocked: z.number() }),
  /** The colour-prompt test and the later run measured from SAM 3.1's mask, once the deck data has them. */
  sam_fix: z.nullish(z.object({ photos: z.number(), old: z.number(), new: z.number(), run_id: z.string() })),
  run: z.object({
    id: z.string(),
    params: z.array(z.string()),
    usd: z.number(),
    minutes_to_file: z.number(),
    print_minutes: z.number(),
    inr: z.number(),
    rounds_detail: z.array(
      z.object({
        round: z.number(),
        error_mm: z.number(),
        iou: z.number(),
        edits: z.array(z.object({ param: z.string(), from: z.number(), to: z.number() })),
      }),
    ),
  }),
});
export type FlowData = z.output<typeof FlowDataSchema>;

export async function fetchFlowData(signal?: AbortSignal): Promise<FlowData> {
  const res = await fetch("/deck/data.json", { signal });
  if (!res.ok) throw new Error(`The run's numbers did not load (${res.status}).`);
  return FlowDataSchema.parse(await res.json());
}

export type FlowImage = { src: string; alt: string; caption: string };
export type FlowLink = { href: string; label: string };
export type FlowStep = {
  id: string;
  /** The step's name on its button. */
  short: string;
  title: string;
  plain: string;
  /** One line: why this step can't be faked. */
  proof: string;
  images: FlowImage[];
  links: FlowLink[];
  /** The run's numbers belong on this step (`stepFacts`), so it says so when they don't load. */
  numbers?: boolean;
};

const img = (name: string) => `/deck/img/${name}.jpg`;

export const FLOW_STEPS: readonly FlowStep[] = [
  {
    id: "photo",
    short: "Photo",
    title: "A photo on the screen mat",
    plain: "Open the mat on a laptop or tablet, lay the broken part on it and take one photo from above. The black squares around the edge are drawn at true size.",
    proof: "Code's capture gate checks the markers, blur, tilt and glare before any model is asked, and turns away a photo it can't trust.",
    images: [{ src: img("flow-photo"), alt: "An orange battery cover lying on the screen mat, with black square markers around the edge, seen at an angle.", caption: "The run's top photo: a rendered sample, not a phone capture." }],
    links: [
      { href: "/mat", label: "Screen mat" },
      { href: "/calibrate", label: "Calibrate your screen" },
    ],
  },
  {
    id: "scale",
    short: "True scale",
    title: "Code flattens the photo to true scale",
    plain: "Code finds the markers, works out how the camera was tilted and flattens the photo, so each pixel covers a known number of millimetres.",
    proof: "The scale comes from the geometry of the markers. No model is involved, so no model can make it up.",
    images: [{ src: img("see-rect"), alt: "The same photo flattened: the mat fills the frame seen straight on, with the orange cover on it.", caption: "The photo after flattening, from the run's files." }],
    links: [{ href: "/calibrate", label: "How the screen gets its scale" }],
  },
  {
    id: "outline",
    short: "Outline",
    title: "The part gets an outline",
    plain: "SAM 3.1, Meta's segmentation model, is asked for the part in words, and its mask is used if it scores above a confidence floor. If not, code falls back to a plain colour threshold against the mat. In this run SAM 3.1 found nothing above the floor, so the threshold drew this outline.",
    proof: "A mask is only a proposal: code scores it and falls back rather than trust a weak one, and the job's log names which one it measured from.",
    images: [{ src: img("see-mask"), alt: "A white silhouette of the cover on a black background: the outline this run measured from.", caption: "The outline this run measured from: the colour-threshold fallback, not SAM 3.1." }],
    links: [
      { href: "/models", label: "Which AI did what" },
      { href: "/proof#scale", label: "How often SAM 3.1's mask is used" },
    ],
  },
  {
    id: "measure",
    short: "Millimetres",
    title: "Code turns the outline into millimetres",
    plain: "From the outline and the scale, code works out the part's sizes, each with a stated error.",
    proof: "These numbers are computed from pixels and marker geometry. A model never types a measurement in.",
    images: [{ src: img("see-measure"), alt: "The photo with the outline drawn over the cover and its length and width marked in millimetres.", caption: "The measured sizes drawn on the photo, from the run's files." }],
    links: [{ href: "/judges", label: "Watch a recorded run" }],
  },
  {
    id: "program",
    short: "Program",
    title: "An agent writes a program, not a mesh",
    plain: "An agent on Muse Spark Open writes a short CadQuery program with named knobs. A size can change later without warping the rest of the part.",
    proof: "A claim can't build a part. The program has to pass an allowlist and run in a sandbox with no network, or there is no model at all.",
    images: [],
    links: [
      { href: "/playground", label: "Turn the knobs yourself" },
      { href: "/models", label: "Which AI did what" },
    ],
  },
  {
    id: "check",
    numbers: true,
    short: "Check",
    title: "The verifier compares it with the photo",
    plain: "Plain code draws the model from the camera's view, lays its outline over the photo's outline and measures the biggest gap.",
    proof: "The verifier never reads what the model says about itself; it measures the model.",
    images: [{ src: img("see-heat1"), alt: "Round one: the model's outline over the photo, with orange and blue where they differ and the worst point circled.", caption: "The run's first build, as the verifier drew it." }],
    links: [
      { href: "/proof", label: "Test evidence" },
      { href: "/results", label: "Accuracy" },
    ],
  },
  {
    id: "fix",
    numbers: true,
    short: "Fix",
    title: "The agent reads the gap and fixes the program",
    plain: "The agent sees where the gap is, edits the program and rebuilds, and the verifier measures again. This repeats until the gap is inside the limit or the agent runs out of rounds.",
    proof: "A fix counts only when the verifier's numbers improve. Code keeps the round closest to passing, whatever the agent says.",
    images: [{ src: img("see-heat3"), alt: "The last round: the model's outline over the photo with almost no orange or blue left.", caption: "The run's last round, as the verifier drew it." }],
    links: [{ href: "/lessons", label: "What it learned" }],
  },
  {
    id: "review",
    numbers: true,
    short: "Review",
    title: "A person reviews it, then you export",
    plain: "A person can compare the photo and the model and send it back with pins on the photo. Then you download STL, 3MF or STEP for a printer.",
    proof: "Every download goes through one export gate that reads the verifier's result, so a model that didn't pass can't leave looking as if it did.",
    images: [
      { src: img("flow-model"), alt: "The finished battery cover as a blue 3D model.", caption: "The model that passed." },
      { src: img("flow-review"), alt: "Screenshot of the review desk: a list of parts on the left, one part's photo and model on the right.", caption: "The review desk (screenshot, showing another part)." },
    ],
    links: [
      { href: "/review", label: "Review desk" },
      { href: "/parts", label: "Parts" },
      { href: "/agents", label: "For developers" },
    ],
  },
];

const num = (v: number) => String(Number(v.toFixed(2)));

/** The run's own numbers for a step, in words. Nothing here is typed: empty for steps the run's numbers don't speak to. */
export function stepFacts(id: string, data: FlowData): string[] {
  const rounds = data.run.rounds_detail;
  const first = rounds[0];
  switch (id) {
    case "outline":
      return data.sam_fix
        ? [`Since this run, the prompt names the part's colour. On ${data.sam_fix.photos} test photos SAM 3.1 returned a mask for ${data.sam_fix.new}, up from ${data.sam_fix.old}, and a later recorded run (${data.sam_fix.run_id}) measured from one.`]
        : [];
    case "program":
      return [`Shown here: ${data.run.params.length} of the final program's knobs, each with its range.`];
    case "check":
      return [
        ...(first ? [`First build: ${num(first.error_mm)} mm off and overlap (IoU) ${first.iou}. The limit is ${num(data.limit_mm)} mm, so it did not pass.`] : []),
        `A scripted model that lied about passing was blocked ${data.bypass.blocked} of ${data.bypass.attempts} times.`,
      ];
    case "fix":
      return rounds.map((r) => {
        const edits = r.edits.map((e) => `${e.param} ${num(e.from)} → ${num(e.to)}`).join(", ");
        return `Round ${r.round}: ${num(r.error_mm)} mm, overlap (IoU) ${r.iou}${edits ? `. Edits: ${edits}` : ", the first build"}.`;
      });
    case "review":
      return [
        `${num(data.run.minutes_to_file)} minutes from photo to file, and $${data.run.usd.toFixed(2)} of model calls.`,
        `By estimate, about ${num(data.run.print_minutes)} minutes to print and ₹${num(data.run.inr)} of filament. It has not been printed.`,
      ];
    default:
      return [];
  }
}
