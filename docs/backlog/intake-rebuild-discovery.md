# Discovery: brand onboarding and product onboarding rebuild (from drill 8)

Started 2026-09-30 in `/dig` on `docs/drills/drill-8/report.md` §3 #1 #2. A board, not an implementation authorization.

**Carved 2026-09-30** into `.work/features/F41.md` (drill-8 small items), `F42.md` (brand onboarding) and `F43.md` (product onboarding);
the decisions below now live in those features' Decisions. Delete this file at F43 closeout (or re-carve from it if the split is rejected).

## Root cause (checked against code 2026-09-30)
Brand and product knowledge that only the owner knows is scattered and mostly never asked:
- Asked in the wizard: products + economics, Meta account, conversion goal.
- Only in 品牌智庫 (two levels deep): offers (`brand_coordinate` toggle, default off), proof (`brand_fact` proof + `fact_key`), video capability (`format/video` seed, default on), regulations.
- Re-asked on every new campaign: platform, audience direction (planner never reads it), cap per sale, landing URL.
- The research → paste → truth-card path writes free text; no card sets a proof `fact_key`, so the planner never gets proof.
- Offers live in two unconnected stores: the coordinate toggle (planner) and confirmed facts/claims with a fulfilment location (copy guard `app/workbench/claims.py:74-102`). Turning the toggle on still blocks 「三盒 NT$999 免運」.
- Brand and product are mixed: product-level things (landing URL, cap, audience, lab proof, bundle price) are brand-level or campaign-level today; a bundle of two products cannot be represented (`knowledge_product_id` returns one parent; `intake.md:25` excludes bundles).

## User decisions
- 2026-09-30: offers / proof / media capability are asked at onboarding, not per campaign (rejected the new-campaign 「這期手上有什麼」 card in the F41 prototype).
- 2026-09-30: rebuild onboarding into one complete interview; existing data is test data and may be deleted.
- 2026-09-30: remove the research → paste → truth-card stage; each step is AI-prefilled from the website/photo scan and the user confirms (one writer per fact, every fact has a field).
- 2026-09-30: separate brand onboarding (once) from product onboarding (per product / per bundle, repeatable).

- 2026-09-30 (prototype review 1):
  - Every AI-judged block ends with a 「自訂」 escape: the user describes in plain language, AI turns it into a field value or a new option, saved to the brand.
  - Brand basics take brand photos (logo, store, team, brand image), not product photos; product photos move to product onboarding.
  - Store policies are a registry, not fixed fields (26 types from SHOPLINE / CYBERBIZ / Shopify / 蝦皮 / TW supplement shops; 8 common shown, rest behind 「更多」), each mapped to an offer key or `none` (reassurance). Custom policies allowed via 自訂. The 7-day cooling-off period (消保法 §19) is fixed; 「不適用」 only for a statutory exception with the disclosure text.
  - Everything modular and extensible, especially tools: a connector registry that declares what each connector reads (Meta now; Google/TikTok, GA4, Search Console, shop platforms, MCP, custom API as seats). Extends the `app/schedule/channel_catalogue.json` capability pattern.
  - Brand onboarding is a low-key entry (once); product onboarding is a prominent block at the top of the brand home (經營概況).

## Proposal under review (prototype `.harness/scratch/prototype/f41-onboarding/index.html`)
- Brand onboarding: basics → AI read → who the brand is (positioning, tone, visual) → brand proof + brand policies (free-shipping threshold, returns, trial) + forbidden claims → media capability (photo / video) → tools (Meta, conversion goal) → done checklist → 「建第一個商品」.
- Product onboarding: what it is → who buys and what they worry about → product proof + claims → ways to sell (single, multi-pack, cross-product bundle) with price, list price, cost, shipping, landing URL, cap per sale (default = break-even) → done checklist.
- Offers become data, not toggles: discount/bundle derived from price vs list price on a way-to-sell; free shipping / guarantee / trial from brand policies; the offer coordinate availability is computed like proof.
- New campaign asks only way-to-sell, goal, dates, budget; platform / audience / cap / landing come from the way-to-sell and brand, overridable in a folded 「這期不一樣」.

## Open
- Bundle model: a way-to-sell with components (product × qty) covering multi-packs and cross-product bundles — pending user review of the prototype.
- One way-to-sell per campaign (today) vs several.
- Drill-8 items outside this rebuild still open: #3 rationale display, #4 auto-ready after preview, #5 name truncation, #6 month-budget card on first approve, #11 English codes (F41 prototype screens ②③④ still apply).
