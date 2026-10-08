# 素材工作檯：生成、素材組、圖片與視覺學習

本頁是此領域的現行決策；只在任務涉及此領域時讀取。邊界與所有權見 [架構入口](../../ARCHITECTURE.md)。
保留原 §5 編號供既有票引用；其他 § 編號由架構入口定位。舊 Feature 編號是來源標記，不是必讀文件。

## 5. 素材工作檯 — settled decisions (2026-09-12 reset)

These are decided. A worker implements them; it does not re-open them. This revision replaces the
2026-09-10 list where they conflict — the IA (old 1–4), the copy contract (old 5) and the reserved
image seat (old 10) are rewritten below. §5.7–§5.10 (image prompts) and the image parts of §5.2,
§5.11–§5.13 were rewritten on 2026-09-15 by F07; the 2026-09-09 【】 8-module template they
replaced is in git. The visual source of truth is the four reference images listed
in git history (retired F02 prototype); where a prototype and an image differ, the image wins.

1. **任務包 → 素材組 → 產物 → 版本.** One 任務包 (pack) holds one or more 素材組 (sets); a set
   holds one 產物 (product) per required content type (文案／圖片／腳本, extensible); a product
   holds 版本 (versions). Display vocabulary only — code and DB names do not change
   (`workbench_brief` is a set, `workbench_output` is a version, `part` is a product type,
   `generation_round` is which round a version came from). The physical pack is one new table,
   `workbench_pack`; every brief carries `pack_id`. 產物類型 are generation parameters, never
   navigation: adding a type must not change the IA and must not add a page.
2. **Rounds are history, never navigation.** A product shows its versions newest round first;
   there is no round switcher and no 建議組合 pool. A version is one selectable artifact and one
   `workbench_output` row (`version_index` inside its round): a copy round writes 5 rows, an
   image-prompt round writes 10 rows (one per prompt; a 輪播 round writes 2 rows, one per concept of
   5 cards — §5.7), a script round writes one row per script.
3. **States are derived, never stored twice.** product: 未生成 (no version) ／待選定 (versions
   exist, fewer selected than required) ／已選定 (selected count ≥ required). set: 待開始 (no
   product has a version) ／等待決定 ／已完成 (every required product 已選定). pack: 待處理 (no
   set started) ／進行中 ／待核准 (every set 已完成, not yet approved) ／已完成 (approved). The
   only stored pack state is `approved_at` plus the completion ticks. A set-table cell reads
   `已選定／需要` (e.g. 2／5), reads 未生成 when no version exists, and reads 「—」 when the set
   does not require that type — one rule, no other spellings. That rule lives in the repository
   derivation and the cell text ships with the API (`cells[].text`); the browser renders the string
   it is given and never re-spells it. Same for the reserved-seat line (§5.11).
4. **The upstream handoff contract.** An upstream module hands over one pack in one call,
   `submit_pack(conn, org_id, brand_id, pack)`; the workbench never learns how the upstream works
   and still only stores and compares `source_ref`, never interprets it. `pack` carries: `source`
   (`source_kind` ＋ opaque `source_ref`), `name`, `context` (brand／product／campaign ids, plus
   the two optional display strings `origin_label` and `origin_href` — 2026-09-12: the upstream
   supplies the origin line and the in-app path back to itself, both stored verbatim in the
   existing `context_json` and returned verbatim by `pack_detail`／`set_detail`; the workbench
   renders them and never parses them, so removing the upstream just removes the line.
   `origin_href` is a router path *without* the `/app` basename, e.g.
   `/brands/<brand>/ads/campaigns/<id>?tab=assets`, and both values must be plain strings),
   `summary` (the 摘要 shown read-only on the pack page: 情境／角度／風格／目標受眾／重點訊息／
   參考連結), `sets` (each: name, opaque `source_ref`, coordinates, product_id,
   `required_outputs` = `{產物類型: 需要選定的版本數}`, and the per-type generation counts — since
   F07 a set's `style_key` and `request.image_prompt_count` are accepted and ignored — an image
   round is always §5.7's fixed shape and its looks come from §5.9 — and `request.variant_count`
   (integer 0–9) is how many ② 變體 the upstream plan wants for that set: the workbench renders that
   count and never computes it, missing or invalid reads 0), and
   `constraints` (e.g. `copy_length`, `promotion_note`). 完成條件 is not sent by the upstream: it
   is §5.5's fixed three-item checklist. 檔期規劃 dispatches one pack per expanded tree, one set
   per deepest node, with `required_outputs = {"copy": 1, "image_prompt": 1}` — one node is one
   ad, so it needs one selected copy and one selected image prompt. `submit_brief` stops being a
   public entry: a set only exists inside a pack.
   `required_outputs[type]` (how many versions must be 選定 before the product is 已完成) and the
   per-type generation count (how many versions one round writes) are **two different fields**;
   neither defaults to the other. 自由創作 fills both from its parse (§5.12): the count the user
   asked for, 1 per requested type when they said none.
   `free` is **not** a valid `required_outputs` key — it is a legacy part name
   (`repository._PART_NAMES`, `app/departments/workbench/free.md`) whose rows predate packs and are
   unreachable from the new screens; the pack's own origin is `source_kind = "free_job"`, so the
   two words never collide. New packs ask only for `copy`／`image_prompt`／`video_script`, and the
   API owns the one label map (文案／圖片／腳本).
