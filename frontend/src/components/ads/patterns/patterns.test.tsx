/** frontend/src/components/ads/patterns/patterns.test.tsx — F04-I07: 最便宜的證偽，五個斷言。
 * 每個 pattern 是 pure presentational component，這裡不 mock fetch，直接餵 props。 */
import { fireEvent, render, screen } from "@testing-library/react";
import { Sparkles } from "lucide-react";
import { describe, expect, it } from "vitest";

import { ActionTimeline } from "./ActionTimeline";
import { CampaignTile } from "./CampaignTile";
import { DecisionCard } from "./DecisionCard";
import { Disclosure } from "./Disclosure";
import { JudgmentBand } from "./JudgmentBand";
import { KpiStrip } from "./KpiStrip";
import { ReservedSlotCard } from "./ReservedSlotCard";

describe("ads patterns（F04-I07）", () => {
  it("DecisionCard items=[] 印空狀態，沒有「同意」按鈕", () => {
    render(<DecisionCard items={[]} />);
    expect(screen.getByText("目前沒有需要你決定的事")).toBeTruthy();
    expect(screen.queryByText("同意")).toBeNull();
  });

  it("CampaignTile percent=140 進度條寬度夾在 100%，不溢位", () => {
    const { container } = render(
      <CampaignTile
        name="測試 Campaign"
        statusLabel="進行中"
        meta="轉換・Meta"
        spendText="NT$4,500"
        budgetText="NT$3,000"
        percentText="140%"
        percent={140}
        judgment="表現優於預期"
        judgmentDetail="建議維持投放並適度提高預算。"
      />,
    );
    const bar = container.querySelector(".bg-primary.rounded-full") as HTMLElement;
    expect(bar.style.width).toBe("100%");
  });

  it("KpiStrip 每一格的 caption 都印得出來", () => {
    render(
      <KpiStrip
        cells={[
          { icon: Sparkles, label: "平台", value: "Meta", caption: "已連接的通路" },
          { icon: Sparkles, label: "預算", value: "NT$30,000", caption: "本期總預算" },
          { icon: Sparkles, label: "時間", value: "9/15–9/30", caption: "投放期間" },
        ]}
      />,
    );
    expect(screen.getByText("已連接的通路")).toBeTruthy();
    expect(screen.getByText("本期總預算")).toBeTruthy();
    expect(screen.getByText("投放期間")).toBeTruthy();
  });

  it("ActionTimeline items=[] 印 emptyText", () => {
    render(<ActionTimeline items={[]} emptyText="還沒有任何紀錄。" />);
    expect(screen.getByText("還沒有任何紀錄。")).toBeTruthy();
  });

  it("Disclosure 預設收起，點了 label 才看得到 children", () => {
    render(
      <Disclosure label="進階設定">
        <p>進階內容</p>
      </Disclosure>,
    );
    expect(screen.queryByText("進階內容")).toBeNull();
    fireEvent.click(screen.getByText("進階設定"));
    expect(screen.getByText("進階內容")).toBeTruthy();
  });

  it("JudgmentBand 外層不含 surface（會壓掉底色），含 bg-accent/60", () => {
    const { container } = render(
      <JudgmentBand icon={Sparkles} sentence="整體表現穩定" facts="近 7 天無異常" />,
    );
    const band = container.firstElementChild as HTMLElement;
    expect(band.className).not.toContain("surface");
    expect(band.className).toContain("bg-accent/60");
  });

  it("ReservedSlotCard 外層不含 surface（會壓掉底色），含 bg-muted", () => {
    const { container } = render(
      <ReservedSlotCard title="自動執行" description="接上後開放" tag="自動執行接上後開放" />,
    );
    const card = container.firstElementChild as HTMLElement;
    expect(card.className).not.toContain("surface");
    expect(card.className).toContain("bg-muted");
  });
});
