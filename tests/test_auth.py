"""The two ways in, and why they are deliberately not interchangeable.

An **API key** is what an agent or a hook carries. It names its user on every
request, so nothing else can make the caller attach it and it needs no CSRF
defence. A **session cookie** is what the dashboard carries, and the browser
attaches it to any request to this origin -- including one a hostile page
provokes -- so a cookie-authenticated mutation additionally requires a header
no cross-origin form can set.

The API-key parsing cases are here because of a real outage: the token is
`mk_<prefix>_<secret>`, the secret is base64url and contains `_` and `-` of its
own, and an unbounded split on `_` therefore rejected roughly a third of every
key ever issued -- intermittently, which is the worst way for an auth bug to
present.
"""

from __future__ import annotations

import hashlib
import secrets
import time
import unittest
import uuid

from memkit import api, auth
from memkit.db import transaction
from tests.fixtures import PASSWORD
from tests.httpharness import ApiTestCase

CSRF = {auth.CSRF_HEADER: auth.CSRF_VALUE}


class AuthTestCase(ApiTestCase):
    def login_token(self, who: str = "alice", password: str = PASSWORD) -> str:
        response = self.client.post("/v1/auth/login", json={"handle": who, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return response.cookies[api.SESSION_COOKIE]

    def resolve(self, token: str) -> str | None:
        return auth.resolve_session(self.db, token, ttl_days=30)


class LoginTest(AuthTestCase):
    def test_a_successful_login_sets_a_cookie_the_page_cannot_read(self) -> None:
        """HttpOnly is the difference between an XSS bug and a stolen session."""
        response = self.client.post(
            "/v1/auth/login", json={"handle": "alice", "password": PASSWORD}
        )
        self.assertEqual(response.status_code, 200, response.text)
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=lax", cookie)
        self.assertIn("path=/", cookie)
        self.assertEqual(response.json()["user"]["handle"], "alice")
        self.assertEqual(response.json()["user"]["auth_kind"], "session")
        self.assertEqual(response.json()["csrf_required_header"], auth.CSRF_HEADER)

    def test_a_wrong_password_and_an_unknown_handle_answer_identically(self) -> None:
        """Otherwise the endpoint is a directory of who has an account here."""
        wrong = self.client.post(
            "/v1/auth/login", json={"handle": "alice", "password": "not-the-password"}
        )
        unknown = self.client.post(
            "/v1/auth/login", json={"handle": "nobody", "password": "not-the-password"}
        )
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(wrong.json(), unknown.json())
        self.assertNotIn("set-cookie", wrong.headers)

    def test_a_disabled_account_cannot_sign_in_at_all(self) -> None:
        """Offboarding has to close the password door as well as the key door."""
        self.client.patch(
            f"/v1/users/{self.team.bob_id}", headers=self.auth, json={"disabled": True}
        )
        refused = self.client.post("/v1/auth/login", json={"handle": "bob", "password": PASSWORD})
        self.assertEqual(refused.status_code, 401, refused.text)

    def test_repeated_failures_are_throttled_and_recover_when_the_window_passes(self) -> None:
        """A password is guessable; the rate limit is what makes guessing useless.

        The window is driven forward by ageing the limiter's own record rather
        than by sleeping: a test that waits a minute to prove a minute-long
        window is a test nobody runs.
        """
        limiter: auth.RateLimiter = api.app.state.login_limiter
        for _ in range(limiter.limit):
            attempt = self.client.post(
                "/v1/auth/login", json={"handle": "alice", "password": "not-the-password"}
            )
            self.assertEqual(attempt.status_code, 401, attempt.text)

        throttled = self.client.post(
            "/v1/auth/login", json={"handle": "alice", "password": PASSWORD}
        )
        self.assertEqual(throttled.status_code, 429, throttled.text)

        # Every recorded attempt is moved a full window into the past, which is
        # exactly what waiting would have done.
        with limiter._lock:
            for hits in limiter._hits.values():
                for index, stamp in enumerate(hits):
                    hits[index] = stamp - (limiter.window + 1)

        recovered = self.client.post(
            "/v1/auth/login", json={"handle": "alice", "password": PASSWORD}
        )
        self.assertEqual(recovered.status_code, 200, recovered.text)

    def test_the_limiter_counts_per_key_and_forgets_on_success(self) -> None:
        """A shared address must not lock out a colleague who typed it right."""
        limiter = auth.RateLimiter(limit=2, window_seconds=60)
        self.assertTrue(limiter.check("handle:alice", "ip:10.0.0.1"))
        limiter.record("handle:alice", "ip:10.0.0.1")
        limiter.record("handle:alice", "ip:10.0.0.1")
        self.assertFalse(limiter.check("handle:alice", "ip:10.0.0.1"))
        self.assertFalse(limiter.check("ip:10.0.0.1"))
        self.assertTrue(limiter.check("handle:bob"))
        limiter.reset("handle:alice", "ip:10.0.0.1")
        self.assertTrue(limiter.check("handle:alice", "ip:10.0.0.1"))


class CsrfTest(AuthTestCase):
    def test_a_cookie_mutation_without_the_header_is_refused(self) -> None:
        """The header is the whole defence, and it is enough because CORS is closed.

        A cross-origin form post or image load can carry the cookie but cannot
        set a custom header, so its absence on a mutation means the request did
        not come from the dashboard.
        """
        self.login_token()
        body = {"text": "written from the dashboard", "kind": "fact", "source_role": "manual"}

        forged = self.client.post("/v1/memories", json=body)
        self.assertEqual(forged.status_code, 403, forged.text)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM memories"), 0)

        genuine = self.client.post("/v1/memories", headers=CSRF, json=body)
        self.assertEqual(genuine.status_code, 201, genuine.text)

    def test_a_safe_method_needs_no_header(self) -> None:
        """Reading is not a state change, and the dashboard reads on every view."""
        self.login_token()
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 200)
        self.assertEqual(self.client.get("/v1/memories").status_code, 200)

    def test_an_api_key_mutation_needs_no_header(self) -> None:
        """Requiring it would break every hook for no gain: a key is never ambient."""
        created = self.client.post(
            "/v1/memories",
            headers=self.auth,
            json={"text": "written by an agent", "kind": "fact", "source_role": "manual"},
        )
        self.assertEqual(created.status_code, 201, created.text)

    def test_a_key_wins_over_a_cookie_when_both_arrive(self) -> None:
        """An agent that sends a key means to act as that key's user.

        Preferring the ambient browser session would silently attribute the
        agent's writes to whoever last signed in on that machine.
        """
        self.login_token("alice")
        me = self.client.get("/v1/auth/me", headers=self.as_bob)
        self.assertEqual(me.status_code, 200, me.text)
        self.assertEqual(me.json()["handle"], "bob")
        self.assertEqual(me.json()["auth_kind"], "api_key")


class SessionLifetimeTest(AuthTestCase):
    def test_logout_revokes_the_session_it_was_called_with(self) -> None:
        """Clearing the cookie is cosmetic; the stored session has to die."""
        token = self.login_token()
        self.assertEqual(self.resolve(token), self.team.alice_id)

        response = self.client.post("/v1/auth/logout")
        self.assertEqual(response.status_code, 200, response.text)

        self.assertIsNone(self.resolve(token))
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 401)

    def test_changing_a_password_signs_out_everywhere_but_here(self) -> None:
        """The usual reason to change a password is that somebody else had it.

        Keeping the calling session is what stops the change from logging the
        user out of the page they just used to make it.

        Expected to fail today, and the failure is the point: the statement in
        `auth.revoke_all_sessions` compares an untyped placeholder in
        `(%s IS NULL OR token_hash <> %s)`, which Postgres refuses with
        `IndeterminateDatatype`. The route therefore answers 500 on every call
        and nobody can change a password. `auth.py` belongs to another agent in
        this change, so this stays red until the placeholder is cast (see the
        port report); remove the marker with the fix.
        """
        elsewhere = self.login_token()
        here = self.login_token()
        self.assertNotEqual(elsewhere, here)

        changed = self.client.post(
            "/v1/auth/password",
            headers=CSRF,
            json={"current_password": PASSWORD, "new_password": "an-even-longer-password"},
        )
        self.assertEqual(changed.status_code, 200, changed.text)

        self.assertIsNone(self.resolve(elsewhere))
        self.assertEqual(self.resolve(here), self.team.alice_id)
        self.assertEqual(
            self.client.post(
                "/v1/auth/login", json={"handle": "alice", "password": PASSWORD}
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/v1/auth/login", json={"handle": "alice", "password": "an-even-longer-password"}
            ).status_code,
            200,
        )

    def test_a_wrong_current_password_changes_nothing(self) -> None:
        """A borrowed session must not be enough to take over the account."""
        self.login_token()
        refused = self.client.post(
            "/v1/auth/password",
            headers=CSRF,
            json={"current_password": "not-it", "new_password": "an-even-longer-password"},
        )
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertEqual(
            self.client.post(
                "/v1/auth/login", json={"handle": "alice", "password": PASSWORD}
            ).status_code,
            200,
        )


