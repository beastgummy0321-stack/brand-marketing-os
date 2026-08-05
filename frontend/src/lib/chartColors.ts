/** 圖表分類色（票 03-cockpit-kpi-chart）——對應 `frontend/src/styles/tokens.css` 的
 * `--color-chart-revenue`／`--color-chart-spend`，唯一色碼來源見該檔。ECharts 用
 * canvas 畫圖讀不到 CSS 變數，這裡另外存一份十六進位值；改色時兩處要一起改。
 * 只分類（哪條線是哪個指標）不表數值大小（規格圖表鐵則），經 dataviz 技能包
 * validate_palette.js 驗證通過（CVD 相鄰對、正常視力門檻、對比皆過）。 */
export const CHART_COLOR_REVENUE = "#0369a1";
export const CHART_COLOR_SPEND = "#b45309";
