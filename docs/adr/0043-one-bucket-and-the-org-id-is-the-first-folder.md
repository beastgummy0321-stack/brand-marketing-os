---
id: 0043
decision: Uploaded files live in one private assets bucket; the org id is the first path segment of the object key.
applies-to: [app/storage/]
supersedes: none
status: in-force
---

# One bucket, and the org id is the first folder

Slice ⑥ ticket 06-1, 2026-08-30. **Supersedes ADR 0027 decision 7** ("素材檔上傳進系統（Storage，
每組織一 bucket），掛在主題下").

Half of that decision has no referent left: 主題 was a concept of `app/ads/`, deleted on 2026-08-29
with the other 21,595 lines (ADR 0030). The other half — one bucket per organisation — reads like
an analogy to 憲法 #2 (每張表必有 `org_id`), but a Storage bucket is not a table.

**Uploaded files live in one private bucket named `assets`. Tenant isolation is the first path
segment of the object key, not the bucket.**

```
<org_id>/brands/<brand_id>/assets/<asset_id>/<filename>     官方素材
<org_id>/intake/<photo_token>/<filename>                    建檔精靈照片
```

## Why the prefix and not the bucket

- Supabase's documented multi-tenant pattern is one bucket with the tenant id as the first path
  segment, and RLS on `storage.objects` keyed off `(storage.foldername(name))[1]`
  ([access control](https://supabase.com/docs/guides/storage/security/access-control), checked
  2026-08-30). "Folders" in Storage are key prefixes; there is no directory entity to isolate.
- A bucket per organisation puts an admin API call inside the signup path — a new failure mode on
  the one path that must never fail — and needs N policies where the prefix needs one.
- The property ADR 0027 #7 wanted is kept: every object's key starts with the organisation that
  owns it, and `app/storage/`'s four functions each refuse a key whose first segment is not the
  `org_id` they were passed. That refusal is the isolation check.

## What else this decides

1. **The backend carries the bytes.** The browser keeps calling the same two FastAPI URLs it calls
   today; FastAPI fetches from Storage with the service-role key and answers. No signed URLs, no
   browser→Storage traffic — 憲法 #3 (前端只跟 FastAPI 講話). Cost: those two routes stop being
   `FileResponse` and buffer up to 10 MB per concurrent image, losing ETag and Range. Acceptable
   for an `<img>` tag; the upgrade path is a signed URL plus a redirect.
2. **No new dependency.** `httpx` is pinned and `app/identity/routes.py:87-96` already calls a
   Supabase REST API with the service-role key. Storage is five more endpoints on the same road,
   not a reason to install `supabase-py` or `storage3`.
3. **No RLS policy on `storage.objects`.** The bucket is private and the only client is the backend
   holding a key that bypasses RLS; a policy written today protects nothing. Consistent with ADR
   0027 decision 9. The day a browser talks to Storage directly, D1 makes it one policy.
   **2026-09-02:** ADR 0052 gave every `public` table a policy, but not this one, and this point
   stands unchanged — 0052 governs the app's own psycopg connection to `public`, while Storage is
   reached over REST with the service-role key, which bypasses RLS regardless of any policy. The
   citation of 0027 decision 9 above now reads against that decision's correction line.
4. **No bucket-level size or MIME limit.** `app/intake/state.py:403-411` and
   `app/brand_web/routes_library.py:71-76` already validate, in Chinese, before anything is
   written. A second number with no source is a guess.

## What we probed, because the API is not what it looks like

Verified against the live local stack on 2026-08-30, before any code was written:

- `DELETE /storage/v1/object/<bucket>` with `{"prefixes": [...]}` matches **exact object names
  only**. Given a prefix it returns `200 []` and deletes nothing. `POST /object/list/<bucket>` is
  non-recursive. The recursive listing is `POST /object/list-v2/<bucket>`, which returns full keys
  and a `hasNext` flag — so "delete everything under this prefix" is list-v2 → delete exact names →
  repeat. Built the naive way, deleting a brand would have reported success and removed nothing.
- A missing object and a duplicate upload both come back as **HTTP 400** carrying the real status
  in the JSON body (`{"statusCode":"404","code":"NoSuchKey"}` /
  `{"statusCode":"409","code":"KeyAlreadyExists"}`). Branching on the HTTP status is dead code.
- `supabase db reset` replays user migrations **before** the storage container restarts, so a bare
  `insert into storage.buckets` aborts the reset with `relation "storage.buckets" does not exist`;
  and because that table is global rather than per-schema, an unguarded insert also fails every
  test module after the first (`app/tests/conftest.py:74` replays all migrations per module). The
  bucket is therefore created twice over: `[storage.buckets.assets]` in `supabase/config.toml` for
  local, and a `to_regclass`-guarded, `on conflict do nothing` insert in a `core` migration for the
  cloud project.

## Consequences

- **`creative_asset_root` is deleted, not ported.** It was already an empty shell — no button
  opened that folder and no code read an image out of it once `app/ads/` was deleted. The settings
  card it lived on keeps only the 花費上限 form.
- **Deleting a brand now really deletes its files.** The old code deleted the (unused) creative
  folder and left the uploaded 官方素材 orphaned on disk forever; the replacement deletes the
  brand's whole key prefix.
- **`data/uploads/` stops being written to and is not migrated.** CLAUDE.md 資料狀態: unreleased
  system, all of `data/` is test data.
- **A new environment variable is load-bearing.** `SUPABASE_SERVICE_ROLE_KEY` must reach the dev
  server, the e2e backend, pytest (via a `conftest.py` setdefault of the local demo key) and CI
  (exported from `supabase status`). Missing, uploads fail loudly — by design; an upload that
  reports success while storing nothing is the one outcome that must not exist.
- **Attaching an image to an ad node is still not built.** This ADR gives files a home; it does not
  deliver the milestone's missing half. That question reopens after the user has pasted an image
  into Meta by hand at least once.

## What we looked at

- Supabase official Storage access-control docs — copied the prefix layout and the
  private-by-default posture; did not copy client-side signed-URL upload (breaks 憲法 #3).
- cal.com platform starter kit (Supabase blog, 2024-06-18) — the server-issues-a-signed-upload-URL
  pattern, rejected for the same reason. Recorded so it is not re-proposed.
- `supabase-py` / `storage3` — a dependency for five HTTP calls against an API this repo already
  calls elsewhere. Not adopted.
