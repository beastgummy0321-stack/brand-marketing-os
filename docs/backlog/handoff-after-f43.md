# Handoff after F43 (2026-10-01)

Start here in the next session. A board, not an implementation authorization. Replaces `handoff-after-f40.md`'s "next" pointer.

## State
- No open feature; queue empty. F41 (drill-8 small fixes), F42 (brand onboarding, 7 steps) and F43 (product onboarding, sell-ways,
  bundles, slim new campaign) are closed on `master` and pushed. As-built: `docs/architecture/ads.md` §6.45–§6.47,
  `docs/architecture/intake.md` F42/F43 sections, ARCHITECTURE §3/§4, CONTEXT terms (全店政策／素材能力／自訂／賣法／組合／顧客群).
- Dev DB (54322) has every F42/F43 migration applied and registered. New background tasks (`intake_scan` prefill, `intake_product_prefill`):
  restart the worker before any browser check.

## Next: drill 9 — rerun B, but re-plan the onboarding part first
Drill 6–8's B script walked the old wizard (paste → truth cards, 賣什麼與數字) and picked a product + 受眾方向 per campaign; none of
that exists now. Keep A (drill-6 rows/fit), the judge rubric, `tw_sim`, the Meta stand-in and the period rules; re-plan only:
1. **Persona script** (`docs/drills/drill-6/persona-beast.md` + a new `drill-9/plan.md`): brand onboarding 7 steps → product onboarding
   (Beast Gummy, sell-ways 隨身體驗包／超能特惠組／終極組合包; 典藏組 = bundle with the T-shirt as a second product) → new campaign
   picks one sell-way.
2. **Brand facts supplement** (`drill-6/brand-facts.md`, same for A and B): state what onboarding now asks — store policies (free
   shipping rule as on the site), brand/product proof actually published (none if none), media = photos only, 1–3 customer groups with
   their worries (from the site's 學生／運動員／上班族／通勤族 and 不 crash／不頻尿／不用配水). Facts only from the 2026-09-26 page.
3. **Website for AI prefill** — decide: a frozen local snapshot of the 2026-09-26 page served by `scripts/drill` (recommended:
   repeatable across drills) vs. the live site.
4. **Measures**: offers present and true (from policies / list price), zero video slots for a photo-only brand, ads' `pain` drawn from
   customer groups, no advanced detour; keep drill-8's rationale / scene / calendar checks.

## Backlog candidates (not planned)
- Retire the old product detail page's AI research / rescan / external handoff and its economics editor (it can freeze a bundle's
  derived cost); move `CapView.knowledge_product_id` into `adsTriageApi.ts`.
- Personas (人物誌) vs product customer groups — onboarding no longer generates personas; decide after drill 9.
- Kit `PickCard` export + compact size (F42 #/b5 uses a local copy).
- From F40: slots `role` counts (主力／探索 chip); per-part generation status; glossary Term for 整期合計.
- `keep/F16-I04` branch (2 unmerged commits from 2026-09-20) and the `marketing-f08-validation` worktree are left untouched.
