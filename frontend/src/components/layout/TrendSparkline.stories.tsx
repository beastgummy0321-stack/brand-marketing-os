import type { Meta, StoryObj } from "@storybook/react-vite";
import { FLAT_TREND, WEEKLY_BUDGET_TREND } from "./fluidCardFixtures";
import { Skeleton } from "./Skeleton";
import { TrendSparkline } from "./TrendSparkline";

const meta = {
  title: "layout/TrendSparkline",
  component: TrendSparkline,
} satisfies Meta<typeof TrendSparkline>;

export default meta;
type Story = StoryObj<typeof meta>;

/** 正常：每日花費趨勢（R4-3 歷史歸檔頁「趨勢縮圖欄」）。 */
export const Normal: Story = { args: { data: WEEKLY_BUDGET_TREND } };

/** 空：沒有數列可畫，顯示「尚無資料」等效文字而非空白 SVG。 */
export const Empty: Story = { args: { data: [] } };

/** 失敗等效：全部同值（除以 0 邊界），仍要畫出一條水平線而不是報錯。 */
export const FlatEdgeCase: Story = { args: { data: FLAT_TREND, colorClassName: "stroke-danger" } };

/** 進行中：資料還沒讀完，用骨架佔位取代。 */
export const Loading: Story = {
  args: { data: [] },
  render: () => <Skeleton className="h-6 w-20" />,
};
