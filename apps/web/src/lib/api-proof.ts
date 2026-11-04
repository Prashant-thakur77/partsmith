import { request } from "./api";
import { ProofSchema } from "./proof-schema";

export * from "./proof-schema";

export const proofApi = { proof: () => request(ProofSchema, "/proof") };
