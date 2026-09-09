# 03 — the loop's guardrails: pairing without an account says so, pairing success is counted, a running period says 「還在進行」, an unknown URL has a page, the disabled 產提示詞 explains itself, 切角 is grouped

route=B: behaviour and copy only; no schema, no entry point, no money, no tenant path. Serves the
board row 工作檯消融與閉環修正 (spec.md). Closes six drill issues in `docs/issues/ui/`
(`issue-pair-without-bound-account-blames-the-name`, `issue-bind-success-is-silent`,
`issue-first-period-message-ignores-a-running-period`, `issue-unknown-url-renders-a-blank-page`,
`issue-image-prompt-button-disabled-with-no-reason`, `issue-angle-select-lists-thirty-five-options`)
— main chat deletes them at close-out. Drill 2 (2026-09-09): 2 of 3 personas approved a tree and
paired with no ad account bound; every node then read 「在 Meta 上找不到」 after zero Graph calls.

## What

### 1. Pairing guard (`app/schedule/binding.py`) and success count (`CampaignTree.tsx`)

- `binding.bind_tree` (`:135`): when `meta_repo.bound_account_ids_for_brand()` returns `[]`, return
  `[NO_ACCOUNT_BOUND]` before the node loop, binding nothing; `bind_failure_message()` (`:33`) returns
  that constant unchanged when it is the only failure (the 「名稱要一字不差…」 tail is wrong for it).
  `NO_ACCOUNT_BOUND = "還沒綁廣告帳戶：到「設定 → Meta 廣告連線」貼權杖並勾選這個品牌，再回來配對。"`,
  a module constant beside `NO_TREE_TO_BIND_MESSAGE`. Routes unchanged (`_run_bind`, `routes.py:327-340`).
- Success count: `CampaignTree.tsx:51` already shows `bindError ?? tree.bind_failure` as an alert. Add,
  when the last bind returned no failure, one `role="status"` line 「配對完成：N／M 個節點對上」 where
  N = nodes in `tree.nodes` (all depths) with a non-null binding and M = all nodes — the tree response
  already carries per-node bindings. Where the alert text contains 「設定」, render 「設定」 as a
  `Link to="/settings"` (what `issue-settings-detour-has-no-link.md` asks; that issue closes too).

Literal — `POST /api/schedule/brands/{id}/tree/bind` with no bound account, HTTP 200:
```json
{"tree": {"bind_failure": "還沒綁廣告帳戶：到「設定 → Meta 廣告連線」貼權杖並勾選這個品牌，再回來配對。",
          "nodes": [{"node_key": "1", "binding": null}]}}
```

### 2. A running period says so (`ScheduleSetup.tsx:117-118`)

