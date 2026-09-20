/**
 * A word-level diff between two versions of one fact.
 *
 * The history tab exists to answer "what changed", and for a sentence-long
 * memory that question is about words, not lines: "Prefers pnpm" becoming
 * "Prefers pnpm for new services" is a small, reviewable edit, and a
 * whole-text before/after makes the reader find that themselves. No diff
 * library is pulled in for two short strings — the texts are capped at 2000
 * characters by the API, so a straightforward longest-common-subsequence walk
 * over a few hundred tokens is both exact and cheap.
 */

export type DiffOp = "same" | "added" | "removed";

export interface DiffPart {
  op: DiffOp;
  text: string;
}

interface Token {
  /** The word with its surrounding whitespace, so parts concatenate back. */
  text: string;
  /** The word alone, which is what "changed" means to a reader. */
  key: string;
}

/**
 * Each token is a word with the whitespace that follows it, so no part is
 * whitespace alone — a struck-through space reads as noise, not as a change.
 * Equality compares the words without that whitespace: rewrapping a sentence
 * or collapsing a double space is not an edit anybody wants marked up, and
 * the newer text's spacing is the one shown.
 */
function tokenize(value: string): Token[] {
  return (value.match(/\s*\S+\s*/g) ?? []).map((text) => ({ text, key: text.trim() }));
}

export function wordDiff(before: string, after: string): DiffPart[] {
  const left = tokenize(before);
  const right = tokenize(after);
  const rows = left.length;
  const columns = right.length;
  const parts: DiffPart[] = [];
  const push = (op: DiffOp, text: string): void => {
    const last = parts[parts.length - 1];
    if (last && last.op === op) last.text += text;
    else parts.push({ op, text });
  };

  // lcs[i][j] as a flat array: the length of the longest common subsequence of
  // left[i..] and right[j..]. Filled from the end so the walk below can pick
  // the branch that keeps the most shared words.
  const width = columns + 1;
  const table = new Int32Array((rows + 1) * width);
  const lcs = (i: number, j: number): number => table[i * width + j] ?? 0;
  for (let i = rows - 1; i >= 0; i -= 1) {
    const a = left[i];
    for (let j = columns - 1; j >= 0; j -= 1) {
      const b = right[j];
      table[i * width + j] =
        a && b && a.key === b.key
          ? lcs(i + 1, j + 1) + 1
          : Math.max(lcs(i + 1, j), lcs(i, j + 1));
    }
  }

  let i = 0;
  let j = 0;
  while (i < rows && j < columns) {
    const a = left[i];
    const b = right[j];
    if (a && b && a.key === b.key) {
      push("same", b.text);
      i += 1;
      j += 1;
    } else if (lcs(i + 1, j) >= lcs(i, j + 1)) {
      push("removed", a?.text ?? "");
      i += 1;
    } else {
      push("added", b?.text ?? "");
      j += 1;
    }
  }
  while (i < rows) {
    push("removed", left[i]?.text ?? "");
    i += 1;
  }
  while (j < columns) {
    push("added", right[j]?.text ?? "");
    j += 1;
  }
  return parts;
}

/** Whether a diff found anything, so the caller can say "text unchanged" once. */
export function isUnchanged(parts: readonly DiffPart[]): boolean {
  return parts.every((part) => part.op === "same");
}
