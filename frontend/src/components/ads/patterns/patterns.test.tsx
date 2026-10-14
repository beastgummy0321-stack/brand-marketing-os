/** frontend/src/components/ads/patterns/patterns.test.tsx — F04-I07: 最便宜的證偽，五個斷言。
 * 每個 pattern 是 pure presentational component，這裡不 mock fetch，直接餵 props。 */
import { fireEvent, render, screen } from "@testing-library/react";
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
import { RULES_FIXTURE, seedAdsRules } from "./rulesFixture";

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

  it("KindMark cut 印「✂ 清理」，用 kind-cut token（F28-I13）", async () => {
    const { KindMark } = await import("./FlowPieces");
    render(<KindMark kind="cut">清理</KindMark>);
    const mark = screen.getByText("清理").closest("[data-slot='kind-mark']") as HTMLElement;
    expect(mark.dataset.variant).toBe("cut");
    expect(mark.textContent).toBe("✂清理");
    expect(mark.className).toContain("bg-kind-cut");
    expect(mark.className).toContain("text-kind-cut-foreground");
  });
});

describe("grade tokens（F28-I13）", () => {
  it("等級 chip 與填色用 tokens.css 的等級／區間 token，不再用透明度近似", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const { GradeChip, GRADE_FILL } = await import("./Chip");
    render(<><GradeChip grade="on_target" /><GradeChip grade="watch" /><GradeChip grade="over" /><GradeChip grade="wasted" /></>);
    expect(screen.getByText("划算").className).toContain("bg-zone-ok");
    expect(screen.getByText("偏貴").className).toContain("bg-zone-watch");
    expect(screen.getByText("太貴").className).toContain("bg-zone-over");
    expect(screen.getByText("太貴").className).toContain("text-grade-over-foreground");
    expect(screen.getByText("沒賣出").className).toContain("bg-grade-wasted-soft");
    expect(GRADE_FILL).toMatchObject({ watch: "bg-grade-watch", over: "bg-grade-over", wasted: "bg-grade-wasted", insufficient: "bg-grade-thin" });
    // Every grade/zone/kind utility the kit uses resolves to a token that tokens.css defines.
    const css = readFileSync(join(__dirname, "../../../styles/tokens.css"), "utf8");
    const used = [...Object.values(GRADE_FILL), ...[...document.querySelectorAll("[data-slot='chip']")].flatMap((el) => el.className.split(" "))]
      .map((cls) => cls.match(/^(?:bg|text)-((?:grade|zone|kind)-[a-z-]+)$/)?.[1])
      .filter((name): name is string => Boolean(name));
    expect(used.length).toBeGreaterThan(0);
    for (const name of used) expect(css).toContain(`--color-${name}:`);
    expect(css).toContain("--color-grade-watch: #d18a1f;");
  });
});