`suggestion === null` splits on `schedule.period` (already in the props' `schedule`):
`period.status === "running"` → 「這期還在進行（到 {end_date}）；結束後到檔期面板按「結算這期」，下一期的建議會出現在這裡。」;
`"awaiting_data"` → 「這期已結束，先到檔期面板按「結算這期」。」; otherwise the current sentence.
`PeriodPanel.tsx:39` unchanged (settling stays a hand action after the end date, ADR 0053).

### 3. Unknown URL (`frontend/src/App.tsx:55-76`)

Inside the `RequireSession` group, last: `<Route path="*" element={<NotFoundRoute />} />` using the
existing `layout/EmptyState` — title 「找不到這一頁」, description 「網址可能過期或打錯了。」, action
「回品牌總覽」 → `/`. One step appended to `frontend/e2e/smoke.spec.ts`: open `/app/brands/x/nothing`
→ heading 「找不到這一頁」 visible → click 回品牌總覽 → the overview heading is visible.

### 4. 產提示詞 disabled reason (`BriefDetail.tsx:239-246, :314-315, :463-466, :576`)

Replace the single `title` with one muted line under the button naming the first true reason, in this
order: `brief.closed_at !== null` → 「工單已關閉，重新開啟後才能產」; `busy || localBusy` → 「等目前這輪完成」;
`noSourceForText` → 「先產文案，或在工單填圖上文字」; `!validRequestedCount` → 「填 1～30 的條數」. The
video-script card (`:463-466`, `:576`) gets the same line minus the `noSourceForText` reason. No new
state; the line is derived from the same booleans.

### 5. 切角 grouped (`NewBriefPanel.tsx:216-228`)

The native `<select>` gets one `<optgroup label={category}>` per distinct `category` of the angle
coordinates (`coordinatesApi.ts:34` already carries it; null category → group 「其他」 last), options in
their existing order inside each group; 「不指定」 stays first, ungrouped. Native select + optgroup is
design-system §6 compliant (no custom dropdown).

## How we know it's done

1. `uv run ruff check app` and `uv run pyright` clean.
2. `uv run pytest app/tests/test_schedule.py -q -k "BindTreeApiContract"` green with one new case in
   `BindTreeApiContractTest` (`:964`): a brand with a succeeded tree and **no** bound account →
   `POST …/tree/bind` returns 200, `tree.bind_failure` equals `NO_ACCOUNT_BOUND` exactly, zero
   `channel_entity_map` rows for that brand, and the Meta name lookup was never called (the existing
   fake's call list is empty). Proven red once by removing the guard (per-node 找不到 text comes back).
3. `uv run pytest app/tests/test_schedule.py app/tests/test_architecture_boundaries.py -q` green.
4. `git grep -n "在 Meta 上找不到" app/schedule/binding.py` still finds `_failure_reason` (kept for real misses).
5. `cd frontend && npm run build && npm run lint && npm test && npm run e2e` green (with the new smoke step).
6. `git diff --name-only` ⊆ Shared files touched.
7. WALK (restarted 8720 backend + worker, fresh browser; MOVE Daily `brd_01M22DNZM1BB1RT6Z7TNAHTACP`
   has a bound account and a running period to 2026-09-24; `brd_bughunt` has none — if `brd_bughunt`
   has no tree, run 檔期規劃 → 出方案 → 展開 first, no account needed):
   1. `brd_bughunt` → 投放結構 → 配對 → the alert reads the 還沒綁廣告帳戶 sentence and 「設定」 is a link that opens 設定.
   2. MOVE Daily → 配對 → 「配對完成：N／M 個節點對上」 appears (paste N／M).
   3. MOVE Daily → 設定檔期 → 建議下一期 reads 這期還在進行（到 2026-09-24）.
   4. Open `/app/brands/brd_bughunt/nothing` → 「找不到這一頁」; 回品牌總覽 lands on the overview.
   5. 素材工作檯 → a 完成 brief → 圖片提示詞 card with an empty count → the line 「填 1～30 的條數」; type 3 → the line is gone and 產提示詞 is enabled.
   6. 新工單 → 切角 shows group headings; pick one → 建立 succeeds.
   Screenshots for 1–4.

## Shared files touched

Searched 2026-09-09:

- `bound_account_ids_for_brand`: `app/schedule/binding.py:135` (the new guard reads it; the definition and 13 other readers unchanged).
- `bind_failure_message` / `_failure_reason` / 「在 Meta 上找不到」: `app/schedule/binding.py:33, :105-108` (constant added; per-node text kept) · `app/schedule/routes.py:338-339` (unchanged) · `app/schedule/jobs.py:352` (docstring mention).
- `bind_failure`: `frontend/src/components/schedule/CampaignTree.tsx:51` · `frontend/src/lib/scheduleApi.ts:118` · `app/schedule/tree.py:205` · `app/schedule/tree_approval.py:31` (unchanged).
- `這是第一期`: `frontend/src/components/schedule/ScheduleSetup.tsx:118` only.
- `runDisabled` / `noSourceForText` / `validRequestedCount`: `frontend/src/components/workbench/BriefDetail.tsx:239, :242, :245-246, :314-315, :463, :466, :576`.
- `angleCoordinates`: `frontend/src/components/workbench/NewBriefPanel.tsx:60, :71, :223`.
- `<Route path=`: `frontend/src/App.tsx:52-76`; `EmptyState`: `frontend/src/components/layout/EmptyState.tsx:14`.

Files edited: `app/schedule/binding.py`, `app/tests/test_schedule.py`,
`app/tests/test_architecture_boundaries.py` (ratchets measured), `frontend/src/App.tsx`,
`frontend/src/components/schedule/{CampaignTree,ScheduleSetup}.tsx`,
`frontend/src/components/workbench/{BriefDetail,NewBriefPanel}.tsx`, `frontend/e2e/smoke.spec.ts`.

## Contradiction check

- §1's guard vs done-check 4 (per-node 找不到 kept): the input that separates them is a brand *with* a
  bound account whose Meta has no campaign of that name — the guard must not fire and the per-node
  message must; the new case covers the no-account branch, the existing `BindTreeApiContractTest`
  cases cover the other.
- §2 vs ADR 0053 (settle by hand, after the end): the wording says 「結束後」; an implementation that
  draws 結算這期 while running would contradict the ADR and still pass the walk — the reviewer checks
  `PeriodPanel.tsx:39` is unchanged.
- Cheapest wrong implementation leaving every check green: raising a 400 for the no-account case (the
  frontend shows it via `bindError`, walk step 1 passes) instead of 200 + `bind_failure` — caught by
  done-check 2's literal; a catch-all route placed outside `RequireSession` (an unknown URL renders
  without the shell and without login) — caught by the smoke step only if it asserts the shell's
  heading too, so it does.
