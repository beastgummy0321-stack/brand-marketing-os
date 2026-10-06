/** frontend/src/components/ads/patterns/kit30.test.tsx — F30-I03: the v10 kit pieces for the remaining ads-center
 * screens. Pure presentational pieces, fed props directly (no fetch mocks). */
import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ChangeTimeline, CopyField, CopyFields, DAY_SWATCH, DayGrid, Legend, MoneyInput, PickCard, PickGroup, ProgressSegments, SlotGrid, SlotTile,
  SourceList, SourceRow, StageRail, TodoRow, TreeRows, type DayGridRow,
} from ".";

const STATIONS = [
  { key: "plan", label: "計畫" }, { key: "assets", label: "素材" }, { key: "launch", label: "上架" },
  { key: "read", label: "判讀" }, { key: "decide", label: "決策" }, { key: "review", label: "回顧" },
];

describe("StageRail", () => {
  it("six stations: done ones show ✓, the current one carries aria-current=step, the rest their number", () => {
    render(<StageRail stations={STATIONS} current="launch" done={["plan", "assets"]} onSelect={() => {}} />);
    const nav = screen.getByRole("navigation", { name: "活動進度" });
    const buttons = within(nav).getAllByRole("button");
    expect(buttons).toHaveLength(6);
    expect(buttons[0].textContent).toContain("✓");
    expect(buttons[0].textContent).toContain("已完成");
    expect(buttons[2].getAttribute("aria-current")).toBe("step");
    expect(buttons.filter((b) => b.getAttribute("aria-current") === "step")).toHaveLength(1);
    expect(buttons[3].textContent).toBe("4判讀");
    expect(nav.querySelectorAll("li")[1].dataset.state).toBe("done");
    expect(nav.querySelectorAll("li")[4].dataset.state).toBe("todo");
  });

  it("done comes from the contract, not the position: a later station can be done while an earlier is not", () => {
    render(<StageRail stations={STATIONS} current="read" done={["plan", "launch"]} onSelect={() => {}} />);
    const items = screen.getByRole("navigation").querySelectorAll("li");
    expect(items[1].dataset.state).toBe("todo");
    expect(items[2].dataset.state).toBe("done");
  });

  it("keyboard: Tab to a station and Enter selects it", async () => {
    const onSelect = vi.fn();
    render(<StageRail stations={STATIONS} current="plan" done={[]} onSelect={onSelect} />);
    const user = userEvent.setup();
    await user.tab();
    await user.tab();
    expect(document.activeElement?.textContent).toContain("素材");
    await user.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledWith("assets");
  });

  it("a station with `to` is a link", () => {
    render(<MemoryRouter><StageRail stations={STATIONS.map((s) => ({ ...s, to: `/c?tab=${s.key}` }))} current="plan" done={[]} /></MemoryRouter>);
    expect(screen.getAllByRole("link")).toHaveLength(6);
    expect(screen.getAllByRole("link")[0].getAttribute("aria-current")).toBe("step");
  });
});

describe("SourceList", () => {
  it("rows print the name, a ✓ on an ok chip, the note and the action; dimmed rows fade", () => {
    render(
      <SourceList>
        <SourceRow icon="∞" name="Meta 廣告帳戶・主帳戶" tone="ok" status="正常" note="最近讀取 09/23 08:40" />
        <SourceRow icon="∞" name="Meta 廣告帳戶・中秋" tone="warn" status="權限失效" note="09/17、09/18 讀不到" action={<button type="button">重新授權 →</button>} />
        <SourceRow icon="G" name="Google Ads" tone="neutral" status="尚未支援" note="接上後開放" dimmed />
      </SourceList>,
    );
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText("✓ 正常")).toBeTruthy();
    expect(within(rows[1]).getByText("權限失效").textContent).toBe("權限失效");
    expect(within(rows[1]).getByRole("button", { name: "重新授權 →" })).toBeTruthy();
    expect(rows[2].className).toContain("opacity-60");
    expect(rows[1].dataset.variant).toBe("warn");
  });
});

