# A creative Meta failed to return once is never asked for again, and there is no way to retry

Status: open (found 2026-09-08 when the user's first look at the history screen hit walk fixture rows).

Cause: ADR 0067 §1.9 caches the creative on `imported_ad` and rules "a `None` is never refetched"
(`app/schedule/history.py` `_needs_creative_fetch`: a row with `creative_fetched_at` set is skipped, whatever
its `creative_body`). Meant for deleted ads; it also freezes a transient failure — an expired token, a Graph
hiccup, or an id that was never Meta's — as 「Meta 現在回不出這則的素材」 forever, with the owner having no
button to try again. The fetch itself works on the real account (checked 2026-09-08: ad
`120234301113370671` returned body, image_url, `created_time`, `effective_status` ARCHIVED).

Impact: wording only, but it is the one line the owner needs to recognise the ad; a stale `None` makes the
whole card useless.

Fix shape (route B, one ticket): on the history GET, retry ids whose `creative_body` and `creative_image_url`
are both NULL when `creative_fetched_at` is older than 24 h (at most 15 calls, the same cap as the first
fetch); plus a per-page 「重新抓素材」 button that clears `creative_fetched_at` for the cards shown. Also
seen: `creative.title` can be a dynamic template literal (`{{product.name}}`) — show it as-is, but prefer
`body` over `title` for the card headline.