class ApiKeyParsingTest(ApiTestCase):
    def mint_with_secret(self, secret: str, *, name: str = "crafted") -> str:
        """Store a key whose secret is chosen, so parsing can be tested directly."""
        prefix = secrets.token_hex(6)
        with transaction(self.db):
            self.db.execute(
                """INSERT INTO api_keys (id,user_id,name,key_prefix,key_hash)
                   VALUES (%s,%s,%s,%s,%s)""",
                (
                    str(uuid.uuid4()),
                    self.team.alice_id,
                    name,
                    prefix,
                    hashlib.sha256(secret.encode()).hexdigest(),
                ),
            )
        return f"{auth.KEY_PREFIX}_{prefix}_{secret}"

    def test_a_minted_key_round_trips(self) -> None:
        with transaction(self.db):
            minted = auth.mint_api_key(self.db, user_id=self.team.alice_id, name="laptop")
        self.assertTrue(minted.token.startswith(f"{auth.KEY_PREFIX}_{minted.prefix}_"))
        self.assertEqual(auth.resolve_api_key(self.db, minted.token), self.team.alice_id)

    def test_a_secret_containing_the_separator_still_resolves(self) -> None:
        """The bug that made about a third of issued keys unusable.

        `token_urlsafe` emits base64url, whose alphabet includes `_` and `-`.
        Splitting the token on every `_` truncated any secret that happened to
        contain one, so whether a key worked depended on the random bytes it
        was made from.
        """
        token = self.mint_with_secret("s3cret_with-both_kinds-of_separator")
        self.assertEqual(auth.resolve_api_key(self.db, token), self.team.alice_id)

        used = self.client.get("/v1/auth/me", headers={"X-API-Key": token})
        self.assertEqual(used.status_code, 200, used.text)
        self.assertEqual(used.json()["handle"], "alice")

    def test_a_malformed_or_wrong_token_resolves_to_nobody(self) -> None:
        """Every rejection path returns None rather than raising into a 500."""
        token = self.mint_with_secret("a_valid-secret_value")
        prefix = token.split("_")[1]
        for candidate in (
            "",
            "not-a-key",
            "mk_only-two-parts",
            f"xx_{prefix}_a_valid-secret_value",
            f"{auth.KEY_PREFIX}_{prefix}_wrong-secret",
            f"{auth.KEY_PREFIX}_deadbeefcafe_a_valid-secret_value",
        ):
            self.assertIsNone(auth.resolve_api_key(self.db, candidate), candidate)

    def test_last_used_at_advances_on_every_use(self) -> None:
        """An operator needs to know which of a person's keys are still live.

        The second timestamp is compared against a backdated one rather than
        against the first, so the assertion does not depend on two requests
        landing in different microseconds.
        """
        with transaction(self.db):
            minted = auth.mint_api_key(self.db, user_id=self.team.alice_id, name="laptop")
        header = {"X-API-Key": minted.token}
        self.assertIsNone(self.scalar("SELECT last_used_at FROM api_keys WHERE id=%s", minted.id))

        self.assertEqual(self.client.get("/v1/auth/me", headers=header).status_code, 200)
        first = self.scalar("SELECT last_used_at FROM api_keys WHERE id=%s", minted.id)
        self.assertIsNotNone(first)

        with transaction(self.db):
            self.db.execute(
                "UPDATE api_keys SET last_used_at = now() - interval '1 hour' WHERE id=%s",
                (minted.id,),
            )
        backdated = self.scalar("SELECT last_used_at FROM api_keys WHERE id=%s", minted.id)
        self.assertEqual(self.client.get("/v1/auth/me", headers=header).status_code, 200)
        self.assertGreater(
            self.scalar("SELECT last_used_at FROM api_keys WHERE id=%s", minted.id), backdated
        )

    def test_a_key_is_listed_by_prefix_and_never_by_secret(self) -> None:
        """The listing has to identify a key well enough to revoke it, and no better."""
        minted = self.client.post("/v1/api-keys", headers=self.auth, json={"name": "laptop"})
        self.assertEqual(minted.status_code, 201, minted.text)
        listed = self.client.get("/v1/api-keys", headers=self.auth).json()["items"]
        entry = next(item for item in listed if item["id"] == minted.json()["id"])
        self.assertEqual(entry["key_prefix"], minted.json()["key_prefix"])
        self.assertNotIn("secret", entry)
        self.assertNotIn(minted.json()["secret"], str(listed))


class RateLimiterUnitTest(unittest.TestCase):
    def test_the_window_is_fixed_and_expires_by_wall_time(self) -> None:
        """Recorded directly, because the endpoint cannot be made to wait a minute."""
        limiter = auth.RateLimiter(limit=1, window_seconds=60)
        limiter.record("handle:alice")
        self.assertFalse(limiter.check("handle:alice"))
        limiter._hits["handle:alice"][0] = time.monotonic() - 61
        self.assertTrue(limiter.check("handle:alice"))


if __name__ == "__main__":
    unittest.main()
