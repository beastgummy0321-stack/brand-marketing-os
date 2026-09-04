/** 圖表分類色（票 03-cockpit-kpi-chart）——對應 `frontend/src/styles/tokens.css` 的
 * `--color-chart-revenue`／`--color-chart-spend`，唯一色碼來源見該檔。ECharts 用
 * canvas 畫圖讀不到 CSS 變數，這裡另外存一份十六進位值；改色時兩處要一起改。
 * 只分類（哪條線是哪個指標）不表數值大小（規格圖表鐵則），經 dataviz 技能包
 * validate_palette.js 驗證通過（CVD 相鄰對、正常視力門檻、對比皆過）。 */
export const CHART_COLOR_REVENUE = "#0369a1";
export const CHART_COLOR_SPEND = "#b45309";

/** 票 T6b 座標賺賠圖的「打平線以下」區塊，對應 `tokens.css` 的 `--color-danger`。
 * 只有這一個顏色是「狀態」不是「分類」：一個座標是賺是賠，由它在打平線的上下決定，
 * 顏色只是把同一件事再說一次（座標本身用直接標籤認人，不靠顏色）。所以這張圖從頭到尾
 * 只有一個資料色（`CHART_COLOR_SPEND`），不需要七個分類色，也就沒有色盲相鄰對的問題——
 * dataviz 技能的 validate_palette 對三個狀態色（success／warning／danger）當分類色跑是
 * FAIL 的（`#dc2626`↔`#d97706` 正常視力 ΔE 14.4，低於 15），這是繞開那個 FAIL 的方式。 */
export const CHART_COLOR_LOSS_ZONE = "#dc2626";
