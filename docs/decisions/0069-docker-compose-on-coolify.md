# 0069 — Docker Compose on Coolify; launchd dropped; a CPU embedding ladder

    Status:        accepted
    Date:          2026-09-04
    Supersedes:    —
    Superseded by: —
    Evidence:      ../measurements.md#to-be-re-measured
    Code:          Dockerfile, docker-compose.yml, src/memkit/operations.py, src/memkit/embed.py
    Contract:      ../06-roadmap.md, ../../README.md

## Decision

The deployment is one Compose file — the app, `postgres:16`, and `qdrant:v1.18.2` — deployed by Coolify on a VPS. Only the app gets a domain; the database and the index publish no port and stay on the internal network. TLS terminates at the proxy, so the app is told it is behind one and keeps its session cookie Secure. The embedding model lives on a volume, because it is about two gigabytes and would otherwise be downloaded on every redeploy.

Service management is gone: no `memkit setup`, no launchd plists, no Docker orchestration from inside the process. The instance's lifecycle belongs to whatever starts the containers.

Backups are `pg_dump --format=custom`, checksummed and verified with `pg_restore --list`. Restore is documented and refused in code.

## Alternatives and why not

**Keep launchd.** It was right for a service that ran beside its user on one Mac. A team instance runs somewhere the team can reach at three in the morning, which is not a laptop, and launchd does not exist on the host it now runs on. Keeping both would mean two supported deployment shapes for one instance.

**Kubernetes, or a managed Postgres and a managed Qdrant.** Correct for a service with an operations team. This one has an author. Compose on a single host is the shape whose failure modes fit in one file and whose restore procedure fits in three commands. Managed Postgres would remove the backup work and add a bill and a second place to configure networking; it stays available as a change to one DSN if the trade ever flips.

**Restore automatically, as the SQLite build did.** `pg_restore --clean` drops and recreates every object in the archive, and nothing else may hold a connection while it runs. The service cannot promise that about itself: its pool reconnects on demand, the worker runs on a timer, and any other replica is a writer it does not know about. A restore that ran anyway would leave a half-replaced schema with no way back. So the part that can be done safely is done — the artifact is verified against its recorded checksum and its table of contents parsed — and the command is handed to whoever can stop the service. `restore_backup` raises `NotImplementedError` with that command in the message, which is a deliberate refusal, not a gap.

**Vendor `pg_dump`.** It must match the server's major version or a custom-format archive is refused, so the image installs `postgresql-client-16` beside `postgres:16` and the pair is upgraded together.

**GPU embeddings.** The CUDA wheels are several gigabytes and the target is a CPU VPS, so the image pins the CPU torch index.

## The embedding ladder

BGE-M3 on CPU is the one performance risk in this deployment, and the response is a documented sequence of configuration steps rather than an automatic runtime fallback — the code chooses a *device* by itself (MPS or CUDA if asked for and present, CPU otherwise) but never silently changes model or runtime, because a different model means vectors in a different space and a store that is no longer comparable with itself.

`memkit bench` is the gate: it measures single-phrase latency and exits non-zero above 300 ms or on a dimension mismatch. If the target VPS fails it, in order: `MEMKIT_EMBED_BACKEND=onnx`, which loads the exported graph and is the faster of the two runtimes on CPU; then more vCPU; then a smaller model with `MEMKIT_EMBED_MODEL` and a matching `MEMKIT_EMBED_DIM`, which requires `memkit reindex` and forfeits BGE-M3's multilingual quality — the reason it was chosen for a Russian-and-English corpus in the first place. The embedder refuses to load a model whose width disagrees with the configured dimension, rather than letting Qdrant reject every point later.

The number that decides this has not been measured on the target hardware. It is listed in [`measurements.md`](../measurements.md#to-be-re-measured).
