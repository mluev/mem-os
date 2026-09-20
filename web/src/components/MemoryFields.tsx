/**
 * The small controls the memories table, its add dialog and the detail drawer
 * all share: the review and lifecycle badges, the filter selects that treat
 * "unset" as a first-class value, and the 0–1 sliders.
 *
 * Kept in one place because a review status that is amber in the table and
 * grey in the drawer is a bug the reader has to resolve by rereading, and
 * because a filter select that loses its label once something is chosen stops
 * being usable with a screen reader.
 */

import type { ReactNode } from "react";
import type { ReviewStatus } from "../api/types";
import type { Option } from "./MemoryOptions";
import { Badge, Select, SelectContent, SelectItem, SelectTrigger, Slider } from "./ui";

/** Radix refuses an item with an empty value, so "unset" needs a sentinel. */
const ANY = " any";

/**
 * Radix keeps a hidden native select in step with the visible one, and while a
 * controlled value has no item to match — the options arrive from the network,
 * so that happens on the first render of any shared link — that sync fires
 * `onValueChange` with an empty value. Taken at face value it silently clears
 * the field the URL just asked for, so a change is only believed when it names
 * an item that exists.
 */
function accept(
  next: string,
  options: readonly Option[],
  onChange: (value: string) => void,
): void {
  if (next === ANY) onChange("");
  else if (options.some((option) => option.value === next)) onChange(next);
}

const REVIEW_TONE: Record<ReviewStatus, string> = {
  pending: "var(--amber)",
  confirmed: "var(--green)",
  declined: "var(--rose)",
};

const REVIEW_TITLE: Record<ReviewStatus, string> = {
  pending: "Written automatically and already usable, waiting for a person to confirm it",
  confirmed: "A person confirmed this fact",
  declined: "A person said this fact is wrong",
};

export function ReviewBadge({ status }: { status: ReviewStatus }) {
  return (
    <Badge style={{ color: REVIEW_TONE[status] }} title={REVIEW_TITLE[status]}>
      <span className="badge-dot" />
      {status}
    </Badge>
  );
}

const STATUS_TONE: Record<string, string> = {
  archived: "var(--faint)",
  expired: "var(--faint)",
  superseded: "var(--violet)",
};

/** Nothing is shown for a live memory: "active" is the absence of news. */
export function LifecycleBadge({ status }: { status: string }) {
  if (status === "active") return null;
  return <Badge style={{ color: STATUS_TONE[status] ?? "var(--muted)" }}>{status}</Badge>;
}

export function Field({
  label,
  htmlFor,
  hint,
  error,
  full,
  children,
}: {
  label: string;
  /** Set for a native control, which then carries the real label association. */
  htmlFor?: string;
  hint?: string;
  error?: string;
  full?: boolean;
  children: ReactNode;
}) {
  const body = (
    <>
      <span>{label}</span>
      {children}
      {error ? (
        <span className="form-error" role="alert">
          {error}
        </span>
      ) : hint ? (
        <span className="subtle">{hint}</span>
      ) : null}
    </>
  );
  const className = full ? "field field-full" : "field";
  return htmlFor ? (
    <label className={className} htmlFor={htmlFor}>
      {body}
    </label>
  ) : (
    <div className={className}>{body}</div>
  );
}

/**
 * A filter select that keeps its own name visible. The trigger reads "Kind"
 * while nothing is chosen and "Kind: preference" afterwards, so the filter bar
 * stays readable at a glance and the control keeps an accessible name either
 * way.
 */
export function FilterSelect({
  label,
  value,
  options,
  anyLabel = "Any",
  onChange,
}: {
  label: string;
  value: string | undefined;
  options: readonly Option[];
  anyLabel?: string;
  onChange: (next: string) => void;
}) {
  const selected = options.find((option) => option.value === value);
  return (
    <Select value={value || ANY} onValueChange={(next) => accept(next, options, onChange)}>
      <SelectTrigger
        className="filter-select"
        aria-label={selected ? `${label}: ${selected.label}` : label}
        style={selected ? { color: "var(--ink)" } : undefined}
      >
        <span>
          {label}
          {selected ? <strong style={{ fontWeight: 600 }}>: {selected.label}</strong> : null}
        </span>
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ANY}>{anyLabel}</SelectItem>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** A select for a form field, where the surrounding Field carries the label. */
export function ValueSelect({
  label,
  value,
  options,
  noneLabel,
  disabled,
  onChange,
}: {
  label: string;
  value: string;
  options: readonly Option[];
  /** When given, an explicit "no value" item is offered. */
  noneLabel?: string;
  disabled?: boolean;
  onChange: (next: string) => void;
}) {
  const selected = options.find((option) => option.value === value);
  // The sentinel is only safe when there is an item carrying it: handed a value
  // that matches no item, Radix answers by firing onValueChange back with that
  // value, which would wipe a field that has no "none" to fall back to.
  const empty = noneLabel ? ANY : "";
  return (
    <Select
      value={value || empty}
      disabled={disabled}
      onValueChange={(next) => accept(next, options, onChange)}
    >
      <SelectTrigger aria-label={label} style={{ width: "100%" }}>
        <span style={selected ? undefined : { color: "var(--faint)" }}>
          {selected?.label ?? noneLabel ?? label}
        </span>
      </SelectTrigger>
      <SelectContent>
        {noneLabel ? <SelectItem value={ANY}>{noneLabel}</SelectItem> : null}
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/**
 * Importance and confidence are 0–1 reals. A slider with a tabular readout
 * beats a number input here: the value is a judgement rather than a
 * measurement, and the reader is comparing it against rows they just saw.
 */
export function RatioField({
  label,
  hint,
  value,
  disabled,
  onChange,
}: {
  label: string;
  hint?: string;
  value: number;
  disabled?: boolean;
  onChange: (next: number) => void;
}) {
  return (
    <div className="field">
      <span className="field-inline-value">
        <span>{label}</span>
        <span className="mono">{value.toFixed(2)}</span>
      </span>
      <Slider
        aria-label={label}
        value={[value]}
        min={0}
        max={1}
        step={0.05}
        disabled={disabled}
        onValueChange={([next]) => onChange(next ?? value)}
      />
      {hint ? <span className="subtle">{hint}</span> : null}
    </div>
  );
}
