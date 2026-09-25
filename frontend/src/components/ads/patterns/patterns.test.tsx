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
    render(<OptionCard icon="✚" title="換一張圖" note="x" disabled />);
    expect((screen.getByRole("button", { name: /換一張圖/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("接上後開放")).toBeTruthy();
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
  ];

  it("TargetRuler 依每筆成本放點，上限線與打平線落在原型算出的位置", async () => {
    const { TargetRuler, rulerScale } = await import("./TargetRuler");
    // Prototype: max = max(1.6 × 450, 617.5 × 1.08) = 720 → cap at 62.5%, 打平 520 at 72.22%.
    const { max, pos } = rulerScale(450, daily.flatMap((a) => (a.costPerResult === null ? [] : [a.costPerResult])));
    expect(max).toBe(720);
    expect(pos(450)).toBe(62.5);
    const { container } = render(<TargetRuler ads={daily} cap={{ value: 450, basis: "own" }} breakEven={520} size="full" />);
    const cap = container.querySelector('[data-part="cap-mark"]') as HTMLElement;
    expect(cap.style.left).toBe("62.5%");
    expect(cap.textContent).toBe("上限 450");
    expect((container.querySelector('[data-part="break-even-mark"]') as HTMLElement).style.left).toBe(`${(520 / 720) * 100}%`);
    const dot = (name: string) => screen.getByRole("button", { name: new RegExp(`^${name}｜`) });
    expect(dot("提問式貼文").style.left).toBe(`${(617.5 / 720) * 100}%`);
    expect(dot("晨光隨行杯・日常出發").style.left).toBe(`${(48 / 720) * 100}%`);
    // a1–a4 sit within 4.8% of each other: they stack one level (33px) apart; a4 is the fourth.
    expect(dot("開箱 15 秒・單手開蓋").style.bottom).toBe("99px");
    // 沒賣出 has no cost: it sits in the box, not on the axis.
    expect(dot("秋季新色預告").style.left).toBe("");
    expect(screen.getByRole("group", { name: "對照上限：上限 450；沒賣出 1、太貴 1、偏貴 1、划算 5" })).toBeTruthy();
  });

  it("TargetRuler 沒上限畫空狀態；暫用打平標在上限位置；清理標出要關的；剛開始的花費未知不印 0", async () => {
    const { TargetRuler } = await import("./TargetRuler");
    const { container, rerender } = render(<TargetRuler ads={daily} cap={null} size="mid" />);
    expect(container.querySelector('[data-variant="empty"]')).toBeTruthy();
    expect(screen.getByText("沒設上限，先不分等級")).toBeTruthy();
    rerender(<TargetRuler ads={daily} cap={{ value: 520, basis: "break_even" }} breakEven={520} size="mid" highlight={{ mode: "close", ids: ["a7", "a8"] }} />);
    expect(container.querySelector('[data-part="cap-mark"]')?.textContent).toBe("暫用打平 520");
    expect(container.querySelector('[data-part="break-even-mark"]')).toBeNull();
    expect(screen.getAllByText("關")).toHaveLength(2);
    rerender(<TargetRuler ads={[{ id: "m2", name: "中秋限定・月光藍開箱", grade: "insufficient", gradeLabel: null, costPerResult: null, spend: null }]} cap={{ value: 450, basis: "own" }} size="full" />);
    expect(screen.getByText("剛開始、數字還不夠 1 則")).toBeTruthy();
    expect(screen.getByText(/已花 未知／1,350 元/)).toBeTruthy();
  });

  it("F28-I14：TargetRuler 圖片載入失敗（Meta 網址過期）換成中性佔位，不出破圖", async () => {
    const { TargetRuler } = await import("./TargetRuler");
    const ads = [{ ...daily[0], thumbnailUrl: "https://scontent.example/expired.jpg" }];
    const { container } = render(<TargetRuler ads={ads} cap={{ value: 450, basis: "own" }} size="full" />);
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
    expect(screen.getByText("—")).toBeTruthy();
    expect(screen.getByText("9 月已花 未知")).toBeTruthy();
    expect(screen.getByText("划算＝在各活動上限內")).toBeTruthy();
  });

  it("MoneyMeter 上限線在 75%；超過 1.2 倍上限變紅；不知道數值只畫空軌", async () => {
    const { MoneyMeter } = await import("./MoneyMeter");
    const { container, rerender } = render(<MoneyMeter value={600} cap={{ value: 450, basis: "own" }} size="lg" />);
    expect(container.querySelector("u")?.className).toContain("left-3/4");
    const fill = container.querySelector("i") as HTMLElement;
    expect(fill.className).toContain("bg-danger");
    expect(fill.style.width).toBe("100%");
    expect(screen.getByText("上限 450")).toBeTruthy();
    rerender(<MoneyMeter value={null} cap={{ value: 450, basis: "own" }} size="sm" />);
    expect(container.querySelector("i")).toBeNull();
  });

  it("PaceChart 沒月預算不畫速度線；已花未知不印已花", async () => {
    const { PaceChart } = await import("./PaceChart");
    const days = [{ day: 10, cumulative: 8000 }, { day: 23, cumulative: 22000 }];
    const { container, rerender } = render(<PaceChart month={9} dayOfMonth={23} daysInMonth={30} budget={60000} spent={22000} daily={days} projected={28696} />);
    expect(screen.getByRole("img", { name: "預算 60,000，已花 22,000，照預算今天應花到 46,000" })).toBeTruthy();
    expect(container.querySelector('[data-part="pace-line"]')).toBeTruthy();
    rerender(<PaceChart month={9} dayOfMonth={23} daysInMonth={30} budget={null} spent={null} daily={[]} projected={null} />);
    expect(container.querySelector('[data-part="pace-line"]')).toBeNull();
    expect(screen.getByText("沒設月預算")).toBeTruthy();
    expect(screen.queryByText(/^已花/)).toBeNull();
  });

  it("ScenarioBars 超出預算上限的列畫斜紋段與超出金額；算不出的列不能選", async () => {
    const { ScenarioBars } = await import("./ScenarioBars");
    const onSelect = vi.fn();
    const rows = [
      { key: "cons", label: "保守", total: 18000, overCap: null },
      { key: "cap", label: "照預算上限", total: 30000, overCap: null, recommended: true, saved: true },
      { key: "agg", label: "積極", total: 111600, overCap: 81600 },
      { key: "grow", label: "穩定成長", total: null, overCap: null },
    ];
    const { container } = render(<ScenarioBars rows={rows} budgetCap={30000} selected="cap" onSelect={onSelect} resultCap={450} />);
    expect(screen.getByText("超出 81,600")).toBeTruthy();
    expect(screen.getByText("約 40 筆購買")).toBeTruthy();
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
    render(<AllocationBar parts={[{ key: "new", label: "新客", pct: 70 }, { key: "re", label: "再行銷", pct: 20 }, { key: "x", label: "探索", pct: 10 }]} total={null} />);
    expect(screen.getByText("新客 70%", { selector: "i" })).toBeTruthy();
    expect(screen.queryByText(/・/)).toBeNull();
  });
});
