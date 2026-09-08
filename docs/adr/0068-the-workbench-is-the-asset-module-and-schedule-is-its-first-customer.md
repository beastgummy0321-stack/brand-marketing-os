---
id: 0068
decision: The workbench module owns briefs and outputs; schedule submits briefs and reads adopted outputs, never the reverse.
applies-to: [app/schedule/, supabase/migrations/, frontend/src/components/schedule/, app/methodology/, app/departments/, app/workbench/, app/departments/workbench/]
supersedes: none
status: in-force
---

# The workbench is the asset module, and schedule is its first customer

`applies-to` names only paths that exist today; the ticket that creates `app/workbench/`,
`app/departments/workbench/` and `frontend/src/components/workbench/` adds them to the line above
in the same commit (the index refuses a path that does not exist).

2026-09-09, Gate A for the 素材工作檯 module, signed by the user the same day. Module-boundary
decision (constitution rule 2). Fulfils **ADR 0047**, which said the finished image prompt
"belongs to the asset module, which does not exist yet and inherits this job when it is built" —
this is that module. Constitution rule 10 is **not** amended: producing a prompt is not
generating an image; the image-generation seat stays reserved (see "What we looked at").

## The decision

1. **One new module, `app/workbench/`**, brand-level, a sidebar entry beside 檔期規劃 (the
   `CONTEXT.md` entry 素材工作檯 already places it there). It owns two tables and their
   migrations (ADR 0049 prefix `workbench_`):
   - `workbench_brief` — the 創意簡報 of `CONTEXT.md`: `kind` CHECK
     (`ad_creative`／`copy`／`image_prompt`／`video_script`／`free`), `source_kind` CHECK
     (`schedule_node`／`manual`), `source_ref jsonb` (for a schedule node: `node_key` +
     `source_tree_task_id`), `product_id` nullable, the seven `*_key` columns +
     `coordinates_snapshot_json`, `visual_tone` (the same two-value CHECK as
     `creative_candidate`), `visual_concept`, `request_json` (lengths, variant counts, prompt
     count, `use_brand_knowledge`, free text), `status` CHECK
     (`queued`／`running`／`done`／`failed`／`closed`), `closed_at`, `created_by`.
   - `workbench_output` — the Nth round of one part of a brief: `brief_id` ON DELETE CASCADE,
     `part` CHECK (`copy`／`image_prompt`／`video_script`／`free`), `generation_round`,
     `body_json`, `coordinates_json`, `adopted_at`, `llm_task_id`, and the **image-generation
     seat, all nullable and unwritten today**: `storage_key`, `provider`, `provider_job_id`,
     `provider_status`. `UNIQUE (brief_id, part, generation_round)`.
2. **Dependency direction is one-way: schedule → workbench.** `app.schedule` imports
   `app.workbench` (its `__init__`), calls `submit_brief()` once per deepest tree node when a
   tree succeeds, and reads `adopted_output()` when it shows a node or scores spend. The
   workbench imports nothing from schedule and knows no tree; a brief from a schedule node is,
   to it, a brief with a `source_ref` it stores and never interprets.
3. **`creative_slot` / `creative_candidate` / `creative_candidate_item` stay with schedule.**
   They are the loop's memory (ADR 0050, 0057, 0064): which fingerprint each tree node ran with.
   ~~`creative_slot` gains one nullable column `brief_id`~~ — **amended 2026-09-09 before ticket
   05**: not needed and not added. The slot is already located by `(node_key,
   source_tree_task_id)` and the brief's `source_ref` carries exactly those two keys, so the join
   is data the two modules already share; a column would be a second copy (rule 7). When schedule
   reads a node whose brief has an adopted `copy` output, it upserts the `creative_candidate` row
   from it, idempotent on the output's `llm_task_id` (the column `creative_candidate.llm_task_id`
   already exists and `persist_creative_result` already keys on it) — a read that seeds its own
   cache, the precedent being `GET .../history` (schedule contract, decisions in force). The
   workbench never writes a schedule table.
