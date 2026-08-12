import type { Meta, StoryObj } from "@storybook/react-vite";
import { CYCLE_ROAS_STAT, CYCLE_SPEND_STAT } from "./fluidCardFixtures";
import { Skeleton } from "./Skeleton";
import { StatBig } from "./StatBig";

const meta = {
  title: "layout/StatBig",
  component: StatBig,
} satisfies Meta<typeof StatBig>;

export default meta;
type Story = StoryObj<typeof meta>;

/** 正常：正向趨勢。 */
export const Normal: Story = { args: CYCLE_ROAS_STAT };

/** 空：還沒有值可顯示，退化成「—」而不是空白。 */
export const Empty: Story = { args: { value: null, label: "本期 ROAS" } };

/** 失敗等效：負向趨勢（花費超支），顏色與圖示切成警示語意。 */
export const DownTrend: Story = { args: CYCLE_SPEND_STAT };

/** 進行中：數字還沒讀完，骨架佔位。 */
export const Loading: Story = {
  args: { value: null },
  render: () => (
    <div className="flex flex-col gap-1">
      <Skeleton className="h-8 w-24" />
      <Skeleton className="h-4 w-16" />
    </div>
  ),
};
