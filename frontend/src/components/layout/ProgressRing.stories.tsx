import type { Meta, StoryObj } from "@storybook/react-vite";
import { ProgressRing } from "./ProgressRing";
import { READINESS_RING_FIXTURE } from "./fluidCardFixtures";

const meta = {
  title: "layout/ProgressRing",
  component: ProgressRing,
} satisfies Meta<typeof ProgressRing>;

export default meta;
type Story = StoryObj<typeof meta>;

/** 正常：交接檢查總分環（GRILL-B4R-performance.md R3-4 「N/M 通過」）。 */
export const Normal: Story = {
  args: {
    value: (READINESS_RING_FIXTURE.passed / READINESS_RING_FIXTURE.total) * 100,
    children: (
      <>
        <span className="text-2xl font-semibold text-foreground">
          {READINESS_RING_FIXTURE.passed}/{READINESS_RING_FIXTURE.total}
        </span>
        <span className="text-xs text-muted-foreground">通過</span>
      </>
    ),
  },
};

/** 空：尚未開始檢查，0%。 */
export const Empty: Story = {
  args: { value: 0, children: <span className="text-xs text-muted-foreground">尚無資料</span> },
};

/** 完成：全數通過，等效於「成功結束」態。 */
export const Complete: Story = {
  args: {
    value: 100,
    colorClassName: "stroke-success",
    children: <span className="text-2xl font-semibold text-success">9/9</span>,
  },
};

/** 進行中：資料還在讀取，轉圈態。 */
export const Loading: Story = {
  args: { value: 0, indeterminate: true },
};
