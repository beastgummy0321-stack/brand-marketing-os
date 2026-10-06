/** frontend/src/components/workbench/WorkbenchHomePage.test.tsx — F36-I02 (drill-6 #5): the empty
 * brand state names the real entry (「投放結構」 → 「開始做素材 →」), no longer mentions a 派工 button
 * that does not exist, and links to the campaigns list. */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/workbenchApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/workbenchApi")>("@/lib/workbenchApi");
  return { ...actual, listPacks: vi.fn(), closePack: vi.fn() };
});
vi.mock("@/components/layout/WorkspaceContext", () => ({
  useWorkspace: () => ({
    brands: [{ brand_id: "brd_1", brand_name: "測試品牌" }],
    // F50-I14: the org is in Taipei whatever zone the test runner is in.
    identity: { org: { id: "org_1", timezone: "Asia/Taipei", today: "2026-10-04" } },
  }),
}));

import { closePack, listPacks, type PackCard } from "@/lib/workbenchApi";
import { PackCardTile, WorkbenchHomePage } from "./WorkbenchHomePage";

const mockListPacks = vi.mocked(listPacks);
const mockClosePack = vi.mocked(closePack);

afterEach(() => {
  vi.clearAllMocks();
});

function renderHome(brandId = "brd_1") {
  return render(
    <MemoryRouter>
      <WorkbenchHomePage brandId={brandId} />
    </MemoryRouter>,
  );
}

describe("WorkbenchHomePage 空狀態（F36-I02）", () => {
  it("沒有任務包時，說明句指向「投放結構」→「開始做素材 →」", async () => {
    mockListPacks.mockResolvedValue([]);
    renderHome();

    expect(
      await screen.findByText(
        "＋ 自由創作 自己開一個工作；或到投放中心打開一個活動，在「投放結構」按「開始做素材 →」，任務包就會送過來。",
      ),
    ).toBeTruthy();
  });

  it("不再提到不存在的「派工」按鈕", async () => {
    mockListPacks.mockResolvedValue([]);
    renderHome();

    await screen.findByText("目前沒有任務包");
    expect(screen.queryByText(/派工/)).toBeNull();
  });

  it("空狀態下方的連結指向該品牌的投放中心活動列表", async () => {
    mockListPacks.mockResolvedValue([]);
    renderHome("brd_1");

    const link = await screen.findByRole("link", { name: "前往投放中心 →" });
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns");
  });
});

/** F47 (drill-10 乙 #15–#17, #21): real-shaped cards — an ads pack with a source campaign whose next step is an
 * image to choose, and a free job without a source. */
function card(overrides: Partial<PackCard> = {}): PackCard {
  return {
    id: "wbp_ads", name: "10/17 秋季活動", subtitle: "通勤族", source_kind: "schedule_node", source_label: "廣告排程",
    status: "running", sets_total: 4, sets_done: 3, progress_pct: 75,
    next_step: { set_id: "wbb_4", set_name: "通勤開會免配水補給", part: "image_prompt", label: "圖片待選定" },
    counts: [{ part: "copy", label: "文案", selected: 4, required: 4 }],
    updated_at: new Date().toISOString(),
    origin_href: "/brands/brd_1/ads/campaigns/adc_17?tab=assets", closed: false, approved_gap: null,
    ...overrides,
  };
}
const FREE = card({
  id: "wbp_free", name: "自由工作 #2", source_kind: "free_job", source_label: "自由創作", next_step: null,
  origin_href: null,
});

function Where() {
  const loc = useLocation();
  return <div data-testid="where">{loc.pathname + loc.search}</div>;
}

function renderRouted() {
  return render(
    <MemoryRouter initialEntries={["/brands/brd_1/workbench"]}>
      <Routes>
        <Route path="*" element={<WorkbenchHomePage brandId="brd_1" />} />
      </Routes>
      <Where />
    </MemoryRouter>,
  );
}

async function openMenu(packName: string) {
  const tile = (await screen.findByRole("heading", { name: packName })).closest(".surface") as HTMLElement;
  await userEvent.click(within(tile).getByRole("button", { name: "更多操作" }));
  return tile;
}

