import type { AdsRules } from "@/lib/adsTriageApi";
import { seedAdsRules } from "./rules";

/** The served `GET …/brands/{b}/rules` as `app/ads/triage.py::rules()` returns it today (F48 Contract R-API), for tests.
 * A test that asserts a printed number reads it from here, so a backend change to a rule shows up as one edit here.
 *
 * This file is a vitest `setupFiles` entry (`frontend/vitest.config.ts`): under vitest it seeds these rules before every
 * test file, so every screen renders the served words without a request. A test that needs the not-loaded state calls
 * `seedAdsRules(null)` and restores `RULES_FIXTURE` after. The app never imports this file. */
export const RULES_FIXTURE: AdsRules = {
  grade: {
    watch_band: 1.2, unsold_spend_multiple: 3, min_results: 10, min_days: 7,
    sample_few: 5, near_best: 1.3, break_even_band: 0.02,
  },
  ab: { min_days: 7, min_conversions_each: 10, relative_difference: 0.1 },
  labels: {
    grade: {
      on_target: "划算", watch: "偏貴", over: "太貴", wasted: "沒賣出",
      too_new: "剛開始、數字還不夠", no_data: "資料不足", no_target: "未判斷",
    },
    verdict: { keep: "留下", keep_relative: "留下", replace: "換掉" },
    flags: { few: "樣本少", relative: "相對最好，仍高於上限", relative_no_cap: "相對最好" },
  },
  glossary: {
    cap: "你願意為一筆訂單付的廣告費，每個活動自己設",
    on_target: "每筆廣告費沒超過這個活動的上限",
    watch: "每筆廣告費超過上限，但超過不到 2 成",
    over: "每筆廣告費超過上限 2 成以上，賣越多虧越多",
    wasted: "花到上限 3 倍的錢，還一筆都沒賣出",
    thin: "賣出的廣告都有分數；還沒賣出且花不到上限 3 倍的先標「剛開始」；成交少於 5 筆標「樣本少」",
    money: "拿每筆廣告費跟打平線比：比它低是有賺，比它高是在虧，差不到 2% 算剛好打平",
    notebook: "系統記住哪些主打有效；下次開新活動，AI 會先讀這些，避開沒效的主打",
    break_even: "賣一筆扣掉商品成本和運費後剩下的錢；每筆廣告費超過它，就是在虧",
  },
};

export { seedAdsRules };

if (import.meta.env.MODE === "test") seedAdsRules(RULES_FIXTURE);
