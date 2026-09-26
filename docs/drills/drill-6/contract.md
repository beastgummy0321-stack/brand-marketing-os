# Drill 6 — plan contract (shared by side A and side B)

One JSON file per side per period. Side A (the outside advertiser) writes it by hand; side B's
is exported from the product by `scripts/drill/export_plan.py`. `scripts/drill/tw_sim.py` reads
both. Unknown fields are `null` — the simulator uses its defaults and the gap list records that
the product never said it.

```json
{
  "side": "A",
  "period": 1,
  "name": "Beast Gummy｜收假週｜首購",
  "start_date": "2026-09-26",
  "end_date": "2026-10-02",
  "objective": "purchase",
  "daily_budget_total": 1500,
  "kpi": {"target_roas": 2.0, "target_cpa": 450},
  "hypothesis": "one sentence: what this period is meant to learn",
  "groups": [
    {
      "name": "冷受眾｜知道自己累",
      "audience_key": "cold_problem_aware",
      "audience_desc": "TW 20–34, interests: 健身 / 大學 / 夜班; exclude buyers 30d",
      "placement": "advantage+ | feed | reels | stories",
      "daily_budget": 900,
      "ads": [
        {
          "name": "unique within the period — the stand-in matches by this exact string",
          "format_key": "single_image | carousel | video",
          "hook_key": "pain_question | outcome_led | never_again | contrast_flip | proof_led",
          "pain_key": "cost | effort | uncertainty | availability | experience | identity",
          "angle_key": "free text or catalog key",
          "proof_key": "none | customer_review | expert_endorsement | lab_report | sales_numbers | media_coverage | founder_voice",
          "offer_key": "none | discount | bundle | free_shipping | trial_sample | guarantee | limited_time",
          "product": "超能特惠組",
          "price": 999,
          "daily_budget": null,
          "headline": "…",
          "body": "…",
          "landing": "https://beastprime.com.tw/…",
          "compliance_notes": "why this copy is legal under 食安法 §28 and Meta's supplement policy"
        }
      ]
    }
  ],
  "notes": "anything the simulator or the judge should know"
}
```

Rules the simulator enforces (see `tw_sim.py` tables):

- `audience_key` picks CPM/CTR/CVR multipliers and, for warm/customer/lapsed pools, a daily spend
  cap (a brand with no pixel history has almost nobody to retarget).
- `format_key`, `offer_key`, `proof_key` are multipliers; `hook`/`angle`/copy only act through the
  judge's `fit`.
- Calendar (TW 2026): 9/26–27 中秋連假尾, 9/28 教師節, 10/9–11 國慶連假, 10/5–8 期中考前,
  10/12–16 期中考週. Context tags from the judge (`student`, `worker`, `driver`, `fitness`,
  `night`, `gamer`) decide who gets the calendar boosts.
- Creative fatigue: an ad name that persists into the next period keeps ageing. Refreshing
  creatives is rewarded; renaming an unchanged ad is cheating and the judge is told to flag it.
- Compliance from the judge: `review` = no delivery on the first two days; `reject` = no delivery
  the whole period (療效宣稱、未成年、誇大咖啡因效果).