describe("WorkbenchHomePage controls（F47）", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
  });

  it("查看全部 → shows every open pack as the list, clears the search and scrolls to it", async () => {
    mockListPacks.mockResolvedValue([card(), FREE]);
    renderRouted();
    await screen.findByRole("heading", { name: "10/17 秋季活動" });
    await userEvent.click(screen.getByRole("button", { name: "進行中" }));
    await userEvent.type(screen.getByPlaceholderText("搜尋工作、Campaign、素材組"), "秋");

    await userEvent.click(screen.getByRole("button", { name: "查看全部 →" }));

    await waitFor(() => expect(mockListPacks).toHaveBeenLastCalledWith("brd_1", { status: "all", q: undefined, sort: "updated" }));
    expect((screen.getByPlaceholderText("搜尋工作、Campaign、素材組") as HTMLInputElement).value).toBe("");
    expect(screen.getByRole("button", { name: "清單" }).getAttribute("aria-pressed")).toBe("true");
    expect(await screen.findByRole("table")).toBeTruthy();
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });

  it("查看來源 opens the source campaign; a pack without a source has no such item", async () => {
    mockListPacks.mockResolvedValue([card(), FREE]);
    renderRouted();
    await openMenu("自由工作 #2");
    expect(screen.queryByRole("menuitem", { name: "查看來源" })).toBeNull();
    await userEvent.keyboard("{Escape}");

    await openMenu("10/17 秋季活動");
    await userEvent.click(screen.getByRole("menuitem", { name: "查看來源" }));
    expect(screen.getByTestId("where").textContent).toBe("/brands/brd_1/ads/campaigns/adc_17?tab=assets");
  });

  it("下一步・圖片待選定 opens that set on its image tab", async () => {
    mockListPacks.mockResolvedValue([card()]);
    renderRouted();
    await userEvent.click(await screen.findByRole("button", { name: /下一步通勤開會免配水補給・圖片待選定/ }));
    expect(screen.getByTestId("where").textContent).toBe("/brands/brd_1/workbench/packs/wbp_ads/sets/wbb_4?part=image_prompt");
  });

  it("關閉任務包 asks once and says what happens; 取消 keeps it, 確定關閉 closes it", async () => {
    mockListPacks.mockResolvedValue([card()]);
    mockClosePack.mockResolvedValue({} as never);
    renderRouted();
    await openMenu("10/17 秋季活動");
    await userEvent.click(screen.getByRole("menuitem", { name: "關閉任務包" }));

    const dialog = screen.getByRole("dialog", { name: "關閉任務包「10/17 秋季活動」？" });
    expect(dialog.textContent).toContain("移到「已關閉」；裡面的素材組和已選定的版本都會保留");
    await userEvent.click(within(dialog).getByRole("button", { name: "取消" }));
    expect(mockClosePack).not.toHaveBeenCalled();

    await openMenu("10/17 秋季活動");
    await userEvent.click(screen.getByRole("menuitem", { name: "關閉任務包" }));
    await userEvent.click(screen.getByRole("button", { name: "確定關閉" }));
    expect(mockClosePack).toHaveBeenCalledWith("brd_1", "wbp_ads");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("已關閉 lists the closed packs, marked as such, with no close item", async () => {
    mockListPacks.mockResolvedValue([card()]);
    renderRouted();
    await screen.findByRole("heading", { name: "10/17 秋季活動" });
    mockListPacks.mockResolvedValue([card({ closed: true })]);
    await userEvent.click(screen.getByRole("button", { name: "已關閉" }));
    await waitFor(() => expect(mockListPacks).toHaveBeenLastCalledWith("brd_1", { status: "closed", q: undefined, sort: "updated" }));
    const tile = await openMenu("10/17 秋季活動");
    expect(within(tile).getByText("已關閉", { selector: "[data-slot=badge]" })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: "關閉任務包" })).toBeNull();
  });

  it("an approved pack still missing sets reads 已核准・還缺 N 組, not 已完成", async () => {
    mockListPacks.mockResolvedValue([card({ status: "done", sets_done: 0, sets_total: 1,
      approved_gap: { missing: 1, set_id: "wbb_1", label: "已核准・還缺 1 組" } })]);
    renderRouted();
    expect(await screen.findAllByText("已核准・還缺 1 組")).not.toHaveLength(0);
    expect(screen.queryByText("已完成", { selector: "[data-slot=badge]" })).toBeNull();
  });
});

