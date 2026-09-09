---
id: 0047
decision: One visual direction per ad node travels with its copy from the workbench; a finished image prompt exists only there.
applies-to: [app/methodology/, app/workbench/, app/schedule/]
supersedes: none
status: in-force
---

# The schedule module ships a visual direction, not an image prompt

**Amended 2026-09-09 (ticket workbench/05, ADR 0068 §5).** The producer of the visual direction
moved: it used to be `schedule_creative`'s own generation call in `app/schedule/`, and is now the
workbench's copy call (`app/departments/workbench/copy.md`), which returns `visual_tone` and
`visual_concept` beside the copy text — the writer who chose the angle names the picture. The
rule this ADR states survives unchanged with its producer moved: still exactly one direction per
node, still one to two sentences, still never a finished prompt outside the asset module. This
ADR's own gate test (`Adr0047VisualDirectionGateTest`) keeps scanning `app/methodology/` and
`app/departments/` for more than one image direction per node; only its assertions naming the
now-deleted `ad_creative.md` retired with that file.

2026-09-01, ticket T1a. Module-boundary decision (constitution rule 2). Amends
`app/methodology/meta-format-specs.md` and `app/methodology/creative-matrix.md` §2.

**The schedule module produces the framework a creative is built on. It never produces a
finished image prompt.** The finished prompt belongs to the asset module, which does not exist
yet and inherits this job when it is built.

Per ad node the schedule module emits exactly one visual direction: the seven-dimension
fingerprint (constitution rule 5), plus one `visual_tone` value, plus one plain-language concept
of one to two sentences — the length `app/departments/creative/ad_creative.md:41` already asks for.

## Why the boundary sits here

- Constitution rule 10 puts image generation outside v1; rule 3 requires the column to exist
  anyway. A finished English prompt is v1 doing the thing v1 said it would not do, in the wrong
  module.
- When the asset module is built there would be two producers of one artifact. Container
  contract rule 5 permits duplicate code across modules; it does not permit duplicate
  responsibility for one output.
- Measured on the 2026-09-01 acceptance run (`llm_task`, 6 ad nodes, 126 variants): image
  prompts were 48.0% of creative output — 20 `圖片提示詞` (36.8%) plus 8 `卡片圖片提示詞`
  (11.2%), 2,126 characters. Nothing in the repo consumes them.
- Those 28 came from T1 itself. `meta-format-specs.md:19` asks for 10 per node with no length
  budget; `ad_creative.md:41` asks for one to two sentences. T1 wired the first file into the
  creative prompt for the first time and the larger number won.

## What pins the image, and what is free to move

Reverse-derived and checked against `creative-matrix.md`. Two rules already guarantee that
generation detail cannot reach the viewer's experience:

- §3.1 — text on the image is written verbatim inside 「」 and never left to the model.
- §3.3 — product appearance defers to the reference image; the prompt does not restate it.

With those two fixed, model, bokeh shape and wardrobe may vary freely: the message does not
drift and the product does not deform. Tonality, lighting, framing and lens (§2) sit between —
they do not change the message, but they do change whether two ads read as one brand.

## `visual_tone`: one column, two values, all assets

- **One column, not two.** Copy tone ("高貴奢華感") is a brand-level property, already injected
  into every prompt by `_compile_brand_context`. A per-ad column would copy the brand layer down
  into the ad layer — the same duplicate-responsibility fault this ADR exists to prevent.
- **Values are the two `creative-matrix.md` §2 already proves**: `暗調強對比` (directional rim
  light, 85mm feel) and `暖調生活` (warm soft light, 50mm feel, split framing). No third value is
  invented.
- **§2 is rewritten to apply to every asset, not only real-person ones.** Of the 35 angles,
  `人物出鏡` is 否 for 12 and 可 for 17 — so between 34% and 83% of angles currently fall outside
  §2's stated scope and carry no tonality rule at all. Only the "人物主體" row of §2's layer table
  stays real-person-only; lighting, lens and framing apply to product and card assets too.