const day = (d: number) => `2026-09-${String(d).padStart(2, "0")}`;
const month = (state: (d: number) => DayGridRow["days"][number]["state"]) => Array.from({ length: 30 }, (_, i) => ({ date: day(i + 1), state: state(i + 1) }));

describe("DayGrid + Legend", () => {
  const rows: DayGridRow[] = [
    { key: "a", label: "主帳戶", days: month((d) => (d > 23 ? "future" : "ok")) },
    { key: "b", label: "中秋活動帳戶", days: month((d) => (d > 23 ? "future" : d < 10 ? "none" : d === 17 || d === 18 ? "missing" : "ok")) },
  ];

  it("renders every state, a title per cell, the row labels and one today marker", () => {
    const { container } = render(<DayGrid rows={rows} today={day(23)} />);
    expect(screen.getByText("主帳戶")).toBeTruthy();
    expect(screen.getByText("中秋活動帳戶")).toBeTruthy();
    const cells = container.querySelectorAll("[data-state]");
    expect(cells).toHaveLength(60);
    expect(screen.getAllByTitle("9/17 缺資料")).toHaveLength(1);
    expect(screen.getAllByTitle("9/5 不需要")).toHaveLength(1);
    expect(screen.getAllByTitle("9/30 還沒到")).toHaveLength(2);
    expect(screen.getAllByTitle("9/1 有資料")).toHaveLength(1);
    expect(screen.getByRole("img", { name: "中秋活動帳戶 9/18 缺資料" }).dataset.state).toBe("missing");
    expect(container.querySelectorAll("[data-today]")).toHaveLength(2);
    const missing = screen.getByTitle("9/17 缺資料");
    expect(missing.className).toContain("border-dashed");
    expect(screen.getAllByTitle("9/1 有資料")[0].className).toContain(DAY_SWATCH.ok);
  });

  it("the header numbers only the tick days, and the grid has one column per day", () => {
    const { container } = render(<DayGrid rows={rows} today={null} />);
    const grid = container.querySelector("[data-slot=day-grid]") as HTMLElement;
    expect(grid.style.gridTemplateColumns).toBe("150px repeat(30, minmax(0, 1fr))");
    const header = Array.from(grid.children).slice(1, 31).map((e) => e.textContent).filter(Boolean);
    expect(header).toEqual(["1", "5", "10", "15", "20", "25", "30"]);
    expect(container.querySelectorAll("[data-today]")).toHaveLength(0);
  });

  it("F31-I12: a long account name wraps in full inside the label column instead of being cut with an ellipsis", () => {
    const long = "Beast Gummy 台灣官方旗艦店主要投放帳戶（新台幣計價）・BeastGummyMidAutumnFestivalTW2026";
    expect(long.length).toBeGreaterThanOrEqual(60);
    const { container } = render(<DayGrid rows={[{ key: "a", label: long, days: month(() => "ok") }]} today={null} />);
    const label = screen.getByText(long);
    expect(label.textContent).toBe(long);
    expect(label.className).not.toContain("truncate");
    expect(label.className).toContain("[overflow-wrap:anywhere]");
    // The 150px label column and one square per day stay as they are.
    expect((container.querySelector("[data-slot=day-grid]") as HTMLElement).style.gridTemplateColumns).toBe("150px repeat(30, minmax(0, 1fr))");
    expect(container.querySelectorAll("[data-state]")).toHaveLength(30);
  });

  it("no rows renders nothing", () => {
    const { container } = render(<DayGrid rows={[]} />);
    expect(container.innerHTML).toBe("");
  });

  it("Legend prints each entry with the swatch classes it was given", () => {
    const { container } = render(<Legend items={[{ label: "有資料", swatch: DAY_SWATCH.ok }, { label: "缺資料", swatch: DAY_SWATCH.missing }, { label: "上限", swatch: "bg-foreground", line: true }]} />);
    expect(screen.getByText("有資料")).toBeTruthy();
    const swatches = container.querySelectorAll("i");
    expect(swatches[1].className).toContain("border-dashed");
    expect(swatches[2].className).toContain("w-0.5");
  });
});

