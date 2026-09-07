/** Canvas (ECharts) cannot read CSS variables, so the chart palette from styles/tokens.css is
 * mirrored here. This file and tokens.css are the only two places a raw hex may appear
 * (docs/design-system.md §2, gate: src/designTokens.test.ts). Labels and positions carry
 * meaning as well as color. */
export const CHART_COLOR_REVENUE = "#7055d8"; // --color-chart-revenue
export const CHART_COLOR_SPEND = "#397cda"; // --color-chart-spend
export const CHART_COLOR_LOSS_ZONE = "#c53945"; // --color-danger
export const CHART_COLOR_LABEL = "#202237"; // --color-foreground
export const CHART_COLOR_AXIS_TEXT = "#626b80"; // --color-muted-foreground
export const CHART_COLOR_GROUND = "#f6f7fb"; // --color-background
