# Upgrade, backup, and recovery

These procedures target one self-hosted team. PostgreSQL is authoritative; Qdrant can be rebuilt. Keep the database, backup volume, and erasure receipts on durable storage, with a separately retained copy of the latest backup directory. A volume survives container replacement; it does not protect against losing the host.

## Upgrade from schema v1

1. Keep the existing application artifact and record its image digest. Stop traffic and all application/worker instances; leave PostgreSQL and Qdrant available.
2. Copy the old configured backup and export directories before replacing the container. Compose now mounts `/backups` and `/exports`; files previously stored under the container's home directory will not move automatically. Verify file hashes and ownership by application UID 10001.
3. Audit prior accepted erasures. With the new binary, initialize the external receipt baseline explicitly: `memkit backup init-erasure-manifest --confirm BASELINE --receipts receipts.json`. Each receipt supplies `user_id` and `private_scope_id` (UUIDs), optionally `accepted_at`. Omit `--receipts` only after establishing that no previous erasure needs replay. An existing backup history without its manifest fails closed.
4. Create a protected pre-migration archive with `memkit backup create --kind pre-migration --protected`. Backup creation does not upgrade the source schema. Copy the entire backup directory, including `erasures`, to independent durable storage.
5. Run `memkit backup restore-drill <archive>` with database-creation privileges. This restores into an isolated database, upgrades it, replays erasure receipts, validates constraints, and removes the temporary database. The source database is unchanged.
6. Start the new application with traffic still withheld. Startup applies additive schema v2: job retry availability and revision/evidence links. Existing memories, revisions, and citations remain; legacy evidence is explicitly unversioned. Rebuild the index with `memkit reindex`, then check readiness, pending deliveries, and representative capture/recall/correction flows before opening traffic.

Before deployment, retain a verified schema-v2-compatible application rollback artifact and its checksum. The [20 September build manifest](releases/2026-09-20-build.json) identifies the locally built, clean-install-tested wheel at `dist/readiness/schema-v2-rollback/memkit-0.3.0-py3-none-any.whl`, matching application source `f1e523d`, and its locked dependencies. These local binaries are not stored in Git; retain them in your release storage before deployment. A source checkpoint alone is not a deployable recovery artifact. A pre-v2 binary can reject the newer schema and is unsuitable for an application rollback. Never remove migration records or rewrite an applied migration to force an old binary to start. A database rollback is a separate offline recovery with erasure replay.

## Routine operation

- Backups: `memkit backup create`, `list`, `verify <archive>`, and `prune`. Verification checks the checksum when supplied and fully decodes the archive; a successful isolated restore drill provides stronger evidence. Protected pre-migration backups are not pruned. Schedule backups and off-host copying through your existing operator tooling.
- Reindex: writes affecting indexed content pause with a retryable `503`; reads, job status, and cancellation remain available. Activation requires exact ID and payload validation. A failed or cancelled build leaves the previous live generation serving. Maintenance releases its database lock when its connection closes.
- Erasure: use the existing administrative command/API. Acceptance persists an external receipt before database deletion. Its administrative job remains visible after the account disappears. External cleanup retries until every managed vector generation and export is clean. Accepted erasure cannot be cancelled.
- Outages: PostgreSQL failure prevents authoritative writes. Qdrant failure allows storage but prevents search; queued index work resumes after recovery. Model providers are optional and never needed for direct capture or local retrieval. A provider failure does not erase evidence.

## Offline recovery

For CLI-managed installations, `memos server backup restore <id> --confirm RESTORE`
automates the offline sequence: protected recovery backup, restore into an empty
database, schema migration and latest erasure replay, database switch, removal of
managed vector generations and exports, reindex, and readiness verification.
The previous database is retained with connections disabled. Never enable it to
serve without applying current erasure receipts and rebuilding derived data.
A durable `restore_incomplete` marker blocks ordinary start/restart/upgrade after
failure; retry restore after resolving the reported failure. A process killed
during the database switch may require an operator to inspect database names and
connection gates first. Keep traffic stopped until cleanup and recovery finish.

1. Stop every application process and block external traffic. Preserve the **latest** external erasure manifest; do not replace it with an older copy from the backup date.
2. Verify the chosen archive, create a new empty PostgreSQL database, and set `MEMKIT_RESTORE_DATABASE_URL` to that replacement. Preserve the former database intact. Restore with matching PostgreSQL client tools:

   ```sh
   pg_restore --exit-on-error --no-owner --no-privileges \
     --dbname="$MEMKIT_RESTORE_DATABASE_URL" /backups/chosen.dump
   ```

3. Point `MEMKIT_DATABASE_URL` at the replacement database. Using the schema-v2-compatible binary and the retained backup volume, run `memkit backup replay-erasures` while offline. This upgrades a v1 archive before replaying receipts. A missing/invalid manifest or a shared-authorship conflict stops recovery. Investigate instead of reopening with resurrected data.
4. Remove the restored installation's old derived Qdrant collections/storage and managed exports. Scope removal to this installation. PostgreSQL and the external erasure manifest must remain intact. This also removes data from generations that are not currently live.
5. Run `memkit reindex` against an empty Qdrant instance. Start the application privately so detached erasure cleanup jobs can finish. Confirm `/readyz`, administrator job status, representative searches, and absence of erased users/data, then reopen traffic.

`memkit backup restore <artifact-id>` deliberately prints guidance instead of replacing a database under live connections. `restore-drill` never restores into the configured database and does not validate host disaster recovery, off-host backup completeness, or available production disk space.