describe("CopyField", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("copies the value and says 已複製; a refused clipboard says 請手動選取複製", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    render(<CopyFields><CopyField label="每日預算" value="NT$400" /><CopyField label="名稱" value="晨光・A" copy={false} /></CopyFields>);
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    await user.click(screen.getByRole("button", { name: "複製每日預算" }));
    expect(writeText).toHaveBeenCalledWith("NT$400");
    expect(await screen.findByText("已複製")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "複製名稱" })).toBeNull();
    expect(screen.getByText("晨光・A")).toBeTruthy();

    Object.defineProperty(navigator, "clipboard", { value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) }, configurable: true });
    render(<CopyField label="網址" value="https://example.com" />);
    await user.click(screen.getByRole("button", { name: "複製網址" }));
    expect(await screen.findByText("請手動選取複製")).toBeTruthy();
  });
});

describe("SlotGrid", () => {
  it("ready, missing and reserved tiles; the reserved seat has no button", () => {
    render(
      <SlotGrid label="廣告組 A">
        <SlotTile variant="ready" name="晨光隨行杯・日常出發" thumbnailUrl={null} status={<span>已確認</span>} />
        <SlotTile variant="missing" actions={<button type="button">上傳</button>} />
        <SlotTile variant="reserved" title="站內出圖" />
      </SlotGrid>,
    );
    const tiles = within(screen.getByRole("list", { name: "廣告組 A" })).getAllByRole("listitem");
    expect(tiles.map((t) => t.dataset.variant)).toEqual(["ready", "missing", "reserved"]);
    expect(within(tiles[0]).getByText("已確認")).toBeTruthy();
    expect(within(tiles[1]).getByText("缺 1 則")).toBeTruthy();
    expect(within(tiles[1]).getByRole("button", { name: "上傳" })).toBeTruthy();
    expect(within(tiles[2]).getByText("接上後開放")).toBeTruthy();
    expect(within(tiles[2]).queryByRole("button")).toBeNull();
  });

  it("F35 two halves: the copy half on a ready tile, the copy-only and image-only variants with their dashed half", () => {
    render(
      <SlotGrid label="廣告組 B">
        <SlotTile variant="ready" name="通勤路上一顆" thumbnailUrl={null} copy={{ label: "已確認", text: "通勤路上，一顆就好　捷運上不用找水。" }} status={<span>已確認</span>} />
        <SlotTile variant="copy-only" name="看過還在猶豫的你" copy={{ label: "工作檯第 1 版", text: "讀書工作通勤，少一個步驟　免配水、免拆包裝。" }}
          imageActions={<button type="button">上傳</button>} extra={<a href="/workbench">看圖片提示詞</a>} status={<span>有文案，缺圖</span>} />
        <SlotTile variant="image-only" name="體驗包 3 入免運" thumbnailUrl="https://scontent.example/c.jpg"
          copyActions={<button type="button">選一版文案</button>} status={<span>有圖，缺文案</span>} />
      </SlotGrid>,
    );
    const tiles = within(screen.getByRole("list", { name: "廣告組 B" })).getAllByRole("listitem");
    expect(tiles.map((t) => t.dataset.variant)).toEqual(["ready", "copy-only", "image-only"]);
    expect(within(tiles[0]).getByText(/文案 · 已確認/)).toBeTruthy();
    expect(within(tiles[0]).getByText(/^通勤路上，一顆就好\s捷運上不用找水。$/).className).toContain("line-clamp-3");
    expect(within(tiles[1]).getByText("缺圖")).toBeTruthy();
    expect(within(tiles[1]).getByRole("button", { name: "上傳" })).toBeTruthy();
    expect(within(tiles[1]).getByText(/文案 · 工作檯第 1 版/)).toBeTruthy();
    expect(within(tiles[1]).getByRole("link", { name: "看圖片提示詞" })).toBeTruthy();
    expect(within(tiles[1]).getByText("有文案，缺圖")).toBeTruthy();
    expect(within(tiles[2]).getByText("缺文案")).toBeTruthy();
    expect(within(tiles[2]).getByRole("button", { name: "選一版文案" })).toBeTruthy();
    expect(tiles[2].querySelector('img[src="https://scontent.example/c.jpg"]')).toBeTruthy();
    expect(within(tiles[2]).queryByText(/文案 · /)).toBeNull();
  });

  it("F45: a ready tile's job region, the waiting variant's next-action region, and the empty copy half", () => {
    render(
      <SlotGrid label="廣告組 C">
        <SlotTile variant="ready" name="週末出遊・隨身一盒" thumbnailUrl={null} emptyCopy="文案還在寫" status={<span>處理中</span>}
          job={<p>文案生成中：工作檯正在寫 3 版文案</p>} />
        <SlotTile variant="waiting" name="備考生・讀到深夜" thumbnailUrl={null} emptyCopy="還沒選文案" status={<span>等你</span>}
          actions={<a href="/workbench">等你：到工作檯選定一版文案 →</a>} />
        <SlotTile variant="waiting" name="會議前・午休五分鐘" thumbnailUrl={null} copy={{ label: "待確認", text: "午休 5 分鐘，一顆就好" }}
          status={<span>等你</span>} actions={<button type="button">等你：確認這版文案</button>} note={<p>沒有檢查成功</p>} />
        <SlotTile variant="ready" name="通勤路上一顆" thumbnailUrl={null} status={<span>已確認</span>} />
      </SlotGrid>,
    );
    const tiles = within(screen.getByRole("list", { name: "廣告組 C" })).getAllByRole("listitem");
    expect(tiles.map((t) => t.dataset.variant)).toEqual(["ready", "waiting", "waiting", "ready"]);
    expect(tiles[0].querySelector("[data-slot=slot-job]")?.textContent).toBe("文案生成中：工作檯正在寫 3 版文案");
    expect(tiles[0].querySelector("[data-slot=slot-copy]")?.getAttribute("data-variant")).toBe("none");
    expect(within(tiles[0]).getByText("文案還在寫")).toBeTruthy();
    expect(tiles[1].className).toContain("border-warning");
    expect(within(tiles[1].querySelector("[data-slot=slot-next]") as HTMLElement).getByRole("link", { name: "等你：到工作檯選定一版文案 →" })).toBeTruthy();
    expect(within(tiles[1]).getByText("還沒選文案")).toBeTruthy();
    // A waiting copy is not confirmed: no ✓ beside 待確認.
    expect(within(tiles[2]).getByText(/文案 · 待確認/).textContent).not.toContain("✓");
    expect(within(tiles[2].querySelector("[data-slot=slot-next]") as HTMLElement).getByText("沒有檢查成功")).toBeTruthy();
    // Without a job or an empty-copy sentence a ready tile is unchanged.
    expect(tiles[3].querySelector("[data-slot=slot-job]")).toBeNull();
    expect(tiles[3].querySelector("[data-slot=slot-copy]")).toBeNull();
  });
});

