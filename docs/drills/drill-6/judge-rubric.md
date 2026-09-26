# Drill 6 — judge rubric (LLM, bounded)

The judge reads one plan file (contract.md) plus `brand-facts.md` and writes `fit_<side>_<period>.json`.
It never sees the other side's plan, never sees simulator numbers, and never writes a number
outside the ranges below. The program does the arithmetic.

```json
{"ads": {"<ad name>": {"fit": 1.0, "tags": ["student"], "compliance": "ok", "reason": "one sentence"}}}
```

## fit — 0.6 … 1.4, default 1.0

Ask: would a Taiwanese person in this audience, on this week's calendar, stop and click this,
and does the copy give them a reason to buy *this* SKU at *this* price?

| Add | For |
|---|---|
| +0.10 | Hook names a concrete situation the audience is in this week (收假第一天、期中考夜讀、連假開車) |
| +0.10 | Copy explains the mechanism (口腔黏膜吸收、不用配水、150 mg＝一杯多的咖啡) instead of adjectives |
| +0.10 | Offer matches the funnel stage (cold → NT$100 體驗包 or 三盒免運; warm → 組合; repeat → 典藏組) |
| +0.05 | Proof is real and specific (a number, a quote, a report), not "many customers love it" |
| −0.10 | Audience/copy mismatch (talks to students, targets 35–54 office workers) |
| −0.10 | Generic energy-drink copy that could be any brand (提神、有效率、更好的自己) |
| −0.15 | Same creative as the previous period under a new name (fatigue laundering) |
| −0.20 | Headline or body is off-brand for a food product (medical, cure, weight loss) |

## tags — zero or more of `student` `worker` `driver` `fitness` `night` `gamer`

Only tags the copy actually speaks to. A tag is what the calendar boosts, so tag laundering
(listing all six) is scored as `fit −0.10`.

## compliance — `ok` | `review` | `reject`

Taiwan 食品安全衛生管理法 §28 (食品不得宣稱醫療效能), 健康食品管理法 (無認證不得稱「健康食品」),
衛福部 caffeine labelling (≥ 200 mg/day warning), and Meta's policy on supplements / personal
attributes.

- `reject`: any of 治療、改善疾病、減肥、燃脂、提升專注力 as a claimed effect、針對未成年、「醫師推薦」without a named real doctor.
- `review`: borderline — 提神／抗疲勞 as a *feeling* with no medical framing, before/after imagery, 「安全」「無副作用」.
- `ok`: describes the product (咖啡因含量、不用配水、口感、攜帶), the situation, and the offer.

`reason` must quote the words that decided it.