5. **核准整包：完成條件可人工覆核；承諾來源僅提醒，由使用者確認。** 完成條件 is three checks: 「完成所有素材組的必要文案與圖片」
   (computed from §5.3), 「確認內容符合品牌規範」 and 「可核准整包並回報上游」 (human ticks). The
   computed check may be overridden by a person; the override warns, and the warning is skippable.
   2026-09-18 使用者裁決取代 F09 的不可略過檢查：版本回傳 `claim_warning`，前端以橘色指出
   可能未確認的用語；使用者可「確認無誤，選定此版」或「返回查看」。智庫補充入口為選用，
   不要求先新增來源。選定成功沿用 `adopted_at`，重載後不重複確認；切換版本清除確認狀態。
   選定 API 與核准整包不因承諾來源不足拒絕操作，不新增 AI 呼叫或資料表。
   Creative offer/proof coordinates, pack summaries and prior model output are not evidence.
   Copy, image and video generation receive the same source policy: use no offer/endorsement when
   confirmed evidence is absent. The advisory detector in `app/workbench/claims.py`
   covers common trial/discount/gift/guarantee/endorsement expressions; suppressing a warning requires
   exact confirmed brand/product statements or approved claims, plus a fulfilment location for offers.
   Pending, forbidden, high-risk and other-product claims cannot authorize them. Existing outputs
   are rechecked against current sources. F44: a brief's offer coordinate narrows the offer sources —
   `claims.sources(…, offer_key)` and the facade `validate_claims(…, *, offer_key=None)`: `None` = every
   available offer row, `"none"` = none, another key = only that offer's rows; the prompt block then says to
   write no offer or to carry that one sentence, and the version list warns with the same narrowing.
   F46 (Contract O): a RISK offer word is backed only when that exact term (whitespace ignored) appears inside one of the
   narrowed offer sentences (replaces the F42 family-wide backing; 「優惠」 included), and the offer words are widened
   (半價、特價、限時、原價、加購價、組合價、滿 N 送／折、再送、加送、送 N、回饋、點數、抽獎 …; a bare 「送」 is not one). The facade's
   `validate_claims` also returns `missing_offer` = the ad's offer sentences when the copy writes none of them (`[]` for no offer);
   ads asset confirmation refuses on it (ads §6.49.1).
   This is bounded expression detection, not a universal
   semantic fact checker; real model wording and unsupported paraphrases remain a validation limit.
   Approving sets the pack to 已完成 and locks its selections — F47 (Q7): a pack approved with the manual override keeps
   `approved_at`, but a set that still misses a required output stays open for generating / selecting the missing parts only
   (made selections stay locked); the pack reads 「已核准・還缺 N 組」 and names the first such set. The upstream reads the approval as
   state — `pack_for_source(conn, org_id, brand_id, source_kind, source_ref)` — never as a
   callback, so the dependency stays one-way. 檔期規劃 shows 「素材製作完，可以開始追蹤成效」 when
   the pack is approved, and may still run its own next step without it behind a small skippable
   warning 「還沒製作素材」.
6. **One copy round = 5 complete sets.** A 文案 round returns `sets`: exactly 5 objects of
   `{body, headline, description}` — 主文 in the band `copy_length` names (短 100–150 ／中 300–500
   ／長 800–1000 中文字元), 標題 ≤27 字, 說明 ≤30 字 — and each object is one selectable version.
   The 2026-09-09 copy decisions are void: no per-length body counts (5／3／2), no separate
   `headlines`／`descriptions` pools, no 建議組合. `copy_length` still comes from the node
   (`short` fallback) and still decides the band only.
   The 5 is written once, as `validate.COPY_SET_COUNT`; `validate.BODY_BANDS` carries the band
   `(lo, hi)` only and no count, and every other reader (the copy prompt's 長度 line, the fix
   round's shape hint, a round's version rows) reads the constant.
   `app/departments/workbench/copy.md` and
   `validate.check_copy` carry the shape; `schedule/state.py::_copy_summary` keeps its flat
   `bodies`／`headlines`／`descriptions` lists, now index-aligned from `sets`, so the 素材準備
   stage does not change.