describe("ProgressSegments (F45)", () => {
  it("waiting has its own colour, apart from running and blocked", () => {
    render(<ProgressSegments label="2／5 格已備妥" segments={[
      { key: "1", state: "ok" }, { key: "2", state: "running" }, { key: "3", state: "waiting" }, { key: "4", state: "blocked" }, { key: "5", state: "todo" },
    ]} />);
    const fills = [...screen.getByRole("img", { name: "2／5 格已備妥" }).querySelectorAll("[data-state]")].map((i) => i.className);
    expect(new Set(fills).size).toBe(5);
    expect(fills[2]).toContain("bg-warning");
  });
});

describe("TreeRows", () => {
  it("root, groups and leaves; a missing leaf says 缺素材 and a dimmed one fades", () => {
    render(
      <TreeRows
        root={{ kind: "活動", name: "日常銷售", note: "每日 600・購買" }}
        groups={[
          { key: "A", kind: "廣告組", name: "廣告組 A", note: "每日 400・2 則", leaves: [
            { key: "1", name: "日常出發", thumbnailUrl: null, chip: <span>划算</span>, value: "380 元" },
            { key: "2", name: "兩入組", thumbnailUrl: null, dimmed: true, chip: <span>關閉中</span> },
          ] },
          { key: "B", kind: "廣告組", name: "廣告組 B", leaves: [{ key: "3", name: "", thumbnailUrl: null, missing: true }] },
        ]}
      />,
    );
    expect(screen.getByText("日常銷售")).toBeTruthy();
    const a = screen.getByRole("list", { name: "廣告組 A" });
    const leaves = within(a).getAllByRole("listitem");
    expect(within(leaves[0]).getByText("380 元")).toBeTruthy();
    expect(leaves[1].className).toContain("opacity-50");
    expect(within(screen.getByRole("list", { name: "廣告組 B" })).getByText("缺素材")).toBeTruthy();
  });

  it("F31-I12: a long ad name keeps a readable width; chip and number move under it as one right-aligned cell", () => {
    const long = "秋季新色預購・兩入組限定優惠・滿三千送品牌帆布袋與試用包・九月底前下單加贈專屬贈品組合・BeastGummyTWAutumn2026";
    expect(long.length).toBeGreaterThanOrEqual(60);
    render(
      <TreeRows
        root={{ kind: "活動", name: "日常銷售" }}
        groups={[{ key: "A", kind: "廣告組", name: "廣告組 A", leaves: [
          { key: "1", name: long, thumbnailUrl: null, chip: <span>偏貴</span>, value: "2,345.67 元・在虧（打平 804）" },
        ] }]}
      />,
    );
    const leaf = within(screen.getByRole("list", { name: "廣告組 A" })).getByRole("listitem");
    const name = within(leaf).getByText(long);
    expect(name.textContent).toBe(long);
    // The row wraps rather than shrinking the name to a sliver: the name has a floor and grows from its own width.
    expect(leaf.className).toContain("flex-wrap");
    const nameCell = leaf.querySelector("[data-part=name]") as HTMLElement;
    expect(nameCell).not.toBeNull();
    expect(nameCell.contains(name)).toBe(true);
    expect(nameCell.className).toMatch(/min-w-\[\d+rem\]/);
    // Grade and number stay together in one cell that keeps to the right edge when it drops to the next line.
    const facts = leaf.querySelector("[data-part=facts]") as HTMLElement;
    expect(facts).not.toBeNull();
    expect(facts.className).toContain("ml-auto");
    expect(within(facts).getByText("偏貴")).toBeTruthy();
    expect(within(facts).getByText("2,345.67 元・在虧（打平 804）")).toBeTruthy();
  });
});

