/**
 * Verifying an evidence span in the browser.
 *
 * Current responses carry a server-verified excerpt and its verdict. Legacy
 * responses carry a message, Unicode character offsets, and a stored hash.
 * Neither response shape may turn an unchecked or drifted span into a verified
 * quote; insecure browsers without hashing report that limitation explicitly.
 */

import type { MemoryEvidence as CurrentEvidence } from "../api/types";

type MemoryEvidence = Pick<CurrentEvidence, "message_id" | "role" | "created_at" | "start_char" | "end_char"> & {
  excerpt?: string;
  verified?: boolean;
  content?: string;
  excerpt_sha256?: string;
  evidence_status?: CurrentEvidence["evidence_status"];
  supported_revisions?: number[];
};

export type SpanState =
  /** Re-sliced and hashed to the value the extractor recorded. */
  | "verified"
  /** The slice exists but does not match the recorded hash, or cannot be taken. */
  | "unverified"
  /** Nothing to check against, or no hashing available in this browser. */
  | "unchecked";

export interface SpanContext {
  before: string;
  excerpt: string;
  after: string;
}

export interface VerifiedSpan {
  key: string;
  messageId: number;
  role: string;
  createdAt: string | null;
  state: SpanState;
  context: SpanContext | null;
  evidenceStatus?: CurrentEvidence["evidence_status"];
  supportedRevisions?: number[];
}

/** How much of the surrounding message to show on either side of the span. */
const PAD = 140;

/**
 * The span with a little of the message around it, so a reader can see the
 * sentence the fact was taken from. Null when the offsets do not land inside
 * the retained message, which is itself a verification failure.
 */
export function spanContext(
  content: string | null | undefined,
  start: number,
  end: number,
  pad: number = PAD,
): SpanContext | null {
  if (typeof content !== "string") return null;
  const characters = Array.from(content);
  if (!Number.isInteger(start) || !Number.isInteger(end)) return null;
  if (start < 0 || end > characters.length || end <= start) return null;
  const head = characters.slice(Math.max(0, start - pad), start).join("");
  const tail = characters.slice(end, Math.min(characters.length, end + pad)).join("");
  return {
    before: (start - pad > 0 ? "…" : "") + head,
    excerpt: characters.slice(start, end).join(""),
    after: tail + (end + pad < characters.length ? "…" : ""),
  };
}

/**
 * The verdict for one span. Split out from the hashing so the decision is
 * testable without a crypto implementation.
 */
export function spanState(
  excerpt: string | null,
  expected: string | null | undefined,
  actual: string | null,
): SpanState {
  if (excerpt === null) return "unverified";
  if (!expected) return "unchecked";
  if (actual === null) return "unchecked";
  return actual === expected.toLowerCase() ? "verified" : "unverified";
}

/** The SHA-256 of a string as lowercase hex, or null where the browser cannot. */
export async function sha256Hex(value: string): Promise<string | null> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) return null;
  try {
    const digest = await subtle.digest("SHA-256", new TextEncoder().encode(value));
    return Array.from(new Uint8Array(digest))
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
  } catch {
    return null;
  }
}

export async function verifySpans(evidence: readonly MemoryEvidence[]): Promise<VerifiedSpan[]> {
  return Promise.all(
    evidence.map(async (item, index) => {
      const key = `${item.message_id}:${item.start_char}:${item.end_char}:${index}`;
      const head = {
        key,
        messageId: item.message_id,
        role: item.role,
        createdAt: item.created_at,
        evidenceStatus: item.evidence_status,
        supportedRevisions: item.supported_revisions,
      };
      // The retained message: re-slice it and check the hash ourselves.
      if (typeof item.content === "string") {
        const context = spanContext(item.content, item.start_char, item.end_char);
        const actual = context ? await sha256Hex(context.excerpt) : null;
        return { ...head, context, state: spanState(context?.excerpt ?? null, item.excerpt_sha256, actual) };
      }
      // A failed verification is deliberately retained by the server for
      // diagnosis. An excerpt's mere presence says nothing about its integrity.
      if (typeof item.excerpt === "string") {
        return {
          ...head,
          context: { before: "", excerpt: item.excerpt, after: "" },
          state: (item.verified === true ? "verified" : item.verified === false ? "unverified" : "unchecked") as SpanState,
        };
      }
      return { ...head, context: null, state: "unverified" as SpanState };
    }),
  );
}