7. **Image prompts: one round = one GPT paste of up to 10 images** (settled 2026-09-15, F07;
   re-planned the same day after probes v3/v4). The bar, in the user's words: 「若系統真的能看行業/風格
   等自適應產出這個Prompt，那真的十分完美。但前提是，系統真得能自己生，而不是靠使用者調適、選風格、下指令。」
   The image engine is GPT (「統一GPT。已經不會變動」). One round is **one model call that writes
   exactly 10 complete natural-language prompts** — GPT chat's per-message image cap. No mode, no
   style pick, no count input: `style_key` and `image_prompt_count` are accepted and ignored, the
   圖片 tab's 「再生成一輪（10 張）」 always asks for one more round, and a new round receives the
   previous round's titles. The shape follows the set's `format` coordinate (key or label, §5.8):
   - **單圖** (`single_image`; a stored `flexible` — Meta has no 彈性 option any more, §3 — reads as
     單圖; also a free pack or no format): 10 independent prompts, one version row each.
   - **輪播** (`carousel`): 2 concepts × 5 cards in the same paste; a concept shares one device,
     layout, look and person; card 1 carries the hook, card 5 the offer/CTA; one version row per
     concept. No variants.
   - **影片** (`video`): no image prompts (「影片廣告不用出圖」). 投放中心 asks a video ad for copy +
     video script (§6.3 item 21). A video set that runs 圖片 anyway gets the 單圖 shape.
   The ratio sentence comes from one table in `app/workbench/visual.py`, copied from
   `app/methodology/meta-format-specs.md`: 單圖 「4:5 直式單圖廣告，1080×1350」 · 輪播 「1:1 輪播卡片，
   1080×1080」.

   **One craft grammar for every industry and style** — `app/departments/workbench/image_prompt.md`,
   built from `.harness/scratch/probes/image-prompt-v4/task_v4.md` (the v2 file's aespa-surface
   examples do not come back): visual device → first sentence names ratio and use → a real layout
   and its typesetting language → at least two concrete details flavoured by the slot's look →
   the subject from the offering's reference → designed typography (every on-image string in 「」,
   tiers, share of frame, one or two colours, position) → a closing sentence of intent from the
   image task. Classification jargon (full audience labels, angle and hook names, task names) never
   goes on the image, and an everyday word is never rewritten into a more abstract one; on-image
   copy uses that industry's customers' own words. A prompt holds only picture and on-image text,
   never a worksheet instruction.

   **What each image must achieve is decided by the system, not by a button**
   (「我需要的是系統自己決定這張圖主訴是什麼自己去給圖，而不是做成按鈕」). The image-task table lives
   once, in `visual.py`. The set's audience key picks the row; `brand.conversion_goal` fills
   `{close}` (purchase 下單 · booking 預約 · lead 留下資料或報名 · awareness 進一步了解 · null 下單);
   only that row is sent:

   | audience | task key · label | 畫面怎麼做 | `subject_role` allowed |
   |---|---|---|---|
   | `cold_unaware` | `stop_relate` 讓人停下來、有共鳴 | 情境反差、比喻、生活觀察，不推銷 | absent, incidental |
   | `cold_problem_aware` | `believe_solution` 讓人相信有解法 | 使用情境、前後對照、把效果或服務現場畫出來（不畫效果數字） | clear, hero |
   | `warm_engaged` | `convert` 讓猶豫的人{close} | 主角主視覺、誘因與截止、打消疑慮 | clear, hero |
   | `customer_repeat` | `come_again` 讓用過的人再{close}一次 | 補齊、時間感、成套 | clear, hero |
   | `lapsed` | `win_back` 讓很久沒回來的人想起來 | 給回來的理由、有什麼不一樣了 | clear |

   `persuasion` allowed = `none` ∪ offer-derived ∪ proof-derived, except `stop_relate` → `none`
   only. Offer: `discount` → offer_headline, price_breakdown · `limited_time` → offer_headline,
   countdown · `bundle`／`trial_sample`／`guarantee`／`free_shipping` → offer_headline · `none` or a
   brand-made key → nothing. Proof: `customer_review` → testimonial, before_after ·
   `founder_voice` → testimonial · `expert_endorsement`／`lab_report`／`media_coverage` → credential
   · `sales_numbers` → data_proof · `none` or a brand-made key → nothing. A set with no audience
   (自由創作) — or with an audience value the table does not know (a brand-made key, or a label
   that matches no vocabulary row) — gets the whole table and returns
   one top-level `image_task`; every item is checked against that row, no visual learnings are read
   for it, and `round.audience_key` stores the value as given. The table changes only by a planner-reviewed code edit.

   **Visual fingerprint.** Every item returns `title` (≤10 characters, for people), `headline` (1–2
   strings, each ≤14 characters, each quoted verbatim in the prompt), `device` (`contrast` 對照／
   `metaphor` 誇張比喻／`borrowed_format` 借用格式／`frozen_moment` 定格瞬間／`demonstration` 直接示範／
   `testimony` 人物證言／`data_visual` 數據具象), `layout` (`candid_scene` 情境畫面／`portrait_focus`
   人物特寫／`subject_focus` 主角特寫／`split_compare` 分割對照／`flat_lay` 俯拍陳列／`magazine_cover`
   雜誌封面／`newspaper_editorial` 報紙編輯／`zine_collage` 拼貼／`infographic` 資訊圖表／
   `social_screenshot` 社群截圖／`screen_mockup` 畫面示意／`type_poster` 大字海報), `look` (the slot's,
   §5.9), `subject_role` (`absent` 不出現／`incidental` 順手帶到／`clear` 清楚出現／`hero` 主角),
   `persuasion` (`none` 無／`offer_headline` 優惠大字／`price_breakdown` 價格拆解／`countdown` 倒數／
   `testimonial` 顧客證言／`credential` 資格背書／`data_proof` 數據證明／`before_after` 前後對比) and
   `prompt`. The fingerprint is image_task + device + layout + look + subject_role + persuasion +
   slot (`exploit` 主力／`explore` 探索). It is stored, shown small, read by 結案 (§6.3), and never
   pasted to GPT.

   **The offering's reference, whatever is sold.** No new asset kinds (「KOL要賣自己，則自己=商品參考。
   講師要賣課，則課的截圖、畫面、教材等=商品參考，牙醫診所要賣預約，則牙醫診所本身照片、案例=商品」):
   `official_asset.asset_kind = 'product_photo'` is labelled 商品參考照 (key unchanged) and its
   `title` is the description. The 商品參考 line lists up to 3 descriptions of the set's knowledge
   product's 商品參考照, else the brand-level ones (`product_id IS NULL`); a missing title reads as
   the product name, else 參考照. The prompt then writes 「主角外型依附上的參考照：<說明>」. No
   reference → the line says so, and the prompt describes only visible traits, never an invented
   package, logo or face.

   **② 變體 — 單圖 only, count from the plan** (「變體只是作主體不變、圖片其他部分些許改變」;
   「依照排程決定，不一定每期每組每個素材都要10張變體」). Rendered at read time from the selected
   version, no model call. `N` = the set's `request.variant_count` (§5.4); missing, invalid or 0 →
   no ②. It keeps subject, person, ratio, text tiers and **every 「」 string of that item verbatim**,
   then lists the first N of nine fixed changes: 1 背景色調 · 2 取景遠近 · 3 文字位置 · 4 強調色 ·
   5 姿勢或表情 · 6 光線時段 · 7 景深 · 8 背景色調＋強調色 · 9 取景遠近＋文字位置. Variants are not
   learned (Meta groups near-identical creatives into one entity; small deltas are noise).
