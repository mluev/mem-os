# 0051 — Memory boundary and hybrid retrieval

    Status:        accepted
    Date:          2026-08-09
    Supersedes:    0028, 0039, 0050 and the task-domain architecture
    Superseded by: —
    Evidence:      ../audits/2026-08-09-comprehensive-audit.md
    Code:          src/memkit/retrieval.py, src/memkit/db.py
    Contract:      ../01-architecture.md, ../05-retrieval.md

## Decision

Mem OS stores evidence and neutral memory but does not manage work. Replace the closed type/scope ontology with kind, tags, and context. Normal retrieval uses dense plus BM25 fusion, a versioned silence threshold, strict expiry, and provenance filtering. Legacy work records are backed up/exported and archived, not converted into a new workflow product.
