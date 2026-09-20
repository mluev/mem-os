/**
 * Adding a fact by hand.
 *
 * The one thing this dialog has to teach is the review rule, because it is
 * surprising and silent otherwise: a memory you save yourself into your own
 * space is confirmed the moment you save it, and anything else — a shared
 * space, or a write attributed to a model — starts pending and waits for a
 * person. The dialog says which of the two the current choices will produce,
 * live, rather than leaving the reader to discover it in the table.
 */

import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { toast } from "sonner";
import { api } from "../api/client";
import type { Memory } from "../api/types";
import { SOURCE_ROLES } from "./MemoryTableState";
import { entityOptions, plainOptions, scopeOptions, useMemoryOptions } from "./MemoryOptions";
import { Field, RatioField, ValueSelect } from "./MemoryFields";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Textarea,
} from "./ui";

const schema = z.object({
  text: z.string().trim().min(1, "A memory needs something to remember").max(2000),
  kind: z
    .string()
    .trim()
    .min(1, "Give this fact a kind, for example preference or decision")
    .max(64),
  scope: z.string().min(1, "Choose the space this memory belongs to"),
  subject: z.string(),
  importance: z.number().min(0).max(1),
  source_role: z.enum(SOURCE_ROLES),
});

type Values = z.infer<typeof schema>;

const SELF_ASSERTED: ReadonlySet<Memory["source_role"]> = new Set(["user", "manual"]);

export function MemoryAddDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated?: (id: string) => void;
}) {
  const client = useQueryClient();
  const options = useMemoryOptions();
  const ownSlug = options.ownScope?.slug ?? "";
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      text: "",
      kind: "preference",
      scope: ownSlug,
      subject: "",
      importance: 0.6,
      source_role: "manual",
    },
  });

  // The caller's own space is the default, and it is only known once
  // /v1/auth/me answers.
  useEffect(() => {
    if (ownSlug && !form.getValues("scope")) form.setValue("scope", ownSlug);
  }, [ownSlug, form]);

  const values = form.watch();
  const confirmedOnSave =
    Boolean(ownSlug) && values.scope === ownSlug && SELF_ASSERTED.has(values.source_role);

  const create = useMutation({
    mutationFn: (input: Values) =>
      api<{ id: string; review_status?: string; deduplicated?: boolean }>("/v1/memories", {
        method: "POST",
        body: JSON.stringify({
          text: input.text.trim(),
          kind: input.kind.trim(),
          source_role: input.source_role,
          scope: input.scope || undefined,
          subject: input.subject || undefined,
          importance: input.importance,
        }),
      }),
    onSuccess: async (result) => {
      if (result.deduplicated) {
        toast.success("That fact was already stored", {
          description: "Nothing was duplicated.",
          action: onCreated ? { label: "Open it", onClick: () => onCreated(result.id) } : undefined,
        });
      } else {
        toast.success(
          result.review_status === "confirmed"
            ? "Saved and confirmed"
            : "Saved — waiting for review",
        );
      }
      form.reset({ ...form.getValues(), text: "" });
      onOpenChange(false);
      await client.invalidateQueries({ queryKey: ["memories"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a memory</DialogTitle>
          <DialogDescription>
            A fact you save into your own space is confirmed immediately — you just said it.
            Anything written into a shared space, or attributed to a model, starts pending and
            stays usable until somebody confirms or removes it.
          </DialogDescription>
        </DialogHeader>
        <form
          className="form-grid"
          onSubmit={form.handleSubmit((input) => create.mutate(input))}
          noValidate
        >
          <Field
            label="Memory"
            htmlFor="add-memory-text"
            full
            error={form.formState.errors.text?.message}
            hint="One durable fact, in the words you would want to read back."
          >
            <Textarea
              id="add-memory-text"
              rows={4}
              maxLength={2000}
              autoFocus
              {...form.register("text")}
            />
          </Field>
          <Field
            label="Kind"
            htmlFor="add-memory-kind"
            error={form.formState.errors.kind?.message}
            hint="Free-form; reuse an existing one where you can."
          >
            <Input
              id="add-memory-kind"
              list="add-memory-kinds"
              maxLength={64}
              {...form.register("kind")}
            />
            <datalist id="add-memory-kinds">
              {options.kinds.map((kind) => (
                <option key={kind} value={kind} />
              ))}
            </datalist>
          </Field>
          <Field label="Source" error={form.formState.errors.source_role?.message}>
            <ValueSelect
              label="Source"
              value={values.source_role}
              options={plainOptions(SOURCE_ROLES)}
              onChange={(next) =>
                form.setValue("source_role", next as Values["source_role"], {
                  shouldValidate: true,
                })
              }
            />
          </Field>
          <Field
            label="Scope"
            error={form.formState.errors.scope?.message}
            hint="Whose space holds this fact, and therefore who can read it."
          >
            <ValueSelect
              label="Scope"
              value={values.scope}
              options={scopeOptions(options.writableScopes)}
              onChange={(next) => form.setValue("scope", next, { shouldValidate: true })}
            />
          </Field>
          <Field label="Subject" hint="Who or what the fact is about, if not the space itself.">
            <ValueSelect
              label="Subject"
              value={values.subject}
              noneLabel="No subject"
              options={entityOptions(options.entities)}
              onChange={(next) => form.setValue("subject", next)}
            />
          </Field>
          <RatioField
            label="Importance"
            value={values.importance}
            onChange={(next) => form.setValue("importance", next)}
            hint="How much this should outrank other facts when the budget is tight."
          />
          <p className="field-full subtle" style={{ margin: 0 }}>
            {confirmedOnSave
              ? "This save lands confirmed."
              : "This save lands pending, and shows up in Needs attention."}
          </p>
          <DialogFooter className="field-full">
            <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Saving…" : "Save memory"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