## What we looked at

Reuse-first §2: find the projects that already draw this boundary, so the search is not repeated
next month. Searched 2026-09-01. **Nothing mature was found** — the three projects doing this job
are hobby-scale (1, 6 and 14 stars; two state no licence), so none is a dependency and none is an
authority. What they are good for is the shape:

- **`rudreshmehta/Creative-Automation-Pipeline`** (6 stars, no licence stated, Imagen 3 + Gemini,
  Pydantic v2). **Copy the split**: the brief is validated JSON carrying variables only; the
  image prompt text lives in `prompts/product_image_generation.txt` and a `PromptLoader` formats
  it with those variables at the *generation* stage. That is this ADR's boundary, already built by
  someone else — the brief never contains the prompt. Also copy the composition step: brand text
  is overlaid programmatically with PIL after generation, not asked of the model — the same rule
  as `creative-matrix.md` §3.1. **Do not copy** its Dropbox upload, its logo-detection compliance
  pass, or its localisation stage; none is in this module's scope.
- **`IamRamgarhia/OpenAdKit`** (14 stars, MIT). The counter-example, and the one T1 accidentally
  built: it emits ready-to-paste Midjourney/DALL·E prompts and states outright that image
  generation is not in scope. **Copy nothing.** Its boundary is coherent only because it has no
  asset stage at all and never will; we are building one, which is exactly why the prompt cannot
  be finished upstream of it.
- **`sharan1303/creative-ai`** (1 star, no licence stated, FastAPI + Celery — the closest stack to
  ours). Looked at because the stack matched; **rejected as a blueprint**: the brief is structured
  JSON, but the transformation into a prompt is undocumented inside a `genai.py` service layer, so
  it has no boundary to copy.

External, and not a project: the OpenAI cookbook's image-gen prompting guide states verbatim that
"Ad generation works best when the prompt is written like a creative brief rather than a purely
technical image spec" — describe brand, audience, concept, composition and exact copy, and let the
model decide the rest. It supports the premise below. It does not settle the module boundary;
where that brief is *written* is still ours to decide, and this ADR decides it.

## Considered and rejected

Recorded so they are not re-proposed next month.

- **Leave the ten English prompts in the schedule module and let the asset module read them.**
  Rejected: it is the two-producers fault stated above, and it commits v1 to a prompt format no
  image tool has yet been pointed at.
- **Two columns — one copy tone, one visual tone.** Rejected: copy tone already arrives from the
  brand layer via `_compile_brand_context`; a per-ad copy of it is the brand layer duplicated one
  level down.
- **A free-text `visual_tone`.** Rejected: `creative-matrix.md` §2 proves exactly two values, and
  a free-text column cannot be grouped when performance comes back in T5. Rule 3 is satisfied —
  adding a third value is an enum row, not a migration.
- **Keep §2 real-person-only and leave product and card assets with no tonality rule.** Rejected
  on the 34–83% number above: that is most of the matrix carrying no rule at all.

## The gate

Prose caps are not caps. A test asserts that no file under `app/methodology/` or
`app/departments/` asks for more than one image direction per node, or attaches
「無字數預算」 to an image field; and the shell rejects a visual direction longer than the
one-to-two-sentence budget. Proven red once before it counts. The test is built in T1b, not here.

## Consequences

- The manual path shortens but survives (constitution rule 8): the user copies one plain-language
  direction into an external tool instead of ten English prompts. Plain language is sufficient for
  current image models — **the user's call, judged in on 2026-09-01**, and the premise this whole
  ADR rests on. It is not unsupported: the cookbook sentence quoted above says the same thing. If
  it turns out false, what changes is who writes the finished prompt, not this boundary.
- Creative output drops by roughly the 48.0% measured above, before any other change.
- `script` and `hook_pool` in `meta-format-specs.md:52-53` also carry 「無字數預算」 (18.1% and
  7.3% of the same run). This ADR does not touch them; the board carries that row.