8. **The model writes the prompts; the program plans, appends and checks.** Prompt, in order:
   `image_prompt.md` · the 工作單 — 用途 and ratio; 商品參考; 品牌視覺規範 (the identity text, §5.9);
   每則風格分配, one line per slot 「第 N 則：<look key>（<look label>）」; audience／pain／angle／hook／
   proof／offer as `label（situation）`; 這張圖的任務 with the allowed subject_role and persuasion;
   這一輪手法清單順序, the seven devices shuffled by the program every round (probe v3: an unshuffled
   list put `contrast` first in 6 of 6 brands); 可用字句; 題材 from the pack summary's 情境／重點訊息;
   自由指示; the previous round's titles; 已知的視覺學習 (§5.9) — · the compiled brand context
   (`context_compiler.compile`, as-is). No `app/methodology/**` file is fed. **Coordinate lookup
   matches key or label**: 投放中心 hands keys, 檔期規劃 handed labels; before F07 every
   ads-dispatched prompt carried raw English keys and no ratio.
   The reply shape is requested by one `input_schema` tool in `gateway.TaskOptions.tools` (the
   `app/intake/ai.py` pattern) at thinking `medium`, with per-set enums (`look` = the plan's looks,
   `subject_role`／`persuasion` = the derived row). The schema is a request, not a guarantee —
   Anthropic tool use is not strict and the fix round sends no tools — so every schema rule is also
   a program check, run on the first reply and again on fix-round replacements.
   Program checks, no tokens, per item (輪播: item fields on the concept, text rules per card):
   - `look` equals its slot's look; `device`／`layout` in their lists; `subject_role` and
     `persuasion` inside the derived row;
   - the ratio token in the first sentence; no `【`; no English code
     (`(?<![A-Za-z])[a-z]+_[a-z_]+`);
   - `headline`: 1–2 strings, each ≤14 characters, each verbatim as a 「」 string in the prompt;
   - every 「」 string ≤22 characters and holds no nested 「; ≤6 「」 strings;
   - **no jargon leak**: no 「」 string contains the set's full audience label (the whole `A・B`
     string, never a half), its angle or hook name, 無證明 (the proof label when proof is `none`), or
     the task label. Everyday words are never flagged — pain and offer labels and halves of audience
     labels (太貴、怕買錯、回購、免運、陌生…) — and a term that occurs in the quotable text is exempt
     (滿799免運). Probe v4's 「還在怕選錯理財方法？」 is customer wording and passes.
   - every **fact number** inside a 「」 string occurs verbatim in the quotable text (the set's
     promotion note, the pack's 重點訊息, the compiled brand context); numbers outside 「」, clock
     times and dates are not checked; efficacy numbers never go on the image;
   - at most one negative phrase (the pattern never matches 要不要).
   Per round: more than 10 trimmed, fewer ❌; `headline[0]`'s first 3 characters at most twice;
   ≥5 layouts; ≥4 devices; the 2 輪播 concepts use different layouts. A failing item is re-asked
   once, as a whole item, in the existing fix round; a round-level failure shows ❌. The recorded
   probe outputs are the fixtures (`app/tests/fixtures/workbench/`); CI never calls a model.
   **Each version row stores its own item** — `body_json` = `{title, headline, prompt, text,
   fingerprint, cards, round, validation, warnings}`:
   - `text` = prompt + blank line + `品牌視覺規範：<identity text>` + newline + `風格規範：<look
     texture>`. A carousel concept's `text` is its 5 card texts, each with that tail, joined by a
     blank line;
   - `fingerprint` = `{image_task, device, layout, look, subject_role, persuasion, slot}`, each
     `{key, label}`;
   - `cards` = `null`, or for 輪播 5 × `{headline, prompt, text}`;
   - `round` = `{format, audience_key, image_task, identity_id, identity_text, plan: [{look, slot}],
     look_order: {exploit, explore}, recommended_index, recommended_slot, learning_ids}` — `plan`
     is in slot (shuffled) order; `look_order` keeps the 主力 looks in pool order and the 探索 looks in
     exploration order; `audience_key` is the resolved key, or the value as given when it has no task
     row.
   This is the contract `ads` reads through `adopted_output` (§6.3), using only `fingerprint` and
   `text` — no second export.
9. **The system derives the brand's look, a program allocates it, learnings steer, nothing is
   excluded by a guess.** Reverses the earlier "one look per brand, no style library" call: probe
   v3 proved looks make industries read differently, probe v4 proved the system can derive them
   from facts alone — and that a derived exclusion list is harmful.
   - **Look catalogue** (code, `app/workbench/looks.py`): twelve texture-only families, key →
     (label, texture), texture text from `.harness/scratch/probes/image-prompt-v4/run_v4.py::LOOKS`:
     `phone_raw` 手機原生抓拍 · `flash_snapshot` 直閃快照 · `documentary` 紀實自然光 ·
     `soft_lifestyle` 柔光生活 · `clean_bright` 明亮乾淨 · `studio_hero` 棚拍主視覺 · `dark_luxury`
     暗調精品 · `cinematic` 電影感 · `bold_graphic` 平面大字 · `ui_render` 介面畫面 · `illustration`
     插畫 · `editorial_portrait` 人物專訪. A texture names light, camera and rendering only — never
     who, which colours or which words.
   - **Brand visual identity** (derived and cached; nobody fills anything). One model call,
     task type `workbench_derive_identity` (`app/departments/workbench/visual_identity.md`, thinking
     `medium`), reads the compiled brand-level context and the catalogue and returns `identity`
     (80–150 characters: casting, palette, type personality, mood — no light, camera or bans),
     `fit_looks` (3–5 catalogue keys, ranked) and `excluded_looks` (0–3 × `{look, fact}`). The
     program keeps an exclusion only when its `fact` occurs verbatim in the context it sent: a look
     is excluded only when brand facts say so. (Probe v4 derived 手機原生抓拍 as never-use for Beast
     Gummy from 中高價＋力量感 — the style the user had proven.) The result is one
     `workbench_visual_identity` row per (brand, `brand.knowledge_version`); a fact edit bumps the
     version and the next round re-derives. Two cold rounds in parallel may both call; the first
     insert wins (`ON CONFLICT DO NOTHING`) and both read the stored row, so a pack never mixes
     identities.
   - **Brand-provided look.** Confirmed `visual_base` facts, values joined by a newline, become the
     look `brand_spec` 品牌規範 — ranked first, never excluded, texture = that text verbatim. No
     `visual_base` is a normal state, not a warning. More than 2 negative phrases in it → one
     warning in 品牌智庫 → 品牌事實, shipped as text by
     `GET /api/workbench/brands/{brand_id}/visual-spec` → `{warnings: [{text, href}]}`, which the
     browser calls (no Python import from legacy).
   - **Slot plan** (program, `looks.allocate`, no model). Per round of 10, 7 主力 slots cycle
     through the learned winners — `visual` rows at likely/validated, same audience, scope
     `look=<key>`, not expired, learned within 180 days — or, with none, through the fit ranking
     (`brand_spec` first). 3 探索 slots take the least-tried non-excluded looks outside the 主力
     pool, ordered by adopted items with that look (brand + audience), then items offered with that
     look, then fit rank, then catalogue order. Slots are shuffled for the prompt only (`round.look_order` keeps display order). 輪播: concept 1 = the first 主力
     look, concept 2 = the first 探索 look. The derived ranking is a starting guess; every
     non-excluded look stays reachable (「假設系統今天丟了5個風格，回收回來的前3名被放到品牌成功區，而
     系統之後只會走快樂路徑，不去找其他可能，永遠都在這三個風格繞」).
   - **Exploration reaches the test.** The user picks the hero, so an exploration look is tested
     only if picked. Each round recommends one item (「建議選這張」): a 探索 item when
     `explore_recommendations_so_far + 1 ≤ 0.3 × (brand_image_rounds_so_far + 1)`, else the first
     主力 item; the 探索 pick is the first item holding the least-tried 探索 look. About 3 in 10
     sets therefore recommend exploration whatever the pack size. The pack page warns when fewer
     than 30% of its sets' adopted image rows are 探索. Never a gate — §5.5's 核准整包 never blocks.
   - **Learnings read.** The worksheet carries ≤5 `learning_text` lines of this audience's
     non-expired `visual` rows at likely/validated, not 看不出, within 180 days, newest first, plus
     「另有 N 條沒列出」 (§1 rule 1). Look winners act through the slot plan, not through the model. No
     audience, or an audience value the table does not know → no learnings and the cold-start plan.
   - **Negatives are tiny.** A model-written prompt carries at most one negative sentence naming a
     specific visual thing (「除此之外不放其他文字」); never a legal line, a brand red line or a broad
     ban (「可以有negative prompt，但不能長篇大論或是為了法規限制、品牌紅線等限制創作力」). Red lines stay
     text-side: 絕對不能講 in the brand context and the fact-number check. The appended identity and
     look texture are exempt.
10. **The old style library retires; the look catalogue is code.** `app/workbench/image_styles.json`,
    `repository.STYLES`／`get_style`, `GET /api/workbench/styles`, 自由創作's style dropdown and
    style mapping, the 【】 template `app/methodology/image-prompt-template.md`,
    `prompts.render_hero_prompt`／`render_variant_prompt`／`render_exploration_prompt`, and the
    neutral default spec with its warning retire. `workbench_brief.style_key` stays (applied
    migration), unread. Nobody picks a look; the catalogue changes only by a planner-reviewed code
    edit.
11. **In-site image generation is a reserved port, not a feature.** `app/workbench/image_port.py`
    is one module with one stub: no provider, no key, no cost, no billing, no automation.
    F38 (2026-09-29, user ruling): the port's call shape is fixed but still inert —
    `generate(prompt_cards, *, aspect, count, brand_id) -> list[GeneratedImage{provider, job_id, storage_key, prompt_label}]`
    raises `image_port_not_connected`; picking a provider and a cost cap is a separate user decision, and prompt cards stay
    the product until then. It
    reports 未接上 and the API repeats that, so the 圖片 tab defaults to the prompt view.
    「顯示提示詞」 is a permanent toggle, not a fallback: the same version cards render as
    plain-text prompt cards with a copy button each plus 「複製全部」. Since F07 each image version
    ships `prompt_cards` = `[{label: "NN｜<title>", text: body.text}]` plus, on a **selected**
    單圖-shape version of a set whose `variant_count` > 0, `{label: "② 變體", text}` (§5.7); a
    `fingerprint_text` line (look · layout · device · persuasion labels); and `badges` (「主力」 or
    「探索」, then 「建議選這張」 on the round's recommended item);
    「複製全部」 copies `SetDetail.products.image_prompt.copy_all_text`, the latest round's paste
    block built once by the backend (a lead line, then `第 N 張` + each text). When a provider is
    connected the image view is the same component fed by the port. 席位保留 is never
    phrased as a refusal, and nothing in the product asks the user to run live ads to see a result.
12. **Four screens, one IA.** 素材工作檯 (入口: search ＋ status pills ＋ pack cards ＋ 最近使用 ＋
    快速開始) → 任務包 (pack-local left rail 總覽＋sets, 完成進度, 素材組進度 table, 摘要, 完成條件,
    核准整包) → 素材組 (studio: tabs = that set's required product types in dispatch order, version
    cards, 生成設定, 查看 Prompt, 完成此素材組) → 自由創作 (natural-language front door, two clicks:
    解析 then 建立). 自由創作 creates a pack named 自由工作 #n through the same contract an upstream
    uses, with 品牌 and 商品 both allowed to be 不指定. The 「AI 解析結果」 is **one real model
    call** on the first click (never while typing): `POST /api/workbench/brands/{b}/parse` →
    `free_parse.py` → `gateway.run_task` with an empty context and the department task file
    `app/departments/workbench/free_parse.md` (no `app/methodology/**` change). It returns the spec
    fields 專案主題／需要產出（含張數）／投放平台／尺寸／目標受眾／主要訴求 (風格設定 retired with the
    style library, §5.10 — the reply's `style_hint` key is kept and is always `null`), and the
    second click submits them as `required_outputs`. A failed, timed-out or unparseable call is
    never a dead end: it returns the caller's defaults with `parsed: false` and the user continues. Rails inside the workbench are pack-local or
    set-local; the OS sidebar is untouched. The old `.workspace-split` workbench page (開始生成／
    派工任務／工單 rail) is retired with this revision.
13. **The 生成設定 table is shipped as text, like `cells[].text`.** `SetDetail.generation_settings`
    is a backend-derived **ordered list of `{label, text}`** — since F07: 品牌／商品, 平台, 尺寸,
    品牌視覺, 這張圖的任務, 風格分配, 視覺學習, 主要訊息 — and the 圖片 tab's right column renders it verbatim, row by row, with no
    per-label branch in the browser (§5.3's rule: text the user reads is produced once, by the side
    that owns the rule). Every row is always present; a row with nothing to say reads 「—」, and the
    商品 half of row 1 reads 「不指定」 when the set has no `product_id`. Sources: brand and product
    names from `brand`／`product` via the set's `product_id`; 平台／尺寸 are the same values as
    `chips` (`chips.style` is `null` since F07 — nobody picks a style); 品牌視覺 is the latest image
    round's `round.identity_text`; 這張圖的任務 is that round's `image_task` label; 風格分配 reads
    「主力：<look labels>；探索：<look labels>」 from `round.look_order` (主力 in pool order, so a
    brand-provided look comes first; 探索 in exploration order); 視覺學習 is 「N 條」 from `round.learning_ids` or 「無」 (no round → 「—」 for these four); 主要訊息 is the pack summary's 重點訊息. It is
    a **read-only mirror of what produced the current prompts**, never an input form and never a
    second endpoint fetch. `SetDetail.products[<part>].generation_settings` is a different field
    with a different shape (the per-product run parameters `copy_length`／`count`) and keeps its
    meaning; the table is the top-level one.


### 5.14 生成工作狀態與回程（F10）

素材組 API 的 `generation` 原樣投影 brief 的 status 與 last_error，和「未選定／已完成」等內容選定狀態分開。前端在 queued／running 時停用重複生成，每 3 秒讀取目前素材組直到工作結束；進度讀取失敗保留目前內容並重試。未產出時的 running／failed 不顯示「還沒有生成過」，既有版本保留可讀，failed 可重試。

F47: the brief is committed before its jobs are enqueued (`enqueue()` defers on its own connection and a worker may start at once; an uncommitted brief was the 「找不到工單」 race, `app/workbench/repository.py`). A round that ends `done` clears the old `last_error`; a failed round shows its reason and 重新生成. While the worker is stopped, pages waiting on generation show the shared 「背景程式停了」 notice (`worker_alive`, `app/background/__init__.py`).

全域工作進度使用公開 `workbench.set_action_url` 解析同組織、同品牌的 brief → pack/set 目的地；缺少有效 brief 時回素材工作檯，不再連到已不存在的排程頁。人物誌進度與完成／失敗通知直達智庫 `?tab=customer-voice` 的「人物誌與顧客原話」，沿用既有閱讀、編輯與重試功能。

### 5.15 一般選擇與同頁詳情（F12，已實作）

一般層突出推薦內容、選定、生成狀態、主要再生成動作與完成；精準控制、生成設定、fingerprint 描述、完整提示詞與版本資訊放同頁收合。未接圖片成品生成前，一鍵複製提示詞仍是一般必要操作，不顯示假圖片或稱提示詞為完成素材。未選部分要能直接定位；整包核准阻擋原因直接顯示，探索提醒保持非阻擋。

生成設定仍為本次生成的 readonly 快照，只有原接口支持的 run parameters 才能編輯。不改 F07 十張／輪播／主力探索／腳本／使用者選定／驗證規則，不新增 LLM 呼叫或 provider。F07 原人工驗收内容保持，生成設定／特徵文字改由展開詳情讀取；其未完成驗收不因此結案。

內部整理留在 workbench，外部只經現有 index.ts、API client 與後端 public entry；不從 ads 引入私有 UI 元件，不為共用收合增加業務依賴。表單收合草稿、可存取性與狀態遵循 design-system.md §F12。

### 5.16 One claims guard（F48 Contract G, 2026-10-04）
`claims.forbidden_terms(conn, brand, product_id)` (facade `workbench.forbidden_terms`) is the one 「不能講」 list: forbidden claims and
`forbidden_word` rules of the sell-way's knowledge products plus brand-level ones; another product's entries never apply.
`claims.registered_names` (active product and sell-way names) are stripped before any scan, so 「超能特惠組」 is a name, not a
promise. Approved product claims count as typed (the length／fulfilment filters are for brand facts only). A discount-family word
(折扣、特價、優惠、原價、特惠 …) is backed by any `discount` offer row (decision 7); 限時／買N送／滿額 keep the exact-term rule.
`validate_claims` returns `forbidden_terms`; the workbench warns on them and the ads slot blocks on the same list. The offer an ad
was written for is `live_creative.offer_for` (the dispatch snapshot, else the current key). `workbench.statutory_reminder` serves the
食安法 reminder for slot copy (computed at read, never stored, never blocking).

### 5.17 Background outcomes（F50, 2026-10-05）
Workbench jobs register through `background.register`; a round stuck in queued／running with no live job is reconciled to failed
after `repository.GENERATION_TIMEOUT_S` (the one generation timeout), `material_handoff.start` restarts a failed set on the same
pack, and `free_parse` returns its fallback `reason` and `error_code` (「AI 這次沒有給出可用的結果（…），先照預設往下。」).

### 5.18 Drill 12 creative and control contracts (F52, planned 2026-10-06)

Status (2026-10-07): the F52 repair queue is implemented and locally merged with scoped checks
and independent reviews. Fresh integrated creative quality and human acceptance remain
unverified; the user requested a pause before the next full round. The historical heading/link
anchor is retained, and the quality contract below is not waived.
[F52](../../.work/features/F52.md), [findings](../drills/drill-12/remediation-findings.md) and
[acceptance A02/A03/A10](../drills/drill-12/acceptance.md) define ownership and verification.

The copy brief consumes the accepted ads slot revision from ads §6.54: audience, situation,
selected registered offer, available verified/user-confirmed facts, retained creative, prior
results with sample limitations, and eligible calendar events. Program prepares this context;
the model chooses/writes a proposition. Distinguish a retained control from a new test. A new-test
intent names its substantive audience/situation/proposition change and evidence; replacing words
in the same proposition does not establish novelty. Known relevant calendar opportunities are
used or consciously declined with a reason. No hardcoded brand/audience/holiday, invented urgency
or model arithmetic. A selected offer must survive into the consumer-visible fields; a deliberate
none-offer plan remains possible but cannot replace a promised offer without revision.

Contract tests prove the brief/output connection; independent fresh judging proves usefulness.
No keyword scanner, automatic self-score or repeated-generation-until-pass loop certifies quality.
Preserve exact carried copy/material. Relative best above the cap is not target attainment.

Copy generation continues to produce **five candidate sets per round**. Copy UI has no variable
count suggesting one result; script count stays variable. Existing image-prompt/raster capability
is unchanged. Generating labels bind the current pack/set/part/job identity; the drill12 image-label
observation is a hypothesis and requires a trace before a repair claim.

Shared pack cards gain an explicit noninteractive preview presentation, reused on free-job and
workbench-home screens. Real cards retain actions. Preview omits dead buttons/tab stops instead
of disabling all pointer events while leaving action styling. No new workbench workflow is added.

The existing claims guard remains the only owner. Registered active product/sell-way name spans
are identity, scoped to the brand; surrounding promotional claims still undergo offer/forbidden
checks. Existing name stripping already implements this intent, so the drill12 特惠 failure requires
an exact contextual reproduction. No global token allowance, arbitrary alias generation or entire
sentence exemption is permitted. Workbench warning and ads-slot refusal reuse the same verdict.
Statutory reminders remain distinct from forbidden facts; this work supplies no legal clearance.


### 5.19 First-release learning qualification (F53, planned 2026-10-07)

Status: implemented in the approved F53 queue (2026-10-08); release acceptance remains
separate in the first-release packet. The authoritative
evidence schema, compatibility, support, current applicability and gates are
[ads §6.55](ads.md#655-supervised-first-release-evidence-contract-f53-planned-2026-10-07).
This changes evidence truth/usage, not F52 copy/image quality or its historical acceptance.

The narrow pure `learning_evidence.py` helper is owned by workbench because creative and image
consumers already read the ledger here; ads uses it only through `app.workbench`. It encodes
the existing scope plus versioned trailer, decodes legacy rows, normalizes actual learning_text
and qualifies prepared rows against explicit current inputs. No SQL/model/clock, ads import,
new framework or second ledger. Public signatures are the three functions in ads §6.55.
Source extraction, money and thresholds stay in ads; facade storage remains unchanged.

`looks.visual_learnings` and `jobs` pass the actual brief product, frozen creative audience,
current conditions and org day to this same qualifier. A same-audience learning from another
product, simulation, an operation receipt, expired offer or changed material is not a visual
winner. Unknown scope/provenance stays historical. Retain the existing 180-day visual horizon,
caps, real-data comparisons, source IDs and association caveat. Compare the base visual scope
only after decoding the trailer. Selected known brand facts may support creative propositions;
they never become market proof. No reverse dependency or broad legacy migration.

`planner_context.creative_projection` and the existing `prompts.creative_text` carry the
normalized source/support/eligibility qualification into copy/review. Model-ready sections are
capped, relevant and explicit about unknowns. Historical/control data may support a labelled
test or faithful carry, not automatic promotion. Numbers, truth labels and suitability are
prepared by code; judgment still uses the existing gateway. Preserve five copy candidates,
explicit none offer, original carried creative, claims guard and accepted revision/receipt.
