/**
 * Human review endpoints (`/api/v1/review/*`). Reads are public; writes need the admin token, which `request()` attaches.
 * Every response is validated; the verdict and every mm number shown on the review page come from these responses.
 */
import { request } from "./api";
import { DraftRulesSchema, FeedbackLogSchema, ReviewAttachmentSchema, ReviewDecisionResultSchema, ReviewDetailSchema, ReviewQueueSchema, ReviewStatsSchema } from "./api-types";

export const REVIEW = {
  queue: "/review/queue",
  stats: "/review/stats",
  feedback: "/review/feedback",
  detail: "/review/{id}",
  draft: "/review/{id}/rules/draft",
} as const;

export type ReviewAction = "accept" | "improve" | "reject";

/** Body of `POST /review/{job_id}` (plan Task 5). */
export type DecisionBody = {
  action: ReviewAction;
  pins: { u: number; v: number; note: string }[];
  note: string;
  reason: string;
  rules: { text: string; keep: boolean; source_pin: number | null }[];
  publish: boolean;
  /** Keys from `uploadAttachment`: pasted screenshots or reference pictures (sent to the fixer with the notes). */
  attachments: string[];
  /** Why it matters, in the reviewer's words (kept in the feedback log). */
  why: string;
};

const post = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const at = (id: string) => `/review/${encodeURIComponent(id)}`;

export const review = {
  queue: (includeReplays = true) => request(ReviewQueueSchema, REVIEW.queue, { query: { include_replays: includeReplays ? 1 : 0 } }),
  stats: () => request(ReviewStatsSchema, REVIEW.stats),
  feedback: (q: { family?: string; outcome?: string; by?: string } = {}) => request(FeedbackLogSchema, REVIEW.feedback, { query: q }),
  detail: (jobId: string) => request(ReviewDetailSchema, at(jobId)),
  draftRules: (jobId: string) => request(DraftRulesSchema, `${at(jobId)}/rules/draft`, { method: "POST" }),
  decide: (jobId: string, body: DecisionBody) => request(ReviewDecisionResultSchema, at(jobId), post(body)),
  uploadAttachment: (jobId: string, image: Blob, name = "screenshot.png") => {
    const form = new FormData();
    form.append("image", image, name);
    return request(ReviewAttachmentSchema, `${at(jobId)}/attachments`, { method: "POST", body: form });
  },
};