describe("ChangeTimeline", () => {
  it("time, title, reason, progress x／N and the state chip; rejected rows have no progress", () => {
    const { container } = render(
      <ChangeTimeline rows={[
        { key: "1", at: "09/21 16:30", title: "改文案", state: "verified", checked: 1, total: 1 },
        { key: "2", at: "09/20 14:05", title: "首次上架・8 項", state: "stale", checked: 2, total: 8, action: <button type="button">打開</button> },
        { key: "3", at: "09/15 10:20", title: "清理：關 1 則", state: "rejected", reason: "兩入組還在檔期", checked: 0, total: 1 },
        { key: "4", at: "09/23 10:12", title: "改預算", state: "platform", checked: 0, total: 2, label: "等你到 Meta 完成" },
      ]} />,
    );
    const rows = screen.getAllByRole("listitem");
    expect(rows.map((r) => r.dataset.variant)).toEqual(["verified", "stale", "rejected", "platform"]);
    expect(within(rows[0]).getByText("✓ 已核對")).toBeTruthy();
    expect(within(rows[1]).getByText("2／8 已核對")).toBeTruthy();
    expect(Array.from(rows[1].querySelectorAll("[data-slot=progress-segments] i")).map((i) => (i as HTMLElement).dataset.state))
      .toEqual(["ok", "ok", "changed", "changed", "changed", "changed", "changed", "changed"]);
    expect(within(rows[1]).getByRole("button", { name: "打開" })).toBeTruthy();
    expect(within(rows[2]).getByText("原因：兩入組還在檔期")).toBeTruthy();
    expect(rows[2].querySelector("[data-slot=progress-segments]")).toBeNull();
    expect(within(rows[3]).getByText("等你到 Meta 完成")).toBeTruthy();
    expect(container.querySelectorAll("[data-slot=chip]")).toHaveLength(4);
  });
});