describe("Shared pack card variants (F52-I17)", () => {
  it("preview removes title, next-step, menu and continue actions even for an actionable source card", async () => {
    const user = userEvent.setup();
    const pack = card();
    const rendered = render(<MemoryRouter initialEntries={["/preview"]}><PackCardTile pack={pack} variant="preview" /><Where /></MemoryRouter>);
    const tile = screen.getByRole("heading", { name: pack.name }).closest(".surface")!;
    expect(within(tile as HTMLElement).queryAllByRole("button")).toHaveLength(0);
    expect(within(tile as HTMLElement).queryAllByRole("link")).toHaveLength(0);
    expect(tile.querySelector('[tabindex]:not([tabindex="-1"]),input,select,textarea')).toBeNull();
    expect(within(tile as HTMLElement).getByText("預覽")).toBeTruthy();
    expect(within(tile as HTMLElement).getByText("廣告排程")).toBeTruthy();
    expect(within(tile as HTMLElement).getByText("4／4")).toBeTruthy();
    expect(within(tile as HTMLElement).getByText("素材組總數 4")).toBeTruthy();
    await user.click(screen.getByRole("heading", { name: pack.name }));
    expect(screen.getByTestId("where").textContent).toBe("/preview");
    rendered.unmount();
  });

  it.each(["title", "continue"])("real cards keep %s navigation to the real pack", async (control) => {
    const user = userEvent.setup();
    const pack = card();
    render(<MemoryRouter initialEntries={["/workbench"]}><PackCardTile pack={pack} brandId="brd_1" onClose={vi.fn()} /><Where /></MemoryRouter>);
    await user.click(screen.getByRole("button", { name: control === "title" ? /10\/17 秋季活動/ : "繼續 →" }));
    expect(screen.getByTestId("where").textContent).toBe("/brands/brd_1/workbench/packs/wbp_ads");
  });
});

describe("Workbench home consumer acceptance (F52-I18)", () => {
  it("empty and loading home states offer real entry points without manufacturing a preview card", async () => {
    const user = userEvent.setup();
    let resolvePacks!: (packs: PackCard[]) => void;
    mockListPacks.mockReturnValue(new Promise((resolve) => { resolvePacks = resolve; }));
    renderRouted();
    expect(screen.getByRole("heading", { name: "任務包（0）" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "更多操作" })).toBeNull();
    expect(screen.queryByRole("button", { name: "繼續 →" })).toBeNull();
    expect(screen.queryByText("預覽")).toBeNull();
    resolvePacks([]);
    expect(await screen.findByText("目前沒有任務包")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: /建立後產生/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "更多操作" })).toBeNull();
    expect(screen.queryByRole("button", { name: "繼續 →" })).toBeNull();
    await user.click(screen.getByRole("link", { name: /文案/ }));
    expect(screen.getByTestId("where").textContent).toBe("/brands/brd_1/workbench/new?type=copy");
  });

  it("loaded long-name cards still continue by keyboard and expose their real pack routes", async () => {
    const user = userEvent.setup();
    const pack = card({ name: "Beast Prime 秋季夜跑與通勤補給完整商品介紹及新手需求驗證素材任務包" });
    mockListPacks.mockResolvedValue([pack]);
    renderRouted();
    const heading = await screen.findByRole("heading", { name: pack.name });
    const tile = heading.closest(".surface") as HTMLElement;
    expect(within(tile).queryByText("預覽")).toBeNull();
    expect(within(tile).getByRole("button", { name: "更多操作" })).toBeTruthy();
    const continueButton = within(tile).getByRole("button", { name: "繼續 →" });
    continueButton.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByTestId("where").textContent).toBe("/brands/brd_1/workbench/packs/wbp_ads");
  });

  it("expands the loaded list and closes only the confirmed real card with a refreshed state", async () => {
    const user = userEvent.setup();
    mockListPacks.mockResolvedValue([card(), FREE]);
    mockClosePack.mockImplementation(async (brandId, packId) => {
      expect(brandId).toBe("brd_1");
      expect(packId).toBe("wbp_ads");
      mockListPacks.mockResolvedValue([card({ closed: true }), FREE]);
      return {} as never;
    });
    renderRouted();
    await screen.findByRole("heading", { name: "10/17 秋季活動" });
    await user.click(screen.getByRole("button", { name: "查看全部 →" }));
    expect(await screen.findByRole("table")).toBeTruthy();
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(3);
    await user.click(screen.getByRole("button", { name: "格狀" }));
    await openMenu("10/17 秋季活動");
    await user.click(screen.getByRole("menuitem", { name: "關閉任務包" }));
    await user.click(screen.getByRole("button", { name: "取消" }));
    expect(mockClosePack).not.toHaveBeenCalled();
    await openMenu("10/17 秋季活動");
    await user.click(screen.getByRole("menuitem", { name: "關閉任務包" }));
    await user.click(screen.getByRole("button", { name: "確定關閉" }));
    await waitFor(() => expect(mockClosePack).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const closedTile = screen.getByRole("heading", { name: "10/17 秋季活動" }).closest(".surface") as HTMLElement;
    expect(await within(closedTile).findByText("已關閉", { selector: "[data-slot=badge]" })).toBeTruthy();
    const freeTile = await openMenu("自由工作 #2");
    expect(screen.getByRole("menuitem", { name: "關閉任務包" })).toBeTruthy();
    expect(within(freeTile).queryByText("已關閉")).toBeNull();
  });
});
