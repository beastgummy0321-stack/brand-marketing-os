---
id: 0061
decision: An org invite is accepted only by a signed-in user whose email equals the invited email, compared case-insensitively.
applies-to: [app/identity/routes.py, app/identity/repository.py]
supersedes: none
status: in-force
---

# An invite is bound to the invited email, not to whoever holds the link

2026-09-04, ticket `docs/issues/deploy/01-invite-email-match.md`, route C (permission /
tenant isolation). Written before any code, per constitution rule 2. This is the first ADR
governing `app/identity/`; `docs/contracts/identity.md` reserved that slot for the first
route C question to reach the module.

## The problem this closes

`accept_invite` (`app/identity/routes.py:152-166`) checks three things — the token exists, the
invite is unused, the invite is unexpired — and **never checks who is holding it**. The invited
address is already stored (`org_invite.email`, `supabase/migrations/20260828000002_identity_baseline.sql:26`)
and already returned by `repo.get_invite_by_token` (`app/identity/repository.py:139-146`); the
route simply does not read it. Anyone who obtains the link — a forwarded mail, a shared screen,
a URL in a chat log — gets a `membership` row in someone else's organisation.

Constitution rule 1 makes tenant isolation a requirement rather than a feature. A join path that
grants membership to a bearer is the one hole that makes every `org_id` filter downstream
irrelevant, because the attacker arrives holding a legitimate `org_id`.

Two of the module's own tests encode the hole as the expected behaviour today
(`app/tests/test_identity_orgs.py:119-124` and `:141-147` mint a token for
`invitee-<hex>@example.com` and accept an invite addressed to `invitee@example.com`). They are
fixtures written for convenience, not a decision — the ticket corrects them.

## The decision

An invite is a letter with a name on it. Accepting it requires being that person:
`accept_invite` compares the authenticated actor's email against `org_invite.email` and answers
**403 `invite_not_yours`** when they differ, before any membership is written.

Comparison is **case-insensitive and whitespace-trimmed** on both sides, because the two strings
come from two different places: `org_invite.email` is typed by the inviting owner into a form
(`app/identity/routes.py:135` only strips it), while the actor's email is copied out of the JWT
claim (`app/identity/__init__.py:113`). An exact-match rule would reject the right person for a
capital letter that neither side chose. An actor with an empty email (the claim is optional —
`claims.get("email") or ""`) matches nothing.

**Order of checks stays as the code has it**: gone (used or expired) is answered before identity.
A holder who learns that a token they already possess has been spent learns nothing they can use;
naming that order here stops it being re-decided per ticket. The 403's message does **not** repeat
the invited address, so the reply never widens what the holder already knows.

## What this does not decide

The screen (`frontend/src/components/auth/AcceptInvitePage.tsx`) still accepts on mount without a
confirmation step, and still renders whatever message the backend returns. The user chose that
scope on 2026-09-04: with the email bound, a mis-click can only be made by the invited person
themselves. A confirmation step is a later UI ticket, not a security one.

## What we looked at

GitHub and Slack both bind an organisation invite to the invited address and ask the wrong account
to switch users; neither treats the link alone as sufficient. Nothing was installed — the check is
one comparison against a column this module already reads.