function Picker({ onPick }: { onPick?: (v: string) => void }) {
  const [v, setV] = useState<string | null>(null);
  return (
    <PickGroup label="目標" value={v} onChange={(x) => { setV(x); onPick?.(x); }}>
      <PickCard value="sales" title="購買" icon="🛒" note="看每賣一筆花多少" />
      <PickCard value="lead" title="名單" icon="✉" note="看每筆名單成本" />
      <PickCard value="engage" title="互動" icon="♡" note="看每次互動成本" disabledReason="尚未開放" />
      <PickCard value="traffic" title="流量" icon="↗" note="看每次點擊成本" />
    </PickGroup>
  );
}

describe("PickCard", () => {
  it("radios in a radiogroup; a click checks one; the reserved card is disabled with its note", async () => {
    render(<Picker />);
    const group = screen.getByRole("radiogroup", { name: "目標" });
    const radios = within(group).getAllByRole("radio");
    expect(radios.every((r) => r.getAttribute("aria-checked") === "false")).toBe(true);
    const user = userEvent.setup();
    await user.click(radios[1]);
    expect(radios[1].getAttribute("aria-checked")).toBe("true");
    expect(radios[0].getAttribute("aria-checked")).toBe("false");
    expect((radios[2] as HTMLButtonElement).disabled).toBe(true);
    expect(within(radios[2]).getByText("尚未開放")).toBeTruthy();
    expect(within(radios[2]).queryByText("看每次互動成本")).toBeNull();
    await user.click(radios[2]);
    expect(radios[2].getAttribute("aria-checked")).toBe("false");
  });

  it("keyboard: arrows move and pick, skipping the disabled card; Space picks; only the picked card is tabbable", async () => {
    const onPick = vi.fn();
    render(<Picker onPick={onPick} />);
    const radios = screen.getAllByRole("radio");
    const user = userEvent.setup();
    await user.tab();
    expect(document.activeElement).toBe(radios[0]);
    await user.keyboard(" ");
    expect(radios[0].getAttribute("aria-checked")).toBe("true");
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(radios[1]);
    expect(radios[1].getAttribute("aria-checked")).toBe("true");
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(radios[3]);
    expect(onPick).toHaveBeenLastCalledWith("traffic");
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(radios[0]);
    await user.keyboard("{End}");
    expect(radios[3].getAttribute("aria-checked")).toBe("true");
    expect(radios.map((r) => r.tabIndex)).toEqual([-1, -1, -1, 0]);
  });

  it("the product layout draws a thumbnail and the badge", () => {
    render(
      <PickGroup label="商品" value="cup" onChange={() => {}}>
        <PickCard value="cup" title="晨光隨行杯" note="NT$1,580" thumbnailUrl={null} badge={<span>有成本</span>} />
      </PickGroup>,
    );
    const card = screen.getByRole("radio", { name: /晨光隨行杯/ });
    expect(card.getAttribute("aria-checked")).toBe("true");
    expect(card.dataset.variant).toBe("picked");
    expect(within(card).getByText("有成本")).toBeTruthy();
  });
});

