/**
 * The job page's first screen in plain words: what happened, why, what to do next. Every number comes in from the job's
 * own verification record and log; this file only words them, and it never turns a result into a better one.
 */
export type PlainTone = "ok" | "warn" | "bad" | "busy";
export type PlainAction = "fit" | "model" | "fix" | "review";

export type JobPlainInput = {
  status: string;
  /** How the job ended: verified, best_effort, failed, refused or cancelled; null while it runs. */
  finished: string | null;
  maxErrorMm: number | null;
  limitMm: number | null;
  /** The outline gap per round, oldest first. */
  gaps: readonly number[];
  views: readonly { view: string; iou: number }[];
  tests: readonly { passed: boolean }[];
  uncheckedCount: number;
  /** The check that failed, in words ("side outline"), when the record names one. */
  failingCheck: string | null;
  /** The verifier's first finding, or the job's stated reason, already in plain words. */
  finding: string | null;
  refusal: string | null;
  /** The part has a place in the review queue, so a person can send it back. */
  inReview: boolean;
  recorded: boolean;
  sample: boolean;
  mock: boolean;
  /** A new job on a server with no model keys: its model steps ran on recorded or stand-in answers. */
  standIn: boolean;
};

export type JobPlain = { tone: PlainTone; happened: string; why: string[]; next: string; actions: PlainAction[]; label: string | null };

const mm = (v: number) => `${v.toFixed(2)} mm`;

function roundsLine(gaps: readonly number[]): string | null {
  if (gaps.length > 1) return `Outline gap by round: ${gaps.map((g) => g.toFixed(2)).join(" → ")} mm.`;
  return null;
}

function runLabel(i: Pick<JobPlainInput, "recorded" | "sample" | "mock" | "standIn">): string | null {
  if (i.mock) return "Mock run: stand-in answers instead of a model, to show the flow.";
  if (i.standIn) return "This server has no model keys, so the model steps used recorded or stand-in answers. This result says nothing about your part.";
  if (i.recorded) return `Recorded run${i.sample ? " on a rendered sample photo" : ""}: played back from its log, so no model is called now.`;
  return i.sample ? "Rendered sample photo, not a phone capture." : null;
}

function verifiedWhy(i: JobPlainInput): string[] {
  const why = ["The verifier measured this itself; nothing the AI claimed counts."];
  const rounds = roundsLine(i.gaps);
  if (rounds) why.push(rounds);
  else if (i.gaps.length === 1) why.push("It passed on the first build.");
  if (i.views.length) why.push(`Overlap with the photo (IoU): ${i.views.map((v) => `${v.view} ${v.iou.toFixed(3)}`).join(", ")}.`);
  if (i.tests.length) why.push(`${i.tests.filter((t) => t.passed).length} of ${i.tests.length} part tests passed.`);
  if (i.uncheckedCount) {
    why.push(i.uncheckedCount === 1 ? "One size had no photo to check it against; it is listed below." : `${i.uncheckedCount} sizes had no photo to check them against; they are listed below.`);
  }
  return why;
}

function bestEffortHappened(i: JobPlainInput): string {
  const { maxErrorMm: err, limitMm: limit } = i;
  if (err != null && limit != null && err > limit) return `Not verified. The closest model is ${mm(err)} off; the limit is ${mm(limit)}.`;
  if (err != null && limit != null && i.failingCheck) {
    const failed = i.failingCheck === "judge flag" ? "the judge blocked it" : `the ${i.failingCheck} check failed`;
    return `Not verified. The largest error, ${mm(err)}, is inside the ${mm(limit)} limit, but ${failed}.`;
  }
  return "Not verified. A check failed; the verifier's notes name it below.";
}

function bestEffortNext(i: JobPlainInput): string {
  const download = "You can still download this model after reading why it did not pass.";
  if (i.recorded) return `This recorded run will not change, so read the notes below or start your own fix. ${download}`;
  if (i.failingCheck === "judge flag") return `Read the judge's note below: it thinks a feature is missing. Send the part back from review, or start again with a clearer photo. ${download}`;
  return `Retake the photo or add a side photo, then run it again. ${download}`;
}

export function jobPlain(i: JobPlainInput): JobPlain {
  const label = runLabel(i);
  const base = { label };
  switch (i.finished) {
    case "verified": {
      const limit = i.limitMm != null ? `; the limit is ${mm(i.limitMm)}` : "";
      return {
        ...base,
        tone: "ok",
        happened: i.maxErrorMm != null ? `Passed. The largest error is ${mm(i.maxErrorMm)}${limit}.` : "Passed the verifier's checks.",
        why: verifiedWhy(i),
        next: i.recorded ? "Check the fit at true size, or turn a knob: rebuilding runs only code, so it works on a recorded run." : "Check the fit at true size on your screen, then use Export for the printer file.",
        actions: ["fit", "model"],
      };
    }
    case "best_effort":
      return {
        ...base,
        tone: "warn",
        happened: bestEffortHappened(i),
        why: [i.finding, roundsLine(i.gaps)].filter((x): x is string => !!x),
        next: bestEffortNext(i),
        actions: i.inReview ? ["review", "fix", "model"] : ["fix", "model"],
      };
    case "refused":
      return {
        ...base,
        tone: "bad",
        happened: "PartSmith declined to make this part.",
        why: i.refusal ? [i.refusal] : [],
        next: "There is nothing to download. If the reason looks wrong, describe the part differently and try again.",
        actions: ["fix"],
      };
    case "failed":
      return {
        ...base,
        tone: "bad",
        happened: "No usable model came out of this run.",
        why: i.finding ? [i.finding] : [],
        next: "Check the photo, with every marker in frame and in focus, and start again.",
        actions: ["fix"],
      };
    case "cancelled":
      return { ...base, tone: "warn", happened: "This job was cancelled before it finished.", why: [], next: "Start again when you are ready.", actions: ["fix"] };
  }
  if (i.status === "waiting_for_answer") {
    return {
      ...base,
      tone: "busy",
      happened: "Paused: it needs one answer from you.",
      why: ["The photo cannot settle a value this part needs, so it asks instead of guessing."],
      next: "Answer the question just below and the job carries on.",
      actions: [],
    };
  }
  const latest = i.gaps.at(-1);
  const limit = i.limitMm != null ? mm(i.limitMm) : "the limit";
  return {
    ...base,
    tone: "busy",
    happened: i.status === "queued" ? "Waiting to start." : latest != null ? `Working on it. The latest outline gap is ${mm(latest)}; the limit is ${limit}.` : "Working on it.",
    why: [`Each round the verifier measures the model again, and the agent edits its program to close the gap until it is inside ${limit}.`],
    next: "Nothing to do yet. This page updates on its own.",
    actions: ["model"],
  };
}
