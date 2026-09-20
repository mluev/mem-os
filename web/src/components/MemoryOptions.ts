/**
 * The vocabularies the memories screen needs in its pickers: who the caller
 * is, which spaces they can read and write, which entities a fact can be
 * about, and which kinds actually occur in this store.
 *
 * Kinds are free-form on the server, so there is no enumeration endpoint to
 * ask. The kind filter is built from the kinds the store has really used
 * (grouped statistics over the last year) plus whatever the current URL and
 * the loaded page mention, so a shared link filtering on a rare kind still
 * shows that kind as selected instead of silently falling back to "any".
 */

import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Entity, Me, Scope, Stats } from "../api/types";

export interface Option {
  value: string;
  label: string;
}

/** Entity pickers key on the slug, because that is what the API accepts. */
export function entityOptions(entities: readonly Entity[]): Option[] {
  return entities.map((entity) => ({
    value: entity.slug,
    label: `${entity.name} · ${entity.kind}`,
  }));
}

export function scopeOptions(scopes: readonly Scope[]): Option[] {
  return scopes.map((scope) => ({ value: scope.slug, label: `${scope.name} · ${scope.kind}` }));
}

export function plainOptions(values: readonly string[]): Option[] {
  return values.map((value) => ({ value, label: value.replace(/_/g, " ") }));
}

export interface MemoryOptions {
  me: Me | undefined;
  /** Every space the caller can read, which is the scope filter's vocabulary. */
  scopes: Scope[];
  /** The subset a write may target. */
  writableScopes: Scope[];
  /** The caller's own private space: the default for a memory they add. */
  ownScope: Scope | undefined;
  /** Everything a fact can be *about*, including teammates. */
  entities: Entity[];
  kinds: string[];
  isLoading: boolean;
}

export function useMemoryOptions(extraKinds: readonly string[] = []): MemoryOptions {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/v1/auth/me") });
  const entities = useQuery({
    queryKey: ["entities", "all"],
    queryFn: () => api<{ items: Entity[] }>("/v1/entities"),
    staleTime: 60_000,
  });
  const kinds = useQuery({
    queryKey: ["stats", "memories", "kind"],
    queryFn: () =>
      api<Stats>("/v1/admin/stats/memories?days=365&group_by=kind"),
    staleTime: 60_000,
  });

  const scopes = me.data?.scopes ?? [];
  const observed = (kinds.data?.series ?? []).map((point) => point.key);
  return {
    me: me.data,
    scopes,
    writableScopes: scopes.filter((scope) => scope.writable),
    ownScope: scopes.find((scope) => scope.id === me.data?.own_entity_id),
    entities: (entities.data?.items ?? []).filter((entity) => !entity.archived_at),
    kinds: [...new Set([...observed, ...extraKinds].filter(Boolean))].sort((left, right) =>
      left.localeCompare(right),
    ),
    isLoading: me.isLoading || entities.isLoading,
  };
}