4. **Copy is made in the workbench and taken from the schedule page.** The 素材準備 stage of
   檔期規劃 (`docs/design-system.md` §5.1, already assigned "creative list · content, coordinates,
   copy actions") shows every deepest node's 投放包 — the adopted copy with a copy button per
   field — read through `adopted_output()`. Changing version, re-running a round, producing image
   prompts and free generation happen in the workbench. One producer, two counters.
5. **The 產素材 button is removed.** A successful tree submits its briefs and enqueues the copy
   part itself. The `schedule_creative` task type, `app/departments/creative/ad_creative.md` and
   the parsing half of `app/schedule/creative.py` retire once their callers reach zero
   (`COORDINATE_KEYS` and the coordinate validators stay — history and the vocabulary route use
   them). Image prompts are **not** produced automatically: the user sets the count on the brief
   (decision 7), so the first request for prompts is the user's press.
   **Where the visual direction comes from once `schedule_creative` retires (amended 2026-09-09,
   before ticket 05):** the workbench copy call returns `visual_tone` and `visual_concept` beside
   the copy — the writer who chose the angle names the picture — and the job writes them onto the
   brief; the sync of decision 3 mirrors them into `creative_candidate`. Still exactly one
   direction per node, still one to two sentences, still never a finished prompt outside the
   workbench: ADR 0047's rule survives with its producer moved, and its `decision` line is
   reworded in ticket 05 to say so (the gate test `Adr0047VisualDirectionGateTest` keeps its
   scan; its tail assertions on `ad_creative.md` go with that file). A schedule-node brief takes
   `product_id` = the plan's first product and `request.product_ids` = all of them; brand context
   is compiled per listed product, as the retiring job did.
6. **One brief = one procrastinate job = one LLM call per part, JSON-only reply.** The copy call
   carries: the workbench copy task file, the methodology rows for the new task labels (below),
   the brief, the product's compiled brand context (one product, not one per tree product), the
   coordinate vocabulary last. The image-prompt call carries the brief, the adopted (or latest)
   copy's headline set for the 「」 on-image text, and the image-prompt methodology. No narrative,
   no second prose block: the shell parses one JSON object. Program-side validation, no tokens:
   character ranges, variant counts, coordinates in the vocabulary, headline/description limits.
   One item out of range is re-asked alone; the batch is never re-generated.
7. **Image prompts are 200–250 characters each for the whole rendered prompt (user ruling
   2026-09-09), written in Traditional Chinese (user ruling 2026-09-09), in the user's eight-module
   template rendered as nine lines — one module per line** (`app/methodology/image-prompt-template.md`
   §2; the fourteen-line rendering was measured at 449–593 characters with a 202–280-character fixed
   block on 2026-09-09, so the user chose to trim the template, not the number). The program splits
   the template into a **fixed block** (format + medium, capture style, human, 保留｜禁止) produced
   once per brief and asserted identical across all N prompts, and a **variable block** (theme + on-image
   text, scene, subject placement, relation, authenticity) that differs per prompt. That is what
   makes 1–10 prompts one set for Meta's flexible format — held by a test, not by the model's memory.
   Measured after the trim: 6/6 prompts at 212–218 characters, fixed block 103.
   **Capture style is a catalogue, not code** (user ruling 2026-09-09): a data file in the module
   (`app/workbench/image_styles.json`, ADR 0056's pattern), one entry per style, default `ugc`;
   `workbench_brief.style_key` holds the choice from day one (rule 3). Adding a style is one entry;
   a schedule-suggested style or a user-picked one in a manual brief is a value in that column, never
   a migration. Style governs how the shot is taken and how imperfect it may look; `visual_tone`
   governs light and colour; both meet in the 攝影形式 line.
   The count N is the user's: an integer field on the brief, beside one fixed grey line of copy —
   「AI 生圖有不確定性，建議多產幾條備用，建議目標張數的 1.5 倍」（user's wording, 2026-09-09）.
   No default is generated for them.
8. **Copy lengths and variant counts** (user ruling 2026-09-09): three lengths per brief, each
   with a fixed one-line "when to use" written by the program (zero tokens):
   短 100–150 字 ×5 「折疊前一口氣講完，適合再行銷、已認識品牌的人」·
   中 300–500 字 ×3 「痛點→證明→優惠，適合第一次看到你的人」·
   長 800–1000 字 ×2 「說故事，適合高單價、需要被說服的商品」.
   Plus 標題 ×5 (≤27 字, `meta-format-specs.md` §1) and 說明 ×5 (≤30 字, same). The 1000 ceiling
   sits under Meta's hard maximum of 1024 characters per body (asset_feed_spec options, verified
   2026-09-09, URL below). The variant split 5/3/2 is the user's; the reason recorded: Meta accepts
   at most five bodies per ad and the user pastes one length, and five genuinely different
   800-word stories from one call degrade into paraphrase, which `humanizer-zh-tw.md` forbids.
   **Measured 2026-09-09** (ticket 01 probe, `gpt-5.6-luna` via local codex, 7 runs): the model
   writes 60–70% of any stated length — short 84–111, medium 209–328, long 507–809 — whether asked
   for the band or for a target at its upper edge (140／450／950), and splitting into three calls
   changes nothing. User ruling the same day: **the bands stay; the task file states the upper-edge
   target; whatever still falls short is re-asked once by the fix call of decision 6**, and a body
   that still misses its band is shown with a ❌, never discarded. Swapping to a stronger model is a
   settings choice the user can make per task (decision 9), not a change to this ADR.
9. **Methodology** (`app/methodology/README.md` gains three task labels): 素材工作檯文案 →
   `copywriting.md`, `humanizer-zh-tw.md` (new; distilled from Humanizer-zh-TW, MIT, the 24 rules
   trimmed to those that apply to ad copy), `customer-voice.md`, `meta-format-specs.md`;
   素材工作檯圖片提示詞 → `creative-matrix.md`, `image-prompt-template.md` (new);
   素材工作檯影片腳本 → `creative-matrix.md`, `copywriting.md`, `humanizer-zh-tw.md`. Task files
   live in `app/departments/workbench/` (ADR 0028). Four task types (`workbench_copy`,
   `workbench_image_prompt`, `workbench_video_script`, `workbench_free`) join the settings page
   task→model table; per-task model choice is the user's there, not a constant.
10. **Manual briefs always belong to the brand the user is in.** "不掛鉤品牌" is
    `request_json.use_brand_knowledge = false` — the prompt omits brand context — never a
    brand-less row (constitution rule 2). A brief can be closed (hidden, reversible) or deleted
    (with its outputs, confirmed); a schedule-sourced brief closed or deleted leaves the tree
    untouched. A re-expanded tree gets new briefs; the old ones stay, flagged as belonging to a
    previous structure, and close in one press.

## Numbers and their sources

| number | value | source |
|---|---|---|
| flexible format media | ≤10 images, ≤10 videos, ≤30 assets total | developers.facebook.com/documentation/ads-commerce/marketing-api/ad-creative/asset-feed-spec/options, 2026-09-09 |
| bodies / titles / descriptions | ≤5 each; body ≤1024 chars, title & description ≤255 | same page, same date |
| `SINGLE_IMAGE` still an `ad_formats` value | yes | same page. Whether Ads Manager still offers it as a UI option: **not verified** (help-centre pages render client-side; third parties say it merged into format display options in 2026-03) |
| prompt length | 200–250 字 | user ruling 2026-09-09 |
| copy lengths, variants 5/3/2 | above | user ruling 2026-09-09 |
| 1.5× advisory | grey-line text only, no default | user ruling 2026-09-09 |

Because nothing here pushes to the Marketing API, the `SINGLE_IMAGE` question changes one word:
the `format` coordinate dimension gains the value 「彈性格式」 (a `brand_coordinate` row, data,
rule 3); 「單圖」 is not deleted.

## What we looked at

Reuse-first §2. Module-boundary blueprints were searched for ADR 0047 on 2026-09-01 (nothing
mature; the brief/prompt split copied from `Creative-Automation-Pipeline`); not repeated.

**Hosted image-generation APIs, verified 2026-09-09 from vendor docs**, kept here so the seat can
be filled without re-searching. None of the four states anything about non-Latin (Traditional
Chinese) text rendering; that would need an empirical run before any is chosen.

| vendor | model ids as printed | reference images | ratios | price | consistency aid | sdk |
|---|---|---|---|---|---|---|
| Google Gemini API | `gemini-3-pro-image`, `gemini-3.1-flash-image`, `gemini-2.5-flash-image` | yes, up to 6–14 by model, plus a "character consistency" multi-image feature | 1:1, 4:5, 9:16 and seven more | US$0.039–0.24 / image by model and resolution | reference set, no seed | `google-genai` |
| OpenAI Images | `gpt-image-2`, `gpt-image-1.5` | yes, multiple | fixed sizes incl. 1024², 1024×1536, 2160×3840 | token-priced, no flat per-image figure on the pricing page | none documented | `openai` |
| fal.ai | `fal-ai/flux-pro/kontext`, `fal-ai/flux/dev` | yes (`image_url`) | not enumerated | Kontext pro US$0.04 / image; dev US$0.025–0.03 / MP | `seed` | `fal-client` |
| Black Forest Labs | `flux-2-pro`, `flux-2-max`, `flux-1-kontext-pro` … | yes, up to 8 (`input_image`…`_8`) | free `width`/`height` | US$0.014–0.07 / MP by model | `seed` | none official (raw HTTP) |

Sources: ai.google.dev/gemini-api/docs/image-generation and /pricing · developers.openai.com/api/docs/guides/image-generation and /models/gpt-image-2 · fal.ai/models/fal-ai/flux-pro/kontext · docs.bfl.ai/api-reference, bfl.ai/pricing.

**Humanizer-zh-TW** (github.com/kevintsai1202/Humanizer-zh-TW, MIT, installed locally as a
skill on 2026-09-09): adopted as a distilled methodology file, not as a runtime dependency — the
shell cats files into the prompt (ADR 0029) and a skill is a file.

## Considered and rejected

- **Produce the ad copy inside schedule, leave the workbench to prompts and free generation.**
  Rejected: two producers of one artifact (the fault ADR 0047 names) — two prompt pipelines, two
  copies of every writing rule, and free-generation copy drifting from tree copy. The user's
  concern behind it — copying from the schedule page while launching by hand — is met by
  decision 4 instead.
- **Move `creative_slot`/`creative_candidate`/`creative_candidate_item` into the workbench.**
  Rejected: their migrations are applied under the `schedule_` prefix and applied files are not
  edited (ADR 0049); the ownership gate would need a re-mapping for no behavioural gain. They
  record what the loop ran; the workbench records what was made. Different questions.
- **Store outputs as `official_asset` rows via `body_json`** (the door ADR 0050 opened).
  Rejected: `official_asset` is the brand's library of *official* material shown in 品牌智庫 and
  read into every prompt; generated candidates in it would pollute both. The `body_json` /
  `parent_asset_id` / `platform` / `aspect_ratio` columns stay, unused — a generated image file,
  once the seat is filled, lives under `workbench_output.storage_key`, not there.
- **In-app image generation in this goal.** Not built in this goal: the seat (decision 1's four
  nullable columns; the vendor table above) is reserved. Recorded as *deferred*, not as declined.
- **Generate image prompts automatically after a tree expands.** Rejected for now: the count is
  the user's (decision 7) and a default would be a filled blank. Revisit after use; the switch is a
  default value on the brief form, not a migration.
- **A workbench → schedule callback on adopt.** Rejected: it inverts the dependency and makes the
  factory know its customer. Sync-on-read (decision 3) keeps one direction.

## The gate

Prose caps are not caps. Tests, each proven red once before it counts: the fixed block is
byte-identical across all N prompts of one output; every prompt is 200–250 characters; every
body sits in its length band and count; the shell rejects a reply with anything outside one JSON
object; `app.workbench` imports nothing from `app.schedule` (the layer order in
`test_architecture_boundaries.py` places workbench below schedule); `MODULES_WITHOUT_CONTRACT`
does not grow.

## Consequences

- `schedule_creative`, `ad_creative.md` and the 產素材 button retire when their callers reach
  zero, in the ticket that lands the schedule handoff; `creative.py` shrinks to the coordinate
  validators.
- The tree job's cost line becomes: one tree call plus one copy call per deepest node.
- `app/methodology/README.md`'s table gains three rows; `creative-matrix.md` is read whole by the
  image-prompt task although only §2–3 apply (`methodology.compile` loads files, not sections) —
  `ponytail:` ceiling, split the file when the token line hurts.
- Design-system §5.1's 素材準備 stage gets its first real content; §5.2 gains a row for the
  workbench (workspace split: brief list left, brief detail right).