function Money({ onValue }: { onValue: (v: number | null) => void }) {
  const [v, setV] = useState<number | null>(null);
  return <MoneyInput label="這個活動最多花" value={v} onChange={(x) => { setV(x); onValue(x); }} />;
}

describe("MoneyInput", () => {
  it("accepts digits, drops thousands separators, rejects anything else; empty is null", async () => {
    const onValue = vi.fn();
    render(<Money onValue={onValue} />);
    const input = screen.getByRole("textbox", { name: "這個活動最多花" }) as HTMLInputElement;
    expect(input.inputMode).toBe("numeric");
    const user = userEvent.setup();
    await user.type(input, "3a0-0.e0");
    expect(input.value).toBe("3000");
    expect(onValue).toHaveBeenLastCalledWith(3000);
    await user.clear(input);
    expect(onValue).toHaveBeenLastCalledWith(null);
    expect(input.value).toBe("");
    await user.click(input);
    await user.paste("30,000");
    expect(input.value).toBe("30000");
    await user.paste("x");
    expect(input.value).toBe("30000");
    expect(screen.getByText("NT$")).toBeTruthy();
  });

  it("Enter runs onEnter", async () => {
    const onEnter = vi.fn();
    render(<MoneyInput label="上限" value={450} onChange={() => {}} onEnter={onEnter} />);
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: "上限" }), "{Enter}");
    expect(onEnter).toHaveBeenCalledOnce();
  });
});

describe("TodoRow v10 states", () => {
  it("mismatch shows ≠ on an amber disc, locked keeps the number, state wins over done", () => {
    const { container } = render(
      <div>
        <TodoRow no={1} state="mismatch">每日預算</TodoRow>
        <TodoRow no={2} state="locked">廣告組 B</TodoRow>
        <TodoRow no={3} done>廣告 C</TodoRow>
        <TodoRow no={4} done state="locked">廣告 D</TodoRow>
      </div>,
    );
    const rows = Array.from(container.querySelectorAll<HTMLElement>("[data-slot=todo-row]"));
    expect(rows.map((r) => r.dataset.variant)).toEqual(["mismatch", "locked", "done", "locked"]);
    expect(screen.getByRole("img", { name: "不符" }).textContent).toBe("≠");
    expect(rows[0].firstElementChild?.className).toContain("bg-grade-watch");
    expect(rows[1].firstElementChild?.textContent).toBe("2");
    expect(rows[3].firstElementChild?.textContent).toBe("4");
  });
});


it("reason and busy cards cannot be selected by click or radio keyboard navigation", async () => {
  const pick = vi.fn();
  render(<PickGroup label="可選目標" value="open" onChange={pick}>
    <PickCard value="open" title="可選" />
    <PickCard value="off" title="不可選" disabledReason="先完成商品資料" />
    <PickCard value="busy" title="讀取中" busy />
    <PickCard value="last" title="最後一項" />
  </PickGroup>);
  const user = userEvent.setup();
  const off = screen.getByRole("radio", {name: /不可選/});
  expect(document.getElementById(off.getAttribute("aria-describedby")!)?.textContent).toBe("先完成商品資料");
  await user.click(off);
  await user.click(screen.getByRole("radio", {name: "讀取中"}));
  expect(pick).not.toHaveBeenCalled();
  screen.getByRole("radio", {name: "可選"}).focus();
  await user.keyboard("{ArrowRight}");
  expect(pick).toHaveBeenCalledWith("last");
});
