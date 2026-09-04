import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart, ScatterChart } from "echarts/charts";
import {
  GridComponent, LegendComponent, MarkAreaComponent, MarkLineComponent, TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

/** ECharts 按需引入（票 03-cockpit-kpi-chart 起，票 B4R-warroom 擴充）：只註冊全站用得到的
 * 圖種＋格線／提示／圖例元件，不拉整包。駕駛艙只用折線（圖表鐵則：本駕駛艙無圓餅/儀表盤
 * /3D）；作戰室覆盤／訂單歸因依 GRILL-B4R-performance.md S8R.23-24 契約明定用長條／環形圖
 * （`echarts/core` 模組化引入下，沒註冊的圖種不會報錯，只是該系列悄悄不畫出來——加新圖種
 * 一律在這裡註冊一次，不得各元件各自 `echarts.use()`，否則同一頁重複註冊互相覆蓋）。
 *
 * 票 T6b 加 `ScatterChart`＋`MarkLineComponent`＋`MarkAreaComponent`（座標賺賠圖：泡泡、
 * 打平線、賠錢區塊）。這三個就是上面那句警告最容易踩到的形狀——漏註冊的話圖照樣渲染、
 * 型別檢查與建置全綠，只是那個系列悄悄不見，所以驗收一定要真的看到圖。 */
echarts.use([
  LineChart, BarChart, PieChart, ScatterChart,
  GridComponent, LegendComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent,
  CanvasRenderer,
]);

export { echarts };
