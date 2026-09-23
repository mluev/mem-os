# Memory and retrieval

Read this when you need more than the everyday commands in
[../SKILL.md](../SKILL.md): precise search, citations, profiles, metadata,
entities, history, review and feedback. Every command accepts `--json`,
`--help`, and `--data @file` for a full JSON body; `memos schema COMMAND --json`
prints the exact arguments.

## Search

`search` is `memories search` with the query as its first argument.

```bash
memos search "how do we deploy the api" --include-sources --json
memos search "release owner" --subject sasha --scopes '["mem-os"]' --json
memos search "database choices" --kinds '["decision","preference"]' --limit 5 --budget-tokens 800 --json
memos search "what did the user say about invoices" --include-raw --include-sources --json
```

- `--include-sources` attaches cited evidence to each result.
- `--include-raw` also returns original user passages that were never turned
  into facts. They are verbatim evidence, not confirmed facts.
- `--include-untrusted` adds assistant, agent and tool-sourced claims that are
  normally excluded. Label them as unconfirmed when you use them.
- `--scopes` narrows to named scopes. Naming a scope you cannot read is an error,
  not an empty result — report it.
- `--subject` narrows to facts about one person, project or other entity.
- `--filter` takes a JSON expression over `kind`, `agent_id`, `tags`, `subject_id`
  and nested `context` fields. It supports `eq`, `in`, `exists`, `absent` and
  `all` (logical AND), for example
  `{"all":[{"field":"tags","op":"in","value":["billing"]},{"field":"context.source_workspace","op":"eq","value":"api"}]}`.
  Put larger bodies in a file and pass `--data @search.json`.
- `--policy-id` applies a named retrieval policy. `--budget-tokens` caps the
  returned context.

Each result includes its `scope`, `subject`, `kind`, `source_role`,
`review_status`, `revision` and score. The response carries a `retrieval_id`
and counts of what was dropped (by trust, validity, filter, relevance). Say
whether a fact is personal or shared: "the team decided" and "you decided" are
different claims.

Browse instead of searching with `memories list`. It pages with `--limit` and
`--offset`; `--all` fetches every page.

```bash
memos memories list --review-status pending --scope mem-os --json
memos memories list --tag billing --sort updated_at --order desc --limit 20 --json
```

## Citations and evidence

```bash
memos memories get ID --json
memos memories sources ID --json
memos memories history ID --json
```

`sources` returns the original messages behind a memory, with excerpts, roles
and `evidence_status`:

- `current`: supports the current revision; cite it as support.
- `historical`: supported an earlier wording only; do not cite it for the
  current text.
- `legacy_unversioned`: revision support is unknown; say so.

Quote only the excerpt you rely on. If no evidence supports a claim, say it is
unsupported rather than repeating it as fact.

## Profiles

```bash
memos profile --json
memos profile --blocks '["about","style","project"]' --budget-tokens 800 --json
memos profile --workspace billing-service --dynamic-days 14 --json
memos profiles render --data @profile.json --json
```

The profile is a budgeted summary made of the `about`, `style`, `team`,
`project` and `recent` blocks. The workspace defaults to the current directory
name. Load it once per session, or again after context is lost. Use
`memos entities profile SLUG --json` for what is known about one entity.

## Writing with metadata

Use `memories create` when you need fields that `remember` leaves out. Its
required fields are `--text`, `--kind` and `--source-role`.

```bash
memos memories create --text "Invoices are generated on the 1st" --kind fact --source-role manual --tags '["billing"]' --importance 0.8 --json
memos memories create --text "Staging freeze until the audit closes" --kind decision --source-role manual --scope mem-os --valid-until 2026-10-31T00:00:00Z --json
memos memories create --data @memory.json --json
```

- `kind`: free text. Common values are `fact`, `preference`, `decision`,
  `instruction`, `person` and `project`.
- `source_role`:
  - `manual`: the user explicitly asked for the save.
  - `user`: something the user stated.
  - `agent` or `assistant`: your inference.
  - `tool`: tool output.
- Optional fields: `tags` (up to 20), `importance` and `confidence` (0–1),
  `valid_until` for facts that expire, `subject`, `scope`, and `context` for
  neutral structured metadata such as a workspace or ticket.

Memories are for durable knowledge, not transient task state or secrets.

## Correcting, forgetting and restoring

```bash
memos memories update ID --text "Invoices are generated on the 2nd" --expected-revision N --json
memos memories update ID --subject sasha --expected-revision N --json
memos memories update ID --scope mem-os --move-scope --expected-revision N --json
memos memories archive ID --expected-revision N --json
memos memories restore ID --json
```

- Always read first, then pass the `revision` you read. A conflict means someone
  else changed the memory: read it again and reconcile.
- `--clear-subject` and `--clear-valid-until` remove those fields. Moving a
  memory to another scope requires `--move-scope`, plus `--move-context` to move
  its context too. The same scope rules apply as for new writes.
- `forget ID` and `memories archive ID` both archive reversibly.

## Entities: people, projects, teams

```bash
memos entities list --kind project --json
memos entities resolve --name "Sasha" --json
memos entities get SLUG --json
memos entities profile SLUG --budget-tokens 600 --json
memos entities create --name "Billing service" --kind project --visibility members --json
memos entities update SLUG --description "Handles invoicing" --json
memos entities aliases add SLUG --alias "billing" --json
memos entities aliases remove SLUG ALIAS --json
memos entities members set SLUG USER_ID --role member --json
memos entities members remove SLUG USER_ID --json
memos entities archive SLUG --json
```

- An entity's slug is both a shared scope and a possible subject.
- Kinds are `project`, `product`, `company`, `person` and `custom`.
- Visibility is `members` or `team`.
- Member roles are `owner`, `member` and `viewer`.
- Resolve names before writing, so "Sasha", "sasha" and "Sasha K." land on the same
  subject. Add an alias when resolution fails for a known name.

Creating, archiving and changing membership changes who can read what, so only
do it when the user asks.

## Review and attention

```bash
memos review list --json
memos review list --kind memory --limit 20 --json
memos memories review ID --decision confirm --expected-revision N --json
memos attention resolve ITEM_ID --action link_entity --entity SLUG --json
memos attention resolve ITEM_ID --action dismiss --json
```

- Automatic, inferred and shared writes may wait in review. Pending memories
  are still retrievable, but say that they are pending.
- Review decisions are `confirm`, `decline` and `undo`.
- Only record a decision the user actually made; never confirm on their behalf.

## Retrieval feedback

```bash
memos retrieval list --limit 10 --json
memos retrieval feedback RETRIEVAL_ID --memory-id ID --useful --json
memos retrieval feedback RETRIEVAL_ID --memory-id ID --no-correct --json
memos retrieval legacy-feedback --memory-id ID --query "release owner" --useful --json
```

Send feedback when a recalled memory clearly helped or was wrong. It improves
ranking and flags stale facts. `retrieval legacy-feedback` exists only for older
clients that have no `retrieval_id`.