describe("review pieces（F23）", () => {
  it("EvidenceRow：current null 印待確認、沒有百分比；有值算 ▲/▼；OptionCard reserved 不可點", async () => {
    const { EvidenceRow, OptionCard } = await import("./ReviewPieces");
    render(<EvidenceRow label="已付款" previous={100} current={null} />);
    expect(screen.getByText("待確認")).toBeTruthy();
    render(<EvidenceRow label="花費" previous={2900} current={3000} />);
    expect(screen.getByText("▲3%")).toBeTruthy();
    render(<OptionCard icon="✚" title="換一張圖" note="x" disabledReason="接上後開放" />);
    expect((screen.getByRole("button", { name: /換一張圖/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("接上後開放")).toBeTruthy();
  });

  it("OptionCard 建議標籤：預設「建議」accent；F30 可改字與 neutral（照順序先試）", async () => {
    const { OptionCard } = await import("./ReviewPieces");
    const { unmount } = render(<OptionCard icon="✎" title="只改文案" note="x" recommended />);
    expect(screen.getByText("建議").getAttribute("data-tone")).toBe("accent");
    unmount();
    render(<OptionCard icon="✎" title="只改文案" note="x" recommended recommendedLabel="照順序先試" recommendedTone="neutral" />);
    const chip = screen.getByText("照順序先試");
    expect(chip.getAttribute("data-tone")).toBe("neutral");
    expect(chip.className).toContain("bg-muted");
    expect(screen.queryByText("建議")).toBeNull();
  });
});

describe("loop pieces（F27）", () => {
  it("CampaignChip 依目標出字；ThumbTiles 超過 max 摺成＋N 則；RecoverSteps 標示進行中", async () => {
    const { CampaignChip, ThumbTiles, RecoverSteps } = await import("./LoopPieces");
    render(<CampaignChip objective="sales" name="日常商品推廣" suffix="轉換" />);
    expect(screen.getByText("購")).toBeTruthy();
    render(<CampaignChip objective="other" name="中秋限定活動" />);
    expect(screen.getByText("中")).toBeTruthy();
    render(<ThumbTiles items={[null, null, null]} max={2} />);
    expect(screen.getByText("＋1 則")).toBeTruthy();
    render(<RecoverSteps steps={[{ label: "重新連線", state: "done" }, { label: "補資料", state: "active" }]} />);
    expect(screen.getByText("補資料")).toBeTruthy();
  });
});

describe("v9 pieces（F28-I07）", () => {
  // The prototype's 日常商品推廣 (cap 450 own, break-even 520): cost per purchase = spend ÷ purchases.
  const daily = [
    { id: "a1", name: "晨光隨行杯・日常出發", grade: "on_target" as const, costPerResult: 48, spend: 1440 },
    { id: "a2", name: "晨光隨行杯・隨時有你", grade: "on_target" as const, costPerResult: 50.25, spend: 1407 },
    { id: "a3", name: "辦公室一角・質感桌面", grade: "on_target" as const, costPerResult: 52, spend: 1300 },
    { id: "a4", name: "開箱 15 秒・單手開蓋", grade: "on_target" as const, costPerResult: 55, spend: 1100 },
    { id: "a5", name: "健身情境・保冷 12 小時", grade: "on_target" as const, costPerResult: 431.25, spend: 3450 },
    { id: "a6", name: "再行銷・兩入組", grade: "watch" as const, costPerResult: 520, spend: 3120 },
    { id: "a7", name: "提問式貼文", grade: "over" as const, costPerResult: 617.5, spend: 2470 },
    { id: "a8", name: "秋季新色預告", grade: "wasted" as const, costPerResult: null, spend: 1480 },
  ].map((ad) => ({ ...ad, currency: "TWD", comparisonReason: null }));

  it("TargetRuler 依每筆成本放點，上限線與打平線落在原型算出的位置", async () => {
    const { TargetRuler, rulerScale } = await import("./TargetRuler");
    // Prototype: max = max(1.6 × 450, 617.5 × 1.08) = 720 → cap at 62.5%, 打平 520 at 72.22%.
    const { max, pos } = rulerScale(450, daily.flatMap((a) => (a.costPerResult === null ? [] : [a.costPerResult])));
    expect(max).toBe(720);
    expect(pos(450)).toBe(62.5);
    const { container } = render(<TargetRuler ads={daily} cap={{ value: 450, basis: "own", currency: "TWD" }} breakEven={520} breakEvenCurrency="TWD" size="full" />);
    const cap = container.querySelector('[data-part="cap-mark"]') as HTMLElement;
    expect(cap.style.left).toBe("62.5%");
    expect(cap.textContent).toBe("上限 450 TWD");
    expect((container.querySelector('[data-part="break-even-mark"]') as HTMLElement).style.left).toBe(`${(520 / 720) * 100}%`);
    const dot = (name: string) => screen.getByRole("button", { name: new RegExp(`^${name}｜`) });
    expect(dot("提問式貼文").style.left).toBe(`${(617.5 / 720) * 100}%`);
    expect(dot("晨光隨行杯・日常出發").style.left).toBe(`${(48 / 720) * 100}%`);
    // a1–a4 sit within 4.8% of each other: they stack one level (33px) apart; a4 is the fourth.
    expect(dot("開箱 15 秒・單手開蓋").style.bottom).toBe("99px");
    // 沒賣出 has no cost: it sits in the box, not on the axis.
    expect(dot("秋季新色預告").style.left).toBe("");
    expect(screen.getByRole("group", { name: "對照上限：上限 450 TWD；沒賣出 1、太貴 1、偏貴 1、划算 5" })).toBeTruthy();
  });

  it("TargetRuler 沒上限畫空狀態；暫用打平標在上限位置；清理標出要關的；剛開始的花費未知不印 0", async () => {
    const { TargetRuler } = await import("./TargetRuler");
    const { container, rerender } = render(<TargetRuler ads={daily} cap={null} size="mid" />);
    expect(container.querySelector('[data-variant="empty"]')).toBeTruthy();
    expect(screen.getByText("沒設上限，先不分等級")).toBeTruthy();
    rerender(<TargetRuler ads={daily} cap={{ value: 520, basis: "break_even", currency: "TWD" }} breakEven={520} breakEvenCurrency="TWD" size="mid" highlight={{ mode: "close", ids: ["a7", "a8"] }} />);
    expect(container.querySelector('[data-part="cap-mark"]')?.textContent).toBe("暫用打平 520 TWD");
    expect(container.querySelector('[data-part="break-even-mark"]')).toBeNull();
    expect(screen.getAllByText("關")).toHaveLength(2);
    rerender(<TargetRuler ads={[{ id: "m2", name: "中秋限定・月光藍開箱", grade: "insufficient", gradeLabel: null, costPerResult: null, spend: null, currency: "TWD", comparisonReason: null }]} cap={{ value: 450, basis: "own", currency: "TWD" }} size="full" />);
    expect(screen.getByText("剛開始、數字還不夠 1 則")).toBeTruthy();
    expect(screen.getByText(/已花 未知／1,350 TWD/)).toBeTruthy();
  });

  it.each([
    { currency: undefined, comparisonReason: null },
    { currency: "USD", comparisonReason: "currency_mismatch" },
    { currency: "TWD", comparisonReason: undefined },
    { currency: "TWD", comparisonReason: "unknown_cap_currency" },
  ])("does not put unknown or incomparable money on the ruler ($currency/$comparisonReason)", async (unit) => {
    const { TargetRuler } = await import("./TargetRuler");
    const { container } = render(<TargetRuler ads={[{ ...daily[0], ...unit }]} cap={{ value: 450, basis: "own", currency: "TWD" }} size="full" />);
    expect(container.querySelector("button[data-grade]")).toBeNull();
    const tray = container.querySelector("[data-part=tray]")!;
    expect(tray).toBeTruthy();
    expect(container.textContent).toContain("幣別不同或尚未核實，不能比較。");
    expect(tray.textContent).not.toContain("%");
    expect(tray.querySelector("i[style]")).toBeNull();
    expect(container.textContent).toContain(unit.currency ?? "幣別未知");
  });

  it("F28-I14：TargetRuler 圖片載入失敗（Meta 網址過期）換成中性佔位，不出破圖", async () => {
    const { TargetRuler } = await import("./TargetRuler");
    const ads = [{ ...daily[0], thumbnailUrl: "https://scontent.example/expired.jpg" }];
    const { container } = render(<TargetRuler ads={ads} cap={{ value: 450, basis: "own", currency: "TWD" }} size="full" />);
    const img = container.querySelector("img") as HTMLImageElement;
    expect(img.getAttribute("src")).toBe("https://scontent.example/expired.jpg");
    expect(container.querySelector('[data-part="thumb-placeholder"]')).toBeNull();
    fireEvent.error(img);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector('[data-part="thumb-placeholder"]')).toBeTruthy();
  });

  it("F28-I14：區段字互不重疊——撞到就往右推，放不下時藏起軸說明", async () => {
    const { zoneLabelLayout } = await import("./TargetRuler");
    // Strategy tab at 1024: a ~300px ruler, cap at 62.5% and 1.2 × cap at 75% (+1% each), words 23px, caption 96px.
    const narrow = zoneLabelLayout(300, [0, 190.5, 228], [23, 23, 23], 96);
    expect(narrow.lefts).toEqual([0, 190.5, 228]);
    expect(narrow.caption).toBe(false);
    // Wide detail ruler: everything keeps its zone start and the caption fits.
    const wide = zoneLabelLayout(900, [0, 571.5, 684], [23, 23, 23], 96);
    expect(wide.lefts).toEqual([0, 571.5, 684]);
    expect(wide.caption).toBe(true);
    // One very expensive ad squeezes 偏貴／太貴 together: 太貴 moves right past 偏貴 (6px gap), never on top of it.
    const squeezed = zoneLabelLayout(400, [0, 22, 26], [23, 23, 23], 96);
    expect(squeezed.lefts).toEqual([0, 29, 58]);
    for (let i = 1; i < 3; i++) expect(squeezed.lefts[i]).toBeGreaterThanOrEqual(squeezed.lefts[i - 1] + 23);
  });

  it("GradeChip 依等級出字與色調；null 印未判斷；API 的 grade_label 優先", async () => {
    const { GradeChip } = await import("./Chip");
    render(<><GradeChip grade="on_target" /><GradeChip grade="wasted" /><GradeChip grade={null} /><GradeChip grade="insufficient" label="資料不足" /></>);
    expect(screen.getByText("划算").dataset.tone).toBe("ok");
    expect(screen.getByText("沒賣出").dataset.tone).toBe("stop");
    expect(screen.getByText("未判斷").dataset.tone).toBe("neutral");
    expect(screen.getByText("資料不足")).toBeTruthy();
  });

  it("GradeBand 划算比例＝划算金額÷已花；已花未知時比例也未知", async () => {
    const { GradeBand } = await import("./GradeBand");
    const buckets = [
      { grade: "on_target" as const, amount: 11000, count: 6, ads: [] },
      { grade: "wasted" as const, amount: 1480, count: 1, ads: [{ entity_id: "a8", name: "秋季新色預告・直式 9:16 短影音", thumbnail_url: null, spend: 1480 }] },
      { grade: "ungraded" as const, amount: 520, count: 0, ads: [] },
    ];
    const { rerender } = render(<GradeBand buckets={buckets} spent={22000} spentLabel="9 月已花" cap={{ value: 450, basis: "own" }} />);
    expect(screen.getByText("50%")).toBeTruthy();
    expect(screen.getByText("秋季新色預告…")).toBeTruthy();
    expect(screen.getByText("未分級 520 元")).toBeTruthy();
    rerender(<GradeBand buckets={buckets} spent={null} spentLabel="9 月已花" cap={null} />);
    expect(screen.getByText("不明")).toBeTruthy();
    expect(screen.getByText("9 月已花 未知")).toBeTruthy();
    // v10 legend: grade words are glossary terms; the shared cap's values show only when one cap is shared.
    const legend = document.querySelector('[data-part="band-legend"]') as HTMLElement;
    const plainText = () => { const c = legend.cloneNode(true) as HTMLElement; c.querySelectorAll('[role="tooltip"]').forEach((n) => n.remove()); return c.textContent; };
    expect(plainText()).toContain("每個活動對照自己的上限：划算＝每筆沒超過上限偏貴＝超過上限不到 2 成");
    expect(legend.querySelectorAll('[data-slot="term"]')).toHaveLength(6);
    rerender(<GradeBand buckets={buckets} spent={22000} spentLabel="9 月已花" cap={{ value: 450, basis: "own" }} />);
    expect(plainText()).toContain("划算＝每筆沒超過上限（450）偏貴＝超過上限不到 2 成（450–540）太貴＝超過 2 成以上（540 以上）");
  });

  it("MoneyMeter 上限線在 75%；超過 1.2 倍上限變紅；不知道數值只畫空軌", async () => {
    const { MoneyMeter } = await import("./MoneyMeter");
    const { container, rerender } = render(<MoneyMeter value={600} cap={{ value: 450, basis: "own" }} size="lg" />);
    expect(container.querySelector("u")?.className).toContain("left-3/4");
    const fill = container.querySelector("i") as HTMLElement;
    expect(fill.className).toContain("bg-danger");
    expect(fill.style.width).toBe("100%");
    expect(screen.getByText("上限 450")).toBeTruthy();
    rerender(<MoneyMeter value={600} cap={{ value: 450, basis: "own" }} size="lg" capLabel="各活動上限" />);
    expect(screen.getByText("各活動上限 450")).toBeTruthy();
    rerender(<MoneyMeter value={null} cap={{ value: 450, basis: "own" }} size="sm" />);
    expect(container.querySelector("i")).toBeNull();
  });

  it("PaceChart 沒月預算（未設或 0）什麼都不畫、說「還沒設月預算」，不會出現 NaN；已花未知不印已花", async () => {
    const { PaceChart } = await import("./PaceChart");
    const days = [{ day: 10, cumulative: 8000 }, { day: 23, cumulative: 22000 }];
    const { container, rerender } = render(<PaceChart month={9} dayOfMonth={23} daysInMonth={30} budget={60000} spent={22000} daily={days} projected={28696} budgetToDate={43210} />);
    expect(screen.getByRole("img", { name: "預算 60,000，已花 22,000，照預算今天應花到 43,210" })).toBeTruthy();
    expect(container.querySelector('[data-part="pace-line"]')).toBeTruthy();
    rerender(<PaceChart month={9} dayOfMonth={23} daysInMonth={30} budget={null} spent={null} daily={[]} projected={null} />);
    expect(container.querySelector("svg")).toBeNull();
    expect(screen.getByText("還沒設月預算")).toBeTruthy();
    expect(screen.queryByText(/已花/)).toBeNull();
    rerender(<PaceChart month={10} dayOfMonth={24} daysInMonth={31} budget={0} spent={30287.66} daily={days} projected={39121} />);
    expect(container.querySelector("svg")).toBeNull();
    expect(container.innerHTML).not.toContain("NaN");
    expect(screen.getByText("還沒設月預算・這個月已花 30,287.66")).toBeTruthy();
  });

  it("ScenarioBars 超出預算上限的列畫斜紋段與超出金額；算不出的列不能選", async () => {
    const { ScenarioBars } = await import("./ScenarioBars");
    const onSelect = vi.fn();
    const rows = [
      { key: "cons", label: "保守", total: 18000, overCap: null, caption: "約 37 筆購買" },
      { key: "cap", label: "照預算上限", total: 30000, overCap: null, recommended: true, saved: true },
      { key: "agg", label: "積極", total: 111600, overCap: 81600 },
      { key: "grow", label: "穩定成長", total: null, overCap: null },
    ];
    const { container } = render(<ScenarioBars rows={rows} budgetCap={30000} selected="cap" onSelect={onSelect} resultCap={450} />);
    expect(screen.getByText("超出 81,600")).toBeTruthy();
    expect(screen.getByText("約 37 筆購買")).toBeTruthy();
    expect(container.querySelectorAll('[data-part="over"]')).toHaveLength(1);
    expect(screen.getByRole("radio", { name: /照預算上限/ }).getAttribute("aria-checked")).toBe("true");
    expect(screen.queryByRole("radio", { name: /穩定成長/ })).toBeNull();
    expect(screen.getByText("要先設上限")).toBeTruthy();
    await userEvent.setup().click(screen.getByRole("radio", { name: /積極/ }));
    expect(onSelect).toHaveBeenCalledWith("agg");
  });

  it("ConfirmSheet 超出預算上限拆成上限內與超出；改回版列出每個值", async () => {
    const { ConfirmSheet, WarnButton } = await import("./ConfirmSheet");
    const { rerender } = render(
      <ConfirmSheet variant="over-cap" title="選「積極 111,600」會超出預算上限 81,600 元" split={{ within: 30000, over: 81600 }} actions={<WarnButton>超出預算上限也要用</WarnButton>} />,
    );
    expect(screen.getByRole("alertdialog", { name: /會超出預算上限/ })).toBeTruthy();
    expect(screen.getByText("預算上限內 30,000")).toBeTruthy();
    expect(screen.getByRole("button", { name: "超出預算上限也要用" }).dataset.variant).toBe("warn");
    rerender(<ConfirmSheet variant="revert" title="改回核准時的設定？" actions={<WarnButton>改回</WarnButton>}>每日預算：600 → 500</ConfirmSheet>);
    expect(screen.getByRole("alertdialog", { name: "改回核准時的設定？" }).dataset.variant).toBe("revert");
    expect(screen.getByText("每日預算：600 → 500")).toBeTruthy();
  });

  it("DiffRow 空值印未設定；數字走格式化", async () => {
    const { DiffRow } = await import("./DiffRow");
    render(<><DiffRow field="每日預算" item="廣告組・#2" before={500} after={1200.5} /><DiffRow field="廣告名稱" before={null} after="秋季新色・限量" /></>);
    expect(screen.getByText("1,200.5")).toBeTruthy();
    expect(screen.getByText("未設定")).toBeTruthy();
  });

  it("CapDots、ProgressSegments、AllocationBar 依數量畫；總額未知不印金額", async () => {
    const { CapDots } = await import("./CapDots");
    const { ProgressSegments } = await import("./ProgressSegments");
    const { AllocationBar } = await import("./ScenarioBars");
    const { container } = render(<CapDots keep={6} close={2} label="留 6 則、關 2 則" />);
    expect(container.querySelectorAll('[data-part="keep"]')).toHaveLength(6);
    expect(container.querySelectorAll('[data-part="close"]')).toHaveLength(2);
    render(<ProgressSegments label="3／11 已核對" segments={[{ key: "1", state: "ok" }, { key: "2", state: "changed" }, { key: "3", state: "todo" }]} />);
    expect(screen.getByRole("img", { name: "3／11 已核對" }).querySelectorAll("[data-state]")).toHaveLength(3);
    render(<AllocationBar parts={[{ key: "new", label: "新客", pct: 70 }, { key: "re", label: "再行銷", pct: 20 }, { key: "x", label: "探索", pct: 10 }]} />);
    expect(screen.getByText("新客 70%", { selector: "i" })).toBeTruthy();
    expect(screen.queryByText(/・/)).toBeNull();
  });

  it("AllocationBar legend prints each part's served amount as sent (F48 Contract M: never total × pct)", async () => {
    const { AllocationBar } = await import("./ScenarioBars");
    // 10,001 split by the API: the amounts are not round(10,001 × pct) and must print unchanged.
    render(<AllocationBar parts={[{ key: "new", label: "新客", pct: 70, amount: 7001 }, { key: "x", label: "探索", pct: 30, amount: 3000 }]} />);
    expect(screen.getByText(/新客 70%・7,001/)).toBeTruthy();
    expect(screen.getByText(/探索 30%・3,000/)).toBeTruthy();
  });

  it("AllocationBar legend={false}：細條、段內無字、無圖例；allocationFills 與段色一致、0% 不上色", async () => {
    const { AllocationBar, allocationFills } = await import("./ScenarioBars");
    const parts = [{ key: "new", label: "新客", pct: 70 }, { key: "re", label: "再行銷", pct: 0 }, { key: "x", label: "探索", pct: 30 }];
    const { container } = render(<AllocationBar parts={parts} legend={false} />);
    const bar = container.querySelector("[data-slot=allocation-bar]") as HTMLElement;
    expect(bar.textContent).toBe("");
    const fills = allocationFills(parts);
    expect(fills).toEqual({ new: "bg-chart-revenue", x: "bg-chart-spend" });
    expect(bar.querySelector("[data-key=x]")?.className).toContain(fills.x);
    expect(bar.querySelector("[data-key=re]")).toBeNull();
  });
});

describe("v10 kit（F29-I09）", () => {
  const PROTO = "../../../../../docs/design/ads/prototype-v10-ads-center.html";
  /** Text as shown: a term's hidden tooltip sentence is not part of the line. */
  const shown = (el: Element) => { const copy = el.cloneNode(true) as Element; copy.querySelectorAll("[role='tooltip']").forEach((t) => t.remove()); return copy.textContent; };

  it("glossary follows served cost/evidence wording; retained terms match the prototype and unloaded terms stay empty", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const { define } = await import("./glossary");
    const html = readFileSync(join(__dirname, PROTO), "utf8");
    const start = html.indexOf("const GLOSS = {");
    const block = html.slice(start, html.indexOf("};", start));
    const gloss = Object.fromEntries([...block.matchAll(/^\s+(\w+): "([^"]*)",?\r?$/gm)].map((m) => [m[1], m[2]]));
    expect(Object.keys(gloss)).toHaveLength(9);
    expect(define("break_even", 520)).toContain("這裡是 520");
    expect(define("break_even", 520)).toContain("不能只用平台歸因證明盈虧");
    expect(define("cap")).toBe(RULES_FIXTURE.glossary.cap);
    expect(define("on_target")).toBe(RULES_FIXTURE.glossary.on_target);
    expect(define("watch")).toBe(RULES_FIXTURE.glossary.watch);
    for (const term of ["over", "wasted", "money", "notebook"] as const) {
      expect(define(term)).toBe(RULES_FIXTURE.glossary[term]);
    }
    expect(define("over")).toContain("不能單憑此判定盈虧");
    expect(define("break_even", null)).not.toContain("這裡是");
    expect(define("break_even", null)).toBe(RULES_FIXTURE.glossary.break_even);
    // `thin` is the served sentence (F48 Contract R: sample size is shown, never a gate), built from the rules.
    expect(define("thin")).toBe(RULES_FIXTURE.glossary.thin);
    expect(define("thin")).toContain(`上限 ${RULES_FIXTURE.grade.unsold_spend_multiple} 倍`);
    expect(define("thin")).toContain(`少於 ${RULES_FIXTURE.grade.sample_few} 筆標「${RULES_FIXTURE.labels.flags.few}」`);
    // A changed served sentence is printed as served — the frontend keeps no copy.
    const served = { ...RULES_FIXTURE, glossary: { ...RULES_FIXTURE.glossary, watch: "後端改過的句子" } };
    expect(define("watch", null, served)).toBe("後端改過的句子");
    // Not loaded: no sentence at all (never a literal fallback).
    seedAdsRules(null);
    try {
      expect(define("cap")).toBe("");
      expect(define("break_even", 520)).toBe("");
    } finally {
      seedAdsRules(RULES_FIXTURE);
    }
  });

  it("Term：虛線字可 tab 到，說明掛在 tooltip；plain 只印字", async () => {
    const { Term, GradeTermChip } = await import("./Term");
    const { container } = render(<p>每筆沒超過<Term k="cap">上限</Term>・<Term k="money" plain>有賺</Term></p>);
    const term = container.querySelector("[data-slot='term']") as HTMLElement;
    expect(term.tabIndex).toBe(0);
    expect(term.className).toContain("border-dotted");
    const tip = screen.getByRole("tooltip", { hidden: true });
    expect(tip.textContent).toBe("你願意為一筆訂單付的廣告費，每個活動自己設");
    expect(term.getAttribute("aria-describedby")).toBe(tip.id);
    expect(container.querySelectorAll("[data-slot='term']")).toHaveLength(1);
    expect(container.textContent).toContain("有賺");

    const chips = render(<><GradeTermChip grade="insufficient" label="剛開始、數字還不夠" /><GradeTermChip grade="wasted" plain /><GradeTermChip grade={null} /></>).container;
    expect(chips.querySelectorAll("[data-slot='term']")).toHaveLength(1);
    expect(chips.textContent).toContain("沒賣出");
    expect(chips.textContent).toContain("未判斷");
  });

  it("moneyTag：±served band（今天 2%）算剛好打平，差 2.1% 才有賺／在虧；任一未知或規則沒載入就不出", async () => {
    const { moneyTag, MoneyTag } = await import("./MoneyTag");
    const band = RULES_FIXTURE.grade.break_even_band;
    expect(moneyTag(520 * (1 - band), 520, band)?.label).toBe("剛好打平");
    expect(moneyTag(520 * (1 + band), 520, band)?.label).toBe("剛好打平");
    expect(moneyTag(520 * (1 - band - 0.001), 520, band)?.label).toBe("有賺");
    expect(moneyTag(520 * (1 + band + 0.001), 520, band)?.label).toBe("在虧");
    expect(moneyTag(null, 520, band)).toBeNull();
    expect(moneyTag(353, null, band)).toBeNull();
    expect(moneyTag(353, 520, null)).toBeNull();
    expect(moneyTag(0, 520, band)?.label).toBe("有賺");
    // The band is the served one: a wider band makes the same cost 剛好打平.
    expect(moneyTag(520 * 0.95, 520, 0.06)?.label).toBe("剛好打平");

    const { container } = render(<><MoneyTag cost={353} breakEven={520} /><MoneyTag cost={614} breakEven={null} /></>);
    const tags = container.querySelectorAll("[data-slot='money-tag']");
    expect(tags).toHaveLength(1);
    expect(shown(tags[0])).toBe("・有賺（打平 520）");
    expect(tags[0].getAttribute("data-variant")).toBe("gain");
  });

  it("display overrides preserve grade geometry and default purchase vocabulary", async () => {
    const { GradeBar } = await import("./GradeBar");
    const { GradeRules } = await import("./GradeRules");
    seedAdsRules(RULES_FIXTURE);
    const buckets = [{grade: "wasted" as const, amount: 200, count: 1, currency: "TWD"}];
    const {container, rerender} = render(<><GradeBar buckets={buckets} withMoney rules={false}
      gradeLabels={{wasted: "尚無成果"}} /><GradeRules money={false} wastedText="尚無成果＝花了錢仍沒有成果" /></>);
    expect(container.querySelector<HTMLElement>('i[data-grade="wasted"]')?.style.width).toBe("100%");
    expect(container.textContent).toContain("尚無成果 1 則・200 TWD");
    expect(container.textContent).toContain("尚無成果＝花了錢仍沒有成果");
    expect(container.textContent).not.toMatch(/沒賣出|都沒賣|有賺|在虧/);
    rerender(<><GradeBar buckets={buckets} withMoney rules={false} /><GradeRules money={false} /></>);
    expect(container.textContent).toContain("沒賣出 1 則・200 TWD");
    expect(container.textContent).toContain("花了錢一筆都沒賣");
    expect(container.querySelector<HTMLElement>('i[data-grade="wasted"]')?.style.width).toBe("100%");
  });

  it("GradeRules 四個等級字都是名詞解釋；GradeBar 依金額分段，金額未知印未知不印 0", async () => {
    const { GradeRules } = await import("./GradeRules");
    const { GradeBar } = await import("./GradeBar");
    const rules = render(<GradeRules breakEven={520} />).container;
    expect(shown(rules)).toContain("划算＝每筆沒超過上限");
    expect(shown(rules)).toContain("沒賣出＝花了錢一筆都沒賣");
    expect(shown(rules)).toContain("有賺／在虧：跟打平線比；分級：跟你的上限比");
    expect(rules.querySelectorAll("[data-slot='term']")).toHaveLength(8);
    const moneyRule = rules.querySelector("[data-slot='money-rule']") as HTMLElement;
    expect(moneyRule.querySelectorAll("[role='tooltip']")[1].textContent).toContain("這裡是 520");

    const buckets = [
      { grade: "on_target" as const, amount: 14240, count: 2, currency: "TWD" },
      { grade: "watch" as const, amount: 6100, count: 1, currency: "TWD" },
      { grade: "over" as const, amount: 8200, count: 2, currency: "TWD" },
      { grade: "wasted" as const, amount: 1600, count: 1, currency: "TWD" },
      { grade: "insufficient" as const, amount: 1600, count: 2, currency: "TWD" },
    ];
    const { container, rerender } = render(<GradeBar withMoney rules={false} buckets={buckets} />);
    const seg = container.querySelector("i[data-grade='on_target']") as HTMLElement;
    expect(seg.style.width).toBe(`${(14240 / 31740) * 100}%`);
    expect(container.textContent).toContain("划算 2 則・14,240 TWD");
    expect(container.textContent).toContain("剛開始、數字還不夠 2 則・1,600 TWD");
    rerender(<GradeBar withMoney rules={false} buckets={[...buckets, { grade: "ungraded", amount: null, count: 1, currency: "TWD" }]} />);
    expect(container.querySelector("i[data-grade]")).toBeNull();
    expect(container.textContent).toContain("未判斷 1 則・金額未知");
    expect(container.textContent).not.toContain("・0 TWD");
    expect(container.querySelector("[data-slot='grade-rules']")).toBeNull();
  });

  it.each([
    { amount: null, count: 1, currency: "TWD" },
    { amount: null, count: 0, currency: "TWD" },
    { amount: 100, count: 1, currency: null },
    { amount: 100, count: 1, currency: "USD" },
    { amount: 0, count: 0, currency: null },
    { amount: 0, count: 0, currency: "USD" },
  ])("GradeBar refuses incomplete or mixed buckets, including zero-count unknowns ($amount/$count/$currency)", async (other) => {
    const { GradeBar } = await import("./GradeBar");
    const { container } = render(<GradeBar withMoney rules={false} buckets={[
      { grade: "on_target", amount: 100, count: 1, currency: "TWD" }, { grade: "watch", ...other },
    ]} />);
    expect(container.querySelector("i[data-grade]")).toBeNull();
    expect(container.textContent).toContain("不比較花費占比");
    expect(container.textContent).toContain("划算 1 則・100 TWD");
    if (other.amount === null) {
      expect(container.textContent).toContain("・金額未知");
      expect(container.textContent).not.toContain("・0 TWD");
    } else expect(container.textContent).toContain(`・${other.amount} ${other.currency ?? "幣別未知"}`);
  });

  it("GradeBar keeps counted zero separate from absent buckets and refuses mixed amounts within one grade", async () => {
    const { GradeBar } = await import("./GradeBar");
    const { container, rerender } = render(<GradeBar withMoney rules={false} buckets={[]} />);
    expect(container.querySelector("[data-grade]")).toBeNull();
    expect(container.textContent).not.toContain("・0");
    rerender(<GradeBar withMoney rules={false} buckets={[{ grade: "on_target", amount: 0, count: 0, currency: "TWD" }]} />);
    expect(container.textContent).toContain("划算 0 則・0 TWD");
    expect(container.textContent).not.toContain("不比較花費占比");
    expect(container.querySelector("i[data-grade]")).toBeNull();
    rerender(<GradeBar withMoney rules={false} buckets={[
      { grade: "on_target", amount: 100, count: 1, currency: "TWD" },
      { grade: "on_target", amount: 100, count: 1, currency: "USD" },
    ]} />);
    expect(container.querySelector("i[data-grade]")).toBeNull();
    expect(container.textContent).toContain("划算 2 則・金額未知");
    expect(container.textContent).not.toContain("・200");
  });

  it("GradeBar treats raw missing amounts as unknown rather than a zero-width comparable bucket", async () => {
    const { GradeBar } = await import("./GradeBar");
    const buckets = JSON.parse('[{"grade":"on_target","amount":100,"count":1,"currency":"TWD"},{"grade":"watch","count":0,"currency":"TWD"}]');
    const { container, rerender } = render(<GradeBar withMoney rules={false} buckets={buckets} />);
    expect(container.querySelector("i[data-grade]")).toBeNull();
    expect(container.textContent).toContain("偏貴 0 則・金額未知");
    expect(container.textContent).toContain("花費金額未知，不比較花費占比。");
    expect(container.textContent).not.toMatch(/NaN|undefined|偏貴 0 則・0/);
    buckets[1].grade = "on_target";
    rerender(<GradeBar withMoney rules={false} buckets={buckets} />);
    expect(container.querySelector("i[data-grade]")).toBeNull();
    expect(container.textContent).toContain("划算 1 則・金額未知");
    // An explicitly known amount still prints even when the unit is absent.
    rerender(<GradeBar withMoney rules={false} buckets={[{ grade: "on_target", amount: 100, count: 1, currency: "" }]} />);
    expect(container.textContent).toContain("划算 1 則・100 幣別未知");
    expect(container.querySelector("i[data-grade]")).toBeNull();
  });

  it("WaitLine：排第 2 件、正在處理的第 1 件、位置讀不到；不印第 0 件", async () => {
    const { WaitLine } = await import("./WaitLine");
    const queued = render(<WaitLine title="AI 正在從文案整理主打" status="queued" position={2} total={5} waitedSeconds={20} note="可以先離開，整理好會出現在首頁待辦" />).container;
    expect(queued.textContent).toContain("AI 排隊：第 2 件／共 5 件，前面還有 1 件・已等約 20 秒");
    expect(queued.querySelectorAll("[data-slot='wait-line'] > div:last-child i")).toHaveLength(5);

    const first = render(<WaitLine title="整理中" status="running" position={1} total={3} waitedSeconds={65} />).container;
    expect(first.textContent).toContain("AI 正在處理：共 3 件・已跑約 1 分");
    expect(first.textContent).not.toContain("前面還有");

    const nextUp = render(<WaitLine title="整理中" status="queued" position={1} total={3} waitedSeconds={0} />).container;
    expect(nextUp.textContent).toContain("第 1 件／共 3 件，前面還有 0 件・剛排進來");

    const unknown = render(<WaitLine title="整理中" status={null} position={null} total={null} waitedSeconds={null} />).container;
    expect(unknown.textContent).toContain("排第幾件讀不到");
    expect(unknown.textContent).not.toMatch(/第 0 件|共 0 件/);
    expect(unknown.querySelectorAll("i")).toHaveLength(0);
  });

  it("ReadFailed 是 alert、不是空狀態；按重試重讀", async () => {
    const { ReadFailed } = await import("./ReadFailed");
    const retry = vi.fn();
    render(<ReadFailed what="AI 整理的主打讀不到；這期的成績都還在" onRetry={retry} />);
    const box = screen.getByRole("alert");
    expect(box.textContent).toContain("讀取失敗");
    expect(box.textContent).toContain("這期的成績都還在");
    fireEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  describe("AbPair", () => {
    const side = (over: Record<string, unknown>) => ({ ad_id: "ad_a", entity_id: "e_a", name: "開箱 15 秒・單手開蓋", value_label: "開箱畫面", thumbnail_url: null, spend: 560, results: 10, cost_per_result: 56, ...over }) as AbSideFixture;
    type AbSideFixture = { ad_id: string; entity_id: string | null; name: string; value_label: string; thumbnail_url: string | null; spend: number | null; results: number | null; cost_per_result: number | null };
    const base = {
      pair_id: "ad_a:ad_b", group_id: "grp_a", group_name: "A・廣泛受眾", dimension: "hook", dimension_label: "開場",
      rules: { min_days: 7, min_conversions_each: 10, relative_difference: 0.1 }, decision: null,
    };

    it("收集中：天數與兩邊購買的進度、還差什麼；購買讀不到不當 0", async () => {
      const { AbPair } = await import("./AbPair");
      const pair = {
        ...base, a: side({ value_label: "辦公桌", results: 6 }), b: side({ ad_id: "ad_b", value_label: "通勤路上", results: null }),
        window: { start: "2026-09-20", end: "2026-09-23" }, days: 4, state: "collecting" as const,
        missing: { days: 3, a_results: 4, b_results: null }, winner: null, difference_pct: null, reason: null,
      };
      const { container } = render(<AbPair pair={pair} />);
      expect(container.querySelector("[data-slot='ab-pair']")?.getAttribute("data-variant")).toBe("collecting");
      expect(container.textContent).toContain("09/20 開始・第 4 天");
      expect(container.textContent).toContain("4／7 天");
      expect(container.textContent).toContain("6／10 筆");
      expect(container.textContent).toContain("還差 3 天／A 還差 4 筆購買／B 的購買讀不到");
      expect(container.textContent).not.toContain("0／10 筆");
    });

    it("可以判斷：贏家留下、輸家建議關掉；便宜幾 % 用 API 的 difference_pct", async () => {
      const { AbPair } = await import("./AbPair");
      const pair = {
        ...base, a: side({}), b: side({ ad_id: "ad_b", name: "晨光隨行杯・日常出發", value_label: "出門情境", spend: 720, results: 16, cost_per_result: 45 }),
        window: { start: "2026-09-16", end: "2026-09-22" }, days: 7, state: "judged" as const,
        missing: { days: 0, a_results: 0, b_results: 0 }, winner: "b" as const, difference_pct: 19.6, reason: null,
      };
      const { container } = render(<AbPair pair={pair} breakEven={520} action={<button type="button">關掉輸家（A）</button>} />);
      expect(container.textContent).toContain("近 7 天 09/16–09/22・其他都一樣");
      expect(container.textContent).toContain("B 比較划算");
      expect(container.textContent).toContain("B 每筆便宜 19.6%（11 元）");
      expect(container.textContent).toContain("比較貴・建議關掉");
      expect(container.textContent).toContain("比較划算・留下");
      expect(container.querySelectorAll("[data-slot='money-tag']")).toHaveLength(2);
      expect(screen.getByRole("button", { name: "關掉輸家（A）" })).toBeTruthy();
    });

    it("讀不到：只印原因，不畫數字", async () => {
      const { AbPair } = await import("./AbPair");
      const pair = {
        ...base, a: side({ spend: null, results: null, cost_per_result: null }), b: side({ ad_id: "ad_b", spend: null, results: null, cost_per_result: null }),
        window: { start: "2026-09-16", end: "2026-09-22" }, days: 7, state: "unreadable" as const,
        missing: { days: 0, a_results: null, b_results: null }, winner: null, difference_pct: null, reason: "缺 2026-09-17 的資料；缺資料不當成零。",
      };
      const { container } = render(<AbPair pair={pair} />);
      expect(container.textContent).toContain("缺 2026-09-17 的資料");
      expect(container.textContent).not.toMatch(/\d+ 元/);
    });
  });

  it("PickRow：整列是勾選框的 label，取消勾選變暗", async () => {
    const { PickRow } = await import("./PickRow");
    const change = vi.fn();
    const { container } = render(<PickRow checked={false} onChange={change} name="提問式貼文・早晨第一口是什麼？" thumbnailUrl={null} grade="over" aside="每筆 617 元" />);
    const box = screen.getByRole("checkbox", { name: "關掉「提問式貼文・早晨第一口是什麼？」" });
    expect(container.querySelector("[data-slot='pick-row']")?.getAttribute("data-variant")).toBe("off");
    expect(container.querySelector("[data-slot='term']")).toBeNull();
    fireEvent.click(screen.getByText("每筆 617 元"));
    expect(change).toHaveBeenCalledWith(true);
    expect((box as HTMLInputElement).checked).toBe(false);
  });

  it("RowMenu：選一項就收起並執行", async () => {
    const { RowMenu } = await import("./RowMenu");
    const replace = vi.fn();
    const { container } = render(<RowMenu label="更多：秋季新色預告" items={[{ label: "換掉這一則", onSelect: replace }, { label: "看紀錄", onSelect: vi.fn() }]} />);
    const details = container.querySelector("details") as HTMLDetailsElement;
    details.open = true;
    fireEvent.click(screen.getByRole("button", { name: "換掉這一則" }));
    expect(replace).toHaveBeenCalledOnce();
    expect(details.open).toBe(false);
  });

  it("投放設定：建議／你改的標籤；讀回列的不一樣、讀不到與計數", async () => {
    const { SettingField, ReadbackRow, ReadbackSummary } = await import("./SettingsPieces");
    const fields = render(<>
      <SettingField label="優化事件" htmlFor="opt" tag="recommended" note="Meta 要幫你找哪種人：會買的人"><select id="opt"><option>購買</option></select></SettingField>
      <SettingField label="出價方式" tag="edited"><span>出價上限</span></SettingField>
    </>).container;
    expect(screen.getByLabelText(/優化事件/)).toBeTruthy();
    expect(fields.textContent).toContain("建議");
    expect(fields.textContent).toContain("你改的");

    const rows = [
      { key: "age", label: "年齡", expected_label: "25–54 歲", observed_label: "18–65+ 歲", state: "differ" as const, reason: null },
      { key: "pixel", label: "像素", expected_label: "晨光官網像素（…4821）", observed_label: null, state: "unreadable" as const, reason: "像素的讀取權限沒開，系統看不到" },
      { key: "bid", label: "出價方式", expected_label: "最低成本", observed_label: "最低成本", state: "match" as const, reason: null },
      { key: "gender", label: "性別", expected_label: "不限", observed_label: null, state: "self_confirmed" as const, reason: null },
    ];
    const { container } = render(<>
      <ReadbackSummary fields={rows} />
      {rows.map((f) => <ReadbackRow key={f.key} field={f} platform="Meta" action={f.state === "unreadable" ? <button type="button">我看過了，一樣</button> : undefined} />)}
    </>);
    expect(container.textContent).toContain("對上了 2");
    expect(container.textContent).toContain("不一樣 1");
    expect(container.textContent).toContain("讀不到 1");
    expect(container.textContent).toContain("不一樣（Meta 上是 18–65+ 歲，這裡是 25–54 歲）");
    expect(container.textContent).toContain("像素的讀取權限沒開");
    expect(container.textContent).toContain("你確認一樣");
    expect(container.querySelectorAll("[data-tone='unread']")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "我看過了，一樣" })).toBeTruthy();
  });

  it("ActionBar exit：back 跟 exit 同一處時只留 exit；不同處兩個都在", async () => {
    const { MemoryRouter } = await import("react-router-dom");
    const { ActionBar } = await import("./FlowPieces");
    const exit = { label: "先不要，回投放中心", to: "/brands/b/ads" };
    const same = render(<MemoryRouter><ActionBar back={{ label: "投放中心", to: "/brands/b/ads" }} exit={exit} /></MemoryRouter>).container;
    expect([...same.querySelectorAll("a")].map((a) => a.textContent)).toEqual(["✕ 先不要，回投放中心"]);
    const other = render(<MemoryRouter><ActionBar back={{ label: "這期成績", to: "/brands/b/ads/settle/2026-08/result" }} exit={{ label: "晚點再結算", to: "/brands/b/ads" }} /></MemoryRouter>).container;
    expect([...other.querySelectorAll("a")].map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["← 這期成績", "/brands/b/ads/settle/2026-08/result"], ["✕ 晚點再結算", "/brands/b/ads"],
    ]);
    const node = render(<MemoryRouter><ActionBar back={<span>自訂返回</span>} /></MemoryRouter>).container;
    expect(node.textContent).toContain("自訂返回");
  });

  it("LearnLine、FlowTo、OriginTag", async () => {
    const { LearnLine, FlowTo, OriginTag } = await import("./LoopPieces");
    const { container } = render(<>
      <LearnLine tone="ok" title="「通勤帶著走」對這群受眾有效" meta={<>日常商品推廣・轉換<OriginTag>從 Meta 帶進來</OriginTag></>} />
      <LearnLine tone="no" title="「新色搶先看」對這群受眾無效" />
      <FlowTo from={{ label: "品牌筆記本", value: "多了 5 條", note: "原本 14 條" }} to={{ label: "下一個新活動", value: "策略會先讀這些" }} />
    </>);
    const lines = container.querySelectorAll("[data-slot='learn-line']");
    expect(lines[0].textContent).toContain("✓");
    expect(lines[1].textContent).toContain("✕");
    expect(container.querySelector("[data-slot='origin-tag']")?.textContent).toBe("從 Meta 帶進來");
    expect(container.querySelector("[data-slot='flow-to']")?.textContent).toContain("多了 5 條原本 14 條→下一個新活動");
  });
});

describe("blocked slot（F44-I05，原型 f44-blocked-slot）", () => {
  it("SlotTile blocked：原因只標出引號裡的字，另有 N 個原因、出口與補充說明都在原因區，縮圖變暗", async () => {
    const { SlotGrid, SlotTile } = await import("./SlotGrid");
    const { container } = render(
      <SlotGrid label="新客">
        <SlotTile variant="blocked" name="備考生・讀到深夜" thumbnailUrl="https://scontent.example/c.jpg"
          copy={{ label: "待確認", text: "讀到凌晨一點　三盒組優惠價 NT$999 陪你撐完最後一章" }} offer={<span>無優惠</span>} status={<span>卡住</span>}
          reason={{ text: "這則規劃的是「無優惠」，文案卻寫了「優惠」。", terms: ["優惠"], more: 0 }}
          actions={<button type="button">換一版文案</button>} note={<p>還是卡住：原因沒有變</p>} />
        <SlotTile variant="blocked" name="訓練前・一顆就好" thumbnailUrl={null}
          reason={{ text: "文案寫了「優惠、加贈」，品牌資料裡沒有登記這個優惠或背書。", terms: ["加贈", "優惠"], more: 2 }} />
        <SlotTile variant="blocked" name="會議前・午休五分鐘" thumbnailUrl={null} reason={{ text: "這個檔案處理失敗：圖片格式讀不出來。", terms: [] }} />
      </SlotGrid>,
    );
    const tiles = [...container.querySelectorAll<HTMLElement>("[data-slot=slot-tile]")];
    expect(tiles.map((t) => t.dataset.variant)).toEqual(["blocked", "blocked", "blocked"]);
    const reason = (t: HTMLElement) => t.querySelector("[data-slot=slot-reason]") as HTMLElement;
    const marks = (t: HTMLElement) => [...reason(t).querySelectorAll("mark")].map((m) => m.textContent);
    // 「無優惠」 carries the same characters but is the plan's label, not an offending word.
    expect(reason(tiles[0]).querySelector("p")?.textContent).toBe("這則規劃的是「無優惠」，文案卻寫了「優惠」。");
    expect(marks(tiles[0])).toEqual(["優惠"]);
    expect(reason(tiles[0]).textContent).not.toContain("另有");
    expect(reason(tiles[0]).querySelector("button")?.textContent).toBe("換一版文案");
    expect(reason(tiles[0]).textContent).toContain("還是卡住：原因沒有變");
    expect(tiles[0].querySelector("img")?.className).toContain("grayscale");
    expect(tiles[0].querySelector("[data-slot=slot-head]")?.textContent).toBe("備考生・讀到深夜無優惠");
    // No tick on a blocked slot's copy half; a ready tile keeps it.
    expect(tiles[0].querySelector("[data-slot=slot-copy] span")?.textContent).toBe("文案 · 待確認");
    const readyTile = render(<SlotTile variant="ready" name="通勤路上一顆" thumbnailUrl={null} copy={{ label: "已確認", text: "通勤路上，一顆就好" }} />).container;
    expect(readyTile.querySelector("[data-slot=slot-copy] span")?.textContent).toBe("✓文案 · 已確認");
    // Both quoted items are marked; 「這個優惠或背書」 later in the sentence is not.
    expect(marks(tiles[1])).toEqual(["優惠", "加贈"]);
    expect(reason(tiles[1]).textContent).toContain("另有 2 個原因");
    expect(marks(tiles[2])).toEqual([]);
    expect(reason(tiles[2]).textContent).toBe("這個檔案處理失敗：圖片格式讀不出來。");
  });

  it("SlotTile 的優惠晶片：有給才有 slot-head；沒給時名稱列跟原本一樣", async () => {
    const { SlotTile } = await import("./SlotGrid");
    const plain = render(<SlotTile variant="ready" name="晨光隨行杯・日常出發" thumbnailUrl={null} />).container;
    expect(plain.querySelector("[data-slot=slot-head]")).toBeNull();
    expect(plain.querySelector("[data-slot=slot-tile]")?.textContent).toBe("晨光隨行杯・日常出發");
    const withOffer = render(<SlotTile variant="ready" name="通勤族・三盒組優惠價" thumbnailUrl={null} offer={<span>組合優惠</span>} />).container;
    expect(withOffer.querySelector("[data-slot=slot-head]")?.textContent).toBe("通勤族・三盒組優惠價組合優惠");
    expect(withOffer.querySelector("img")).toBeNull();
  });

  it("ProgressSegments：卡住是 danger 色、處理中是淡紫", async () => {
    const { ProgressSegments } = await import("./ProgressSegments");
    render(<ProgressSegments label="1／3 格已備妥，1 格卡住" segments={[{ key: "1", state: "ok" }, { key: "2", state: "blocked" }, { key: "3", state: "running" }]} />);
    const bar = screen.getByRole("img", { name: "1／3 格已備妥，1 格卡住" });
    expect(bar.querySelector("[data-state=blocked]")?.className).toContain("bg-danger");
    expect(bar.querySelector("[data-state=running]")?.className).toContain("bg-chart-soft");
    expect(bar.querySelector("[data-state=ok]")?.className).toContain("bg-success");
  });
});

describe("campaign words（F47-I08，drill-10 §4.3；F49 Contract L）", () => {
  it("一個活動一個字＝後端給的 lifecycle.label（不看 status、不自己換字）；沒有 lifecycle 印「—」", async () => {
    const { campaignWord } = await import("./campaignWords");
    const lc = (state: "draft" | "live" | "ended" | "closed", label: string) => ({ lifecycle: { state, label, can_close: false } });
    expect(campaignWord(lc("draft", "草稿"))).toBe("草稿");
    expect(campaignWord(lc("live", "投放中"))).toBe("投放中");
    expect(campaignWord(lc("ended", "已結束・待結案"))).toBe("已結束・待結案");
    expect(campaignWord(lc("ended", "已結束"))).toBe("已結束");
    expect(campaignWord(lc("closed", "已結案"))).toBe("已結案");
    // The old second argument still compiles and no longer overrides the served word.
    expect(campaignWord(lc("live", "投放中"), { onPlatform: false })).toBe("投放中");
    expect(campaignWord({})).toBe("—");
    expect(campaignWord({ lifecycle: null })).toBe("—");
    // Without a served lifecycle, a caller's own 「not on a platform」 answer still reads 草稿.
    expect(campaignWord({}, { onPlatform: false })).toBe("草稿");
  });

  it("已結案不說在投：平台上還在投的 N 則（served running count）才寫出來", async () => {
    const { closedWord } = await import("./campaignWords");
    expect(closedWord(6)).toBe("已結案・平台上還開著 6 則");
    expect(closedWord(0)).toBe("已結案");
  });
});

describe("served rules（F48-I08 Contract R-API）", () => {
  const G = RULES_FIXTURE.grade;
  const L = RULES_FIXTURE.labels.grade;
  /** The served rules with one grade threshold and one word changed — what a backend rule change looks like. */
  const CHANGED = {
    ...RULES_FIXTURE,
    grade: { ...G, watch_band: 1.5, unsold_spend_multiple: 4 },
    labels: { ...RULES_FIXTURE.labels, grade: { ...L, watch: "有點貴" } },
  };
  const visible = (el: Element) => { const c = el.cloneNode(true) as Element; c.querySelectorAll("[role='tooltip']").forEach((t) => t.remove()); return c.textContent ?? ""; };
  const withRules = async (rules: typeof RULES_FIXTURE | null, run: () => void | Promise<void>) => {
    seedAdsRules(rules);
    try { await run(); } finally { seedAdsRules(RULES_FIXTURE); }
  };
  const band = (["on_target", "wasted", "ungraded"] as const).map((grade) => ({ grade, amount: 1000, count: 1, ads: [] }));

  it("GradeBand legend: the words and numbers are the fixture's (偏貴 band and its 成)", async () => {
    const { GradeBand } = await import("./GradeBand");
    const { container } = render(<GradeBand buckets={band} spent={3000} spentLabel="9 月已花" cap={{ value: 450, basis: "own" }} />);
    const legend = visible(container.querySelector('[data-part="band-legend"]')!);
    const tenths = String(Math.round((G.watch_band - 1) * 10));
    expect(legend).toContain(`${L.watch}＝超過上限不到 ${tenths} 成（450–${450 * G.watch_band}）`);
    expect(legend).toContain(`${L.over}＝超過 ${tenths} 成以上（${450 * G.watch_band} 以上）`);
    expect(legend).toContain(`${L.too_new} 不明 元`);
  });

  it("a changed rule moves every piece with it: legend, ruler zones, meter colour, chip word, glossary", async () => {
    await withRules(CHANGED, async () => {
      const { GradeBand } = await import("./GradeBand");
      const { TargetRuler, rulerScale } = await import("./TargetRuler");
      const { MoneyMeter } = await import("./MoneyMeter");
      const { GradeTermChip } = await import("./Term");
      const bandView = render(<GradeBand buckets={band} spent={3000} spentLabel="9 月已花" cap={{ value: 450, basis: "own" }} />).container;
      expect(visible(bandView.querySelector('[data-part="band-legend"]')!)).toContain("有點貴＝超過上限不到 5 成（450–675）");

      const ads = [
        { id: "w", name: "沒賣出那則", grade: "wasted" as const, costPerResult: null, spend: 2000 },
        { id: "t", name: "剛開始那則", grade: "insufficient" as const, gradeLabel: L.too_new, costPerResult: null, spend: 900 },
        { id: "o", name: "太貴那則", grade: "over" as const, costPerResult: 700, spend: 1400 },
      ].map((ad) => ({ ...ad, currency: "TWD", comparisonReason: null }));
      const ruler = render(<TargetRuler ads={ads} cap={{ value: 450, basis: "own", currency: "TWD" }} size="full" />).container;
      const { pos } = rulerScale(450, [700]);
      const watchZone = ruler.querySelector("i.bg-grade-watch") as HTMLElement;
      expect(watchZone.style.width).toBe(`${pos(675) - pos(450)}%`);
      expect(ruler.querySelector("[data-zone='有點貴']")).toBeTruthy();
      expect(screen.getByRole("button", { name: /^沒賣出那則｜/ }).textContent).toContain("花到 1,800 TWD 還沒賣");
      expect(ruler.textContent).toContain("已花 900 TWD／1,800 TWD");

      const meter = render(<MoneyMeter value={600} cap={{ value: 450, basis: "own" }} size="sm" />).container;
      expect(meter.querySelector("i")?.className).toContain("bg-warning/80");

      const chip = render(<GradeTermChip grade="watch" />).container;
      expect(visible(chip)).toBe("有點貴");
    });
  });

  it("not loaded yet: words print without numbers, nothing falls back to a literal", async () => {
    await withRules(null, async () => {
      const { GradeBand } = await import("./GradeBand");
      const { GradeRules } = await import("./GradeRules");
      const { TargetRuler } = await import("./TargetRuler");
      const { MoneyTag } = await import("./MoneyTag");
      const { Term } = await import("./Term");
      const bandView = render(<GradeBand buckets={band} spent={3000} spentLabel="9 月已花" cap={{ value: 450, basis: "own" }} />).container;
      const legend = visible(bandView.querySelector('[data-part="band-legend"]')!);
      expect(legend).not.toMatch(/成|偏貴|划算/);
      expect(legend).toContain("＝每筆沒超過上限（450）");

      const rules = render(<GradeRules breakEven={520} />).container;
      expect(rules.querySelectorAll("i")).toHaveLength(0);
      expect(visible(rules)).toBe("有賺／在虧：跟打平線比；分級：跟你的上限比");

      const ruler = render(<TargetRuler ads={[{ id: "w", name: "沒賣出那則", grade: "wasted", costPerResult: null, spend: 2000, currency: "TWD", comparisonReason: null }]} cap={{ value: 450, basis: "own", currency: "TWD" }} size="full" />).container;
      expect(ruler.querySelector("[data-zone]")).toBeNull();
      expect(screen.getByRole("button", { name: /^沒賣出那則｜/ }).textContent).not.toContain("花到");

      expect(render(<MoneyTag cost={353} breakEven={520} />).container.querySelector("[data-slot='money-tag']")).toBeNull();
      const term = render(<Term k="cap">上限</Term>).container;
      expect(term.querySelector("[role='tooltip']")).toBeNull();
      expect(term.textContent).toBe("上限");
    });
  });
});


it("unknown grade counts and amounts stay unknown", async () => {
  const { GradeBand } = await import("./GradeBand");
  render(<GradeBand spent={null} spentLabel="本月" cap={null} buckets={[{grade: "on_target", amount: null, count: null, ads: []}]} />);
  expect(screen.getByText("不明 則")).toBeTruthy();
  expect(screen.getAllByText("不明 元").length).toBeGreaterThan(0);
  expect(screen.getByText("不明")).toBeTruthy();
});
