# 08 — the angle dimension is called 「切角」 everywhere it is a label

Route A/B (copy in four label sources; no behaviour, no schema). Rule: `CONTEXT.md` 「廣告素材」 — **切角**
is the canonical word, 角度 is listed under _Avoid_; `docs/design-system.md` §8 (interface vocabulary).
Graduated from `issue-angle-dimension-labelled-角度.md`.

## What

Change the label of the `angle` dimension from 「角度」 to 「切角」 in exactly the places that name the
**dimension** (not prose that uses 角度 as an ordinary word — the methodology files, `quadrant.ts:27`,
`CoordinateQuadrantChart.tsx:207`, `CoordinatesTab.tsx:28` stay as they are):

```
frontend/src/lib/coordinatesApi.ts:15            ["angle", "角度"]  → ["angle", "切角"]
frontend/src/components/schedule/CampaignTree.tsx:10-13   the local COORDINATE_LABELS list is DELETED; the component reads
                                                   `COORDINATE_DIMENSIONS` from `@/lib/coordinatesApi` instead (amended, see ## Blocked)
app/schedule/diagnosis.py:39                     DIMENSION_LABELS["angle"] = "角度" → "切角"
app/departments/creative/ad_creative.md:29,31    `angle`（角度） → `angle`（切角）; the example on :31 「例如角度填」 → 「例如切角填」 (a prompt part; the user authorised it 2026-09-08)
```

Tests that assert the old word follow the code (grep hits in `app/tests/test_past_ads_history.py`,
`test_schedule.py`, `test_schedule_diagnosis.py`, `test_schedule_performance.py` — change only the
assertions that name the dimension label, never a test's shape).

Literal example — the seven dimension labels after this ticket, in order:

```json
["受眾", "痛點", "切角", "鉤子", "證明", "優惠", "格式"]
```

## How we know it's done

1. **Machine gate**: `unset BRAND_OS_LLM_PROVIDER; uv run ruff check app; uv run pyright;
   uv run pytest app/tests/test_schedule_diagnosis.py app/tests/test_schedule.py app/tests/test_schedule_performance.py app/tests/test_past_ads_history.py -q -n 4 --dist loadfile`
   · `cd frontend && npm run build && npm run lint && npm run depcruise && npm test` · `cd frontend && npm run e2e`.
2. **The word is gone from labels**: `grep -rn '"角度"' frontend/src app --include=*.ts --include=*.tsx --include=*.py`
   prints nothing; `grep -n "角度" app/departments/creative/ad_creative.md` prints nothing.
3. **The prompt is consistent**: `jobs._history_text`'s header already says 切角 (ticket 05); after this
   ticket `diagnosis_mod.DIMENSION_LABELS["angle"]` is the same word, so the diagnosis prompt and the
   plan prompt no longer carry two names for one dimension — `grep -rn '"角度"' app/schedule` (quoted
   string, labels only; prose in comments stays) prints nothing.
4. **The shell vocabulary gate stays green**: `uv run pytest app/tests/test_schedule.py -q -k CampaignTreeVocabularyGateTest`
   passes — `CampaignTree.tsx` contains neither 角度 nor 切角 as a literal; the label comes from `coordinatesApi`.

## Shared files touched

Searched 2026-09-08, whole repo, unscoped: `grep -rn "角度" frontend/src app --include=*.ts --include=*.tsx --include=*.py --include=*.md`
→ 19 hits; the four label sources above change, the prose hits stay. Files this ticket edits:

```
frontend/src/lib/coordinatesApi.ts:15
frontend/src/components/schedule/CampaignTree.tsx:11
app/schedule/diagnosis.py:39
app/departments/creative/ad_creative.md:29
app/tests/test_past_ads_history.py, app/tests/test_schedule.py, app/tests/test_schedule_diagnosis.py, app/tests/test_schedule_performance.py   (assertions only, where they name the label)
```

## Contradiction check

- **Done-check 2 (`"角度"` gone from every `.ts/.tsx/.py`) vs the prose hits that stay.** The grep in
  check 2 is quoted-string only, so prose in comments (`quadrant.ts:27`) does not match; input that would
  break it: a comment containing the quoted string — none exists today (the scan above).
- **Cheapest wrong implementation that leaves every check green**: renaming the label in the frontend
  only — check 1's Python tests and check 3's `app/schedule` grep catch it.

## Blocked

2026-09-09, implementer round 1: `CONTEXT.md` 「外殼」 forbids the literal 切角 in shell code and
`test_schedule.py::CampaignTreeVocabularyGateTest` (`_BANNED_WORDS`) enforces it on `CampaignTree.tsx`,
while `CONTEXT.md` 「廣告素材」 lists 角度 under _Avoid_ — the ticket's "change the pair in CampaignTree"
could satisfy neither. Ruling (main chat): the shell does not own the word; `CampaignTree.tsx` drops its
own `COORDINATE_LABELS` list and reads `COORDINATE_DIMENSIONS` from `frontend/src/lib/coordinatesApi.ts`
(one label source, the gate scans the component's own text and stays green). Done-check 3 narrowed to a
quoted-string grep (the ticket's "19 hits" scan counted prose; prose stays). `ad_creative.md:31`'s example
follows line 29. Round 2 = those two edits; the three already-changed sites stand.
