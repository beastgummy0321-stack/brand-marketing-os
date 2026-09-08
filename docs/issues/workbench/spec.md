# 目標：素材工作檯（the asset module）

Status: Gate A signed 2026-09-09 (ADR 0068, `docs/contracts/workbench.md`, CONSTITUTION scope line,
CONTEXT.md 廣告素材 §). Plan review pending. No ticket dispatched yet.

## Outcome the user signed

After a tree expands, every deepest node has usable Meta copy — three lengths with a one-line
"when to use", 5 headlines, 5 descriptions — readable and copyable on the schedule page's 素材準備
stage without a second button. In the workbench the user sets an image count per node and gets
N image prompts (200–250 字, eight-module template, one fixed block shared by all N), re-runs
rounds, adopts one, closes or deletes what they will not use, and opens free briefs (copy / image
prompts / video script / free) with or without brand knowledge. No image is generated in-app; the
seat is reserved (ADR 0068 "What we looked at").

## Why the current output is unusable (measured, not guessed)

- `schedule_creative` loads only `creative-matrix.md` + `meta-format-specs.md`
  (`app/schedule/state.py:50`); `copywriting.md` never reaches the prompt.
- `meta-format-specs.md` §1 sets body at 125 字 (Meta's fold, not its 1024 limit) and
  `ad_creative.md` "篇幅上限" tells the model to keep everything short to avoid truncation — because
  one call writes every node of the tree (`app/schedule/jobs.py:575-636`, `max_tokens=24000`).
- ADR 0047 deliberately stopped at one visual concept per node; the finished prompt was assigned
  to a module that did not exist.

## Screens (design-system §5)

| where | what |
|---|---|
| 檔期規劃 → 素材準備 stage (§5.1, already assigned) | one 投放包 per deepest node: length tabs 短／中／長 with the fixed one-liner, variants each with 複製; 標題 ×5, 說明 ×5 with 複製; a status line 「圖片提示詞：尚未產／已產 N 條」 + 「到工作檯」 link; 「屬於先前結構」 flag when the brief's tree is not the current one |
| 檔期規劃 → 投放結構 right pane | selected node's existing content + one line 「素材：文案完成／產出中／失敗」 |
| 素材工作檯 (new sidebar entry, workspace split) | left: brief list (default filter 進行中＋完成未採用; toggle 已關閉); right: brief detail — copy part (rounds switch, adopt), image-prompt part (count field + grey line + 產提示詞, prompts with 複製, product reference photo thumbnail), video-script part; 再產一輪 / 關閉 / 刪除 (confirm) |
| 素材工作檯 → 新工單 | kind, product (optional), 視覺調性 (two values), 風格 (from `GET /api/workbench/styles`, default UGC), 切角 (brand_coordinate angle rows), free text, counts, 帶品牌資料 switch |

## Ticket 01 result (2026-09-09, probe shipped and deleted)

- JSON-only replies: 7/7 valid once the copy object was flattened (nested `bodies` lost its closing
  brace 5/5 before). `json.loads(strict=False)` is the only tolerance.
- Copy lengths: the local model writes 60–70% of any stated length (see ADR 0068 §8). User ruling:
  bands stay, task file names upper-edge targets, ticket 02's fix call re-asks the rest.
- Image prompts: fourteen lines measured 449–593 字; the user trimmed the template to nine lines
  (ADR 0068 §7); measured after: 6/6 at 212–218 字, fixed block 103.
- Capture style is a growable catalogue with `ugc` as the only entry; `style_key` on the brief.
- Prompt caching: not checked yet (ticket 02).
| 設定 → AI 與費用 | four new rows in the task→model table |

The 產素材 button on 投放結構 is removed in ticket 05.

## Tickets (cut vertically; sequential; each four sections at dispatch)

| # | name | route | lands |
|---|---|---|---|
| 01 | probe: methodology + task files + CLI | B | `app/methodology/humanizer-zh-tw.md`, `image-prompt-template.md`, README rows; `app/departments/workbench/copy.md`, `image_prompt.md`; `scripts/workbench_probe.py` runs both calls for one node of the current Beast Gummy tree via `gateway.run_task` and prints copy + N prompts + the program checks' verdicts. No table, no screen. **The user reads the output before ticket 02 is dispatched.** |
| 02 | tables + repository + jobs | C (schema, module) | `supabase/migrations/<ts>_workbench_brief_output.sql`; `app/workbench/` (entry, repository, jobs for parts copy/image_prompt/video_script/free, validate, prompts); ADR 0068 `applies-to` gains the new paths; `docs/contracts/workbench.md` becomes description; `LAYER_ORDER` (`app/tests/test_architecture_boundaries.py:483`) gains `app.workbench` between `app.llm` and `app.schedule`, and `MODULES` (`app/tests/test_migration_ownership.py:16`) gains `workbench` — both are boundary decisions ADR 0068 already made, not gate widening; `MODULES_WITHOUT_CONTRACT` untouched (page exists). Checks whether the Anthropic provider can mark the methodology block for prompt caching (`app/llm/providers.py` has no `cache_control` today) — verified against the pinned SDK docs, never from memory |
| 03 | routes + API shapes | C (module entry) | `/api/workbench/...` per contract; `frontend/src/lib/workbenchApi.ts` |
| 04 | workbench screen | new screen (prototype → real) | `frontend/src/components/workbench/` via `index.ts`; sidebar entry; design-system §5.2 row; 新工單 form |
| 05 | schedule handoff | C (module boundary; **no schema** — ADR 0068 §3 amended, the slot is found by `(node_key, source_tree_task_id)`) | tree success → `submit_brief` per node; copy call carries `visual_tone`/`visual_concept`; `state` reads briefs; 素材準備 stage 投放包; 產素材 button, `schedule_creative`, `ad_creative.md`, 「廣告內容生成」 row retire; `creative_candidate` seeded through the existing `persist_creative_result`; jobs bell shows 素材生成; ADR 0047 decision reworded |
| 06 | free briefs, video script, closing | B | `app/departments/workbench/{video_script,free}.md` task files + validators; `brand_coordinate` format value 「彈性格式」 seed; pull-out test of `app/workbench/` (container contract §6); CONTEXT/contract touch-ups; board row closes when the folder is empty |

Ticket 05 is the only one that changes a global behaviour (tree → auto copy); its structure
(01–04) lands dormant first, per workflow "two tickets: structure, then flip".

## Plan review (Opus, 2026-09-09) — what it found and what changed

- Input cost was missing from the plan: up to 12 deepest nodes (`campaign_tree.md:53`: ≤4 × ≤3) ×
  ~16 KB of methodology per copy call ≈ **11× today's input tokens** when the provider is
  Anthropic (zero on `codex_cli`). Accepted by the user's rule "quality > tokens"; ticket 02 checks
  prompt caching; ticket 01 measures one call's tokens and seconds so the multiple is a number, not
  a guess. The 73–110 s figure describes the old one-call shape and is not reused.
- `meta-format-specs.md:22` says body 125 字 and would enter the same prompt as the three lengths:
  ticket 01 amends that line (ADR 0068 §8), so one file carries one number.
- The eight-module template existed only in conversation: ticket 01 writes it to the repo
  verbatim and measures the fixed block's own character count before anything else — if the fixed
  block alone leaves no room under 250, decision 7 is reported back to the user, not patched.
- Spec said "layer order untouched"; wrong — corrected in ticket 02's row above.
- The ADR 0047 gate test (`test_methodology.py:374`) flags any methodology/department line that
  pairs an image marker with `N 個/份`; the new files state the count as 「工單指定的條數」 and the
  program injects N at run time. The same test's tail asserts on `ad_creative.md`, which ticket 06
  deletes — that assertion goes with the file, citing ADR 0068 (the decision), not the deletion.
- `TASK_TYPE_LABELS` still lists four `creative_*` types from the deleted `app/ads` era: ticket
  06 replaces them with the four `workbench_*` rows.
- The reviewer's simplest alternative (no module: fix the methodology row, three lengths, copy
  buttons; prompts as one `llm_task` job) is the route the user declined at the premise check
  (2026-09-09) because it has no place for free briefs, rounds, close/delete or the image-prompt
  workflow; recorded in ADR 0068 "Considered and rejected" by reference. Its retained point —
  `workbench_brief` repeats the seven keys `creative_slot` already holds — is deliberate: the
  workbench must serve a manual brief with no slot, and ADR 0050 froze the same keys twice for the
  same reason (rule 7).

## Numbers this plan leans on

| number | source |
|---|---|
| body ≤1024 chars, ≤5 bodies, ≤5 titles/descriptions ≤255 chars, ≤10 images | Meta asset_feed_spec options page, 2026-09-09 (ADR 0068 table) |
| 200–250 字 per prompt; 短 100–150 ×5 / 中 300–500 ×3 / 長 800–1000 ×2; 1.5× grey line | user rulings 2026-09-09 (ADR 0068 §7–8) |
| current creative call: 73–110 s, one call per tree | `app/dashboard/routes_jobs_api.py:35` |
| methodology bytes today: creative-matrix 13,580 + meta-format-specs 3,659 | `wc -c` 2026-09-09 |

## Not in this goal (seats exist)

In-app image generation (`workbench_output.storage_key/provider/*`), video files, pushing to the
Marketing API, remembering the last prompt count as a default.
