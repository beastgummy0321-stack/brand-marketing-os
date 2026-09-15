# Meta purchases are never ingested — real-data closeouts can only say 看不出

Status: not planned. Found reviewing F07's closed loop (2026-09-15).

- `app/ads/outcome.py::ingest_meta` writes `purchases=0` for every Meta row (outcome.py:140), and
  `_bucket` treats Meta purchases as untracked (outcome.py:162-172). The Meta read it uses carries
  spend, impressions, clicks and ROAS only.
- `sample_bucket` returns 低 below 10 purchases (outcome.py:39-46), so every Meta-sourced
  comparison is 低: F07 visual learning (`app/ads/visual_learning.py`) always writes 看不出, and a
  purchase-metric campaign verdict is 看不出 too. Only `source='simulated'` rows produce a winner.
- Consequence: the image loop (結案 → visual learnings → the next round's 主力 looks) cannot learn
  from real campaigns until purchase count and value come in from Meta.
- Revisit: pull purchase count and value into `ads_outcome_daily` for Meta rows, and keep the
  untracked flag only when the account has no purchase event.
