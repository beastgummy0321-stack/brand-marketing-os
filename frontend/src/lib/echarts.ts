import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";

/** ECharts 按需引入（票 03-cockpit-kpi-chart）：只註冊駕駛艙用得到的線圖＋格線／
 * 提示／圖例元件，不拉整包（圖表鐵則：本駕駛艙只用折線，無圓餅/儀表盤/3D）。 */
echarts.use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

export { echarts };
