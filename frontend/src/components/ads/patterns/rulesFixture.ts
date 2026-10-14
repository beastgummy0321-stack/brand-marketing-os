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
    cap: "你願意為一次活動成果付出的廣告費，每個活動自己設",
    on_target: "每次成果成本沒超過這個活動的上限",
    watch: "每次成果成本超過上限，但超過不到 2 成",
    over: "每次成果成本超過上限 2 成以上；這是成本比較，不能單憑此判定盈虧",
    wasted: "花到上限 3 倍的錢，已追蹤成果仍為零；提示支出風險",
    thin: "賣出的廣告都有分數；還沒賣出且花不到上限 3 倍的先標「剛開始」；成交少於 5 筆標「樣本少」",
    money: "以商品貢獻假設比較廣告成本；這是估算，不能當作已付款利潤，差不到 2% 算剛好打平",
    notebook: "系統保留主打的觀察與適用條件；下次先核實是否適用，不代表已證明主打有效",
    break_even: "賣一筆扣掉商品成本和運費後剩下的錢；須核實來源、退款與其他成本，不能只用平台歸因證明盈虧",
  },
  // F50 Contract I: `triage.limits()` as served today.
  limits: {
    review_days: { min: 1, max: 31 },
    review_cadence_default: 7,
    campaign_default_days: 30,
    copy_items_max: 5,
    upload_max_mb: 50,
  },
  // F49 Contract Q: `triage.reasons()` as served today.
  reasons: {
    too_new: { title: "剛開始、數字還不夠", text: "這則廣告還沒賣出，也還沒花到上限 3 倍；再跑幾天數字才夠判斷", fix: "wait" },
    result_unknown_days: {
      title: "有幾天的成果沒讀到",
      text: "平台沒回報這幾天的花費或成果數，系統不把沒讀到當成 0；重新讀取平台資料後再判斷",
      fix: "resync",
    },
    needs_resync: {
      title: "有幾天的資料要重新讀",
      text: "這段期間有幾天沒讀到，或是在系統開始記成果數之前讀的；重新讀取一次就會補上",
      fix: "resync",
    },
    mixed_currency: { title: "混了兩種幣別", text: "這段期間的花費有兩種幣別，系統不會自己換算加總，所以先不判斷", fix: null },
    mixed_result_definition: {
      title: "成果的算法不一致",
      text: "這段期間平台用了不只一種方式算成果（例如歸因設定改過），數字不能直接相加，所以先不判斷",
      fix: null,
    },
    no_previous_window: {
      title: "沒有上一段可以比",
      text: "這則廣告照常判斷划不划算；只是前一段同樣天數的資料不完整，看不出變好還是變差",
      fix: "wait",
    },
    result_kind_unknown: {
      title: "還不知道要算哪種成果",
      text: "這個活動還沒設定要看哪種成果（例如購買），平台資料也沒說；設定後才能判斷",
      fix: "cap",
    },
    target_unresolved: {
      title: "還沒設定上限",
      text: "這個活動還沒設定一筆訂單願意付多少廣告費，沒有尺可以量；設定上限後就會判斷",
      fix: "cap",
    },
    spend_over_target_no_result: { title: "沒賣出", text: "花到上限 3 倍的錢，已追蹤成果仍為零；提示支出風險", fix: null },
    cost_per_result_up: { title: "比上一段貴", text: "跟前一段同樣天數比，每筆廣告費多了超過 2 成", fix: null },
    cost_per_result_down: { title: "比上一段便宜", text: "跟前一段同樣天數比，每筆廣告費少了超過 2 成", fix: null },
    cost_per_result_flat: { title: "跟上一段差不多", text: "跟前一段同樣天數比，每筆廣告費差不到 2 成", fix: null },
  },
};

export { seedAdsRules };

if (import.meta.env.MODE === "test") seedAdsRules(RULES_FIXTURE);
