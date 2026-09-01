---
id: 0046
decision: The 2026-09-01 ads-loop rebuild retires eighteen ADRs into docs/adr/retired/, out of the read path.
applies-to: [docs/adr/]
supersedes: none
status: in-force
---

# The 2026-09-01 rebuild retires eighteen ADRs

The ads-loop was re-interviewed from scratch and stress-tested nine times. The data model changed
(ads belong to a channel, a campaign period is a filter, creative carries a seven-dimension
fingerprint, no current-state column answers "what was true then"). `CONSTITUTION.md` and the
ad-loop diagram are now the only source for this module.

Eighteen ADRs are **retired**: moved to `docs/adr/retired/`, which is gitignored. They stay on
disk and stay in git history (`git log --follow`); they are out of the read path. Following
ADR 0030's reasoning, the record is kept rather than deleted — but it is kept where nobody
trips over it.

| Retired | Why |
| --- | --- |
| 0006, 0007, 0008, 0010, 0025 | Governed `app/ads/`, deleted (ADR 0030 already named them) |
| 0011, 0026, 0037, 0044 | Superseded: statistical thresholds now come from `ab-testing.md` §3; brand memory is rebuilt; red lines are a post-generation exclusion list, not prompt rules |
| 0014, 0015 | Governed the hardcoded holiday calendar, deleted by ADR 0036 |
| 0017, 0019 | Governed `docs/ui-migration-contract.md`, deleted 2026-09-01 |
| 0018, 0022 | The three-act product model and its settlement rules are void; the loop replaces them |
| 0023 | Meta write path is now a channel adapter plus `channel_entity_map` |
| 0024 | `app/core/orchestrator.py` is deleted; the `decision` table it owned is reused, not dropped |
| 0045 | Node/time bucketing is re-decided by the campaign-period membership model |

Still binding, unchanged: 0027 (SaaS target), 0028–0036, 0038–0043.
