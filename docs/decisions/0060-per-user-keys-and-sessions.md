# 0060 — Per-user API keys and cookie sessions replace the single static key

    Status:        accepted
    Date:          2026-09-04
    Supersedes:    —
    Superseded by: —
    Evidence:      tests/test_api_v4.py, tests/test_entities.py
    Code:          src/memkit/auth.py, src/memkit/api.py (get_principal, login)
    Contract:      ../03-api.md

## Decision

Two credentials, deliberately different in shape because they are attacked differently.

An **API key** is `mk_<prefix>_<secret>`, minted per user, shown once, stored as a sha256 of the secret with the prefix in clear text so a key can be listed and revoked without keeping anything usable. It is looked up by prefix and compared in constant time. Because it is attached explicitly by the caller on every request, it needs no CSRF defence.

A **session cookie** is what the dashboard carries: HttpOnly, Secure, SameSite=Lax, sliding expiry, stored as a hash for the same reason as the key. The browser attaches it to any request to this origin, including one a hostile page provokes, so a cookie-authenticated mutation must additionally carry `X-Requested-With: memkit`. Safe methods do not need it. When both credentials arrive, the key wins.

Passwords are argon2id. Login failures are counted per handle and per address in a fixed window and answered identically either way.

## Alternatives and why not

**Keep the static key and add an owner field.** This is the cheapest change and it is not authentication: a shared secret cannot say who is calling, so the caller would have to, and any holder of the key could then claim to be anyone. It also has no revocation granularity — one leaked laptop retires everybody's credential.

**A CSRF token instead of a required header.** The double-submit or synchroniser-token patterns are the textbook answer and both need a token minted, delivered, stored and compared. The header works because of two properties this deployment already has: CORS is closed, so no cross-origin script can set a custom header on a request that reaches us, and a form post or image load — the shapes an attacker *can* provoke without script — cannot set one at all. A token would add a round-trip and a failure mode for defence this configuration already provides. If CORS ever opens to a third-party origin, this reasoning expires with it.

**SameSite=Strict.** Would remove the need for the header, and would also sign the user out every time they arrive at the dashboard from a link, which is how people actually arrive at it. Lax plus the header keeps the ordinary navigation working and refuses the cross-site mutation.

**Rate limiting in the database.** A login flood should not become a write workload, so the counter is in process. The honest cost: it is per replica, and this deployment is single-replica. A second replica needs a shared counter, and that is a real change rather than a configuration switch — recorded here so nobody discovers it by scaling out.

**bcrypt or PBKDF2.** argon2id is memory-hard; the whole point of hashing here is that a stolen database does not yield a list of plausible passwords, and memory-hardness is what makes an offline attack expensive on the hardware attackers actually use.

## Consequences

Nothing in the service reads a key from configuration, so there is no instance-wide credential to leak. Sharing one key between two people is sharing one memory — the key names its user and an unqualified write lands in that user's private scope. Changing a password revokes every other session, because the usual reason to change one is that somebody else may have had it.
