import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { EmptyState } from "./EmptyState";
import { FluidCard } from "./FluidCard";
import { Skeleton } from "./Skeleton";

const meta = {
  title: "layout/FluidCard",
  component: FluidCard,
} satisfies Meta<typeof FluidCard>;

export default meta;
type Story = StoryObj<typeof meta>;

/** 正常：展開態，卡片殼＋標題＋內容。 */
export const Normal: Story = {
  args: {
    title: "本期成效",
    subtitle: "檔期一・進行中",
    children: <p className="text-sm text-foreground">ROAS 2.4×，較上期成長 0.3×。</p>,
  },
};

/** 收合摘要：R1-2「其他階段收合成摘要卡」的樣子，點標題可展開（互動見 Interactive）。 */
export const Collapsed: Story = {
  args: {
    title: "企劃",
    collapsible: true,
    expanded: false,
    collapsedSummary: "已完成 · 目標 CPA 320 元",
    children: <p className="text-sm text-foreground">企劃內容（收合時不渲染）。</p>,
  },
};

/** 失敗：卡內容是錯誤空狀態，卡殼本身不特別變色（錯誤語意交給內容區的 EmptyState）。 */
export const ErrorContent: Story = {
  args: {
    title: "本期成效",
    children: <EmptyState title="讀取失敗" description="成效資料讀取失敗，請稍後再試。" />,
  },
};

/** 進行中：內容區用骨架佔位（沿用既有 Skeleton，不是文字「讀取中」）。 */
export const Loading: Story = {
  args: {
    title: "本期成效",
    children: (
      <div className="flex flex-col gap-2">
        <Skeleton className="h-4 w-1/3" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    ),
  },
};

/** 互動：點標題可展開收合，驗證 grid-template-rows 動畫與 chevron 轉向。 */
export const Interactive: Story = {
  args: { children: null },
  render: () => {
    function Demo() {
      const [expanded, setExpanded] = useState(false);
      return (
        <FluidCard
          title="企劃"
          collapsible
          expanded={expanded}
          onToggleExpand={() => setExpanded((v) => !v)}
          collapsedSummary="已完成 · 目標 CPA 320 元"
        >
          <p className="text-sm text-foreground">展開後的完整企劃內容。</p>
        </FluidCard>
      );
    }
    return <Demo />;
  },
};
