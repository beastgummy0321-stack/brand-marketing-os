/** frontend/src/components/ads/patterns/patterns.test.tsx — F04-I07: 最便宜的證偽，五個斷言。
 * 每個 pattern 是 pure presentational component，這裡不 mock fetch，直接餵 props。 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Sparkles } from "lucide-react";
import { describe, expect, it, vi } from "vitest";

import { ActionTimeline } from "./ActionTimeline";
import { CampaignTile } from "./CampaignTile";
import { DecisionCard } from "./DecisionCard";
import { Disclosure } from "./Disclosure";
import { FieldCard } from "./FieldCard";
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

  it("Disclosure 第一次展開才掛載，收起後保留草稿且隱藏內容不可聚焦", async () => {
    const user = userEvent.setup();
    const mounted = vi.fn();
    function Draft() {
      mounted();
      return <input aria-label="進階輸入" defaultValue="" />;
    }
    render(
      <>
        <Disclosure label="進階設定"><Draft /></Disclosure>
        <button type="button">下一個操作</button>
      </>,
    );
    expect(screen.queryByRole("textbox", { name: "進階輸入" })).toBeNull();
    expect(mounted).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "進階設定" }));
    const input = screen.getByRole("textbox", { name: "進階輸入" });
    await user.type(input, "草稿");
    await user.click(screen.getByRole("button", { name: "進階設定" }));

    expect(screen.queryByRole("textbox", { name: "進階輸入" })).toBeNull();
    expect(document.querySelector<HTMLInputElement>('input[aria-label="進階輸入"]')?.value).toBe("草稿");
    expect(document.querySelector('[inert] input[aria-label="進階輸入"]')).toBeTruthy();
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "下一個操作" }));

    await user.click(screen.getByRole("button", { name: "進階設定" }));
    expect((screen.getByRole("textbox", { name: "進階輸入" }) as HTMLInputElement).value).toBe("草稿");
  });

  it("FieldCard 的純圖示修改按鈕有具體名稱", () => {
    render(<FieldCard icon={Sparkles} label="預算" value="NT$3,000" emptyText="未設定" source="user" onEdit={vi.fn()} />);
    expect(screen.getByRole("button", { name: "編輯預算" })).toBeTruthy();
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

describe("flow pieces（F22）", () => {
  it("Meter 不知道數值就不畫量尺，只留說明；TodoRow done 換成勾", async () => {
    const { Meter, TodoRow } = await import("./FlowPieces");
    const { container, rerender } = render(<Meter value={null} max={100} tone="danger" left="累積中" />);
    expect(container.querySelector("[aria-hidden]")).toBeNull();
    expect(screen.getByText("累積中")).toBeTruthy();
    rerender(<Meter value={500} max={100} marker={90} tone="danger" />);
    expect((container.querySelector("[aria-hidden] > div") as HTMLElement).style.width).toBe("100%");
    render(<TodoRow no={2} done>關掉開關</TodoRow>);
    expect(screen.getByLabelText("已完成")).toBeTruthy();
  });
});
