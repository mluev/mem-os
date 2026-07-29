export const MEMORY_TYPES = [
  "preference",
  "fact",
  "skill",
  "relation",
  "project",
  "decision",
  "task",
] as const;

export const TAU: Record<string, number> = {
  preference: 540,
  fact: 900,
  skill: 270,
  relation: 270,
  project: 180,
  decision: 180,
  task: 2,
};
