/** F29-I16: the three v10 launch-settings blocks of the publish flow — the list stage's choice card (建議／你改的,
 * UTM live check, unreadable pixel list, save failure, read only after approval), the platform stage's copy block,
 * and the verify stage's readback (對上了／不一樣／讀不到 + 我看過了，一樣). */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  confirmLaunchSetting, getLaunchSettings, saveLaunchSettings,
  type LaunchSettingsValues, type LaunchSettingsView, type SettingsReadback as Readback,
} from "@/lib/adsLaunchSettingsApi";
import type { HandoffWorkspace } from "@/lib/adsHandoffApi";
import { LaunchSettingsCard } from "./LaunchSettingsCard";
import { LaunchSettingsCopy } from "./LaunchSettingsCopy";
import { SettingsReadback } from "./SettingsReadback";

vi.mock("@/lib/adsLaunchSettingsApi", () => ({
  getLaunchSettings: vi.fn(), saveLaunchSettings: vi.fn(), confirmLaunchSetting: vi.fn(),
}));
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "test-scope" }) }));

const REC: LaunchSettingsValues = {
  optimization_event: "purchase", bid_strategy: "lowest_cost", placement: { mode: "auto", positions: [] },
  audience: { age_min: 18, age_max: 65, gender: "all", countries: ["TW"] }, pixel_id: "px_4821",
  utm: "utm_source=meta&utm_medium=paid&utm_campaign=cmp_fall",
};

function view(over: Partial<LaunchSettingsView> = {}, values: Partial<LaunchSettingsValues> = {}): LaunchSettingsView {
  return {
    values: { ...REC, ...values }, recommended: REC, edited: [], errors: [],
    options: {
      optimization_event: [
        { value: "purchase", label: "購買", note: "Meta 要幫你找哪種人：會買的人" },
        { value: "add_to_cart", label: "加入購物車", note: "Meta 要幫你找哪種人：會放進購物車的人" },
      ],
      bid_strategy: [
        { value: "lowest_cost", label: "最低成本", note: "讓 Meta 用最少的錢買到結果" },
        { value: "cost_cap", label: "單次成果成本上限", note: "每筆盡量不超過你設的金額，但量可能變少" },
      ],
      positions: [
        { value: "facebook_feed", label: "Facebook 動態", note: "滑 Facebook 首頁時看到" },
        { value: "instagram_feed", label: "Instagram 動態", note: "滑 Instagram 首頁時看到" },
      ],
      countries: [{ value: "TW", label: "台灣", note: "整個台灣都看得到" }, { value: "HK", label: "香港", note: "整個香港都看得到" }],
      pixels: [{ id: "px_4821", name: "晨光官網像素" }],
      pixels_error: null,
      placement_modes: [
        { value: "auto", label: "自動", note: "讓 Meta 自己決定廣告出現在 FB、IG 哪裡" },
        { value: "manual", label: "手動", note: "你自己挑廣告要出現在哪裡" },
      ],
      genders: [{ value: "all", label: "不限", note: "男女都給看" }, { value: "female", label: "女性", note: "只給女性看" }],
      ages: [18, 21, 25, 30, 35, 45, 54, 55, 65],
      field_notes: { audience: "要給哪些人看：年齡、性別、地區", pixel_id: "官網上記錄誰買了東西的追蹤碼；選錯就看不到成效", utm: "加在網址後面，讓官網後台分得出是哪個廣告帶來的" },
    },
    ...over,
  };
}

const campaign = { id: "cmp_fall", status: "ready" as const, manual_handoff: null };

function renderCard(locked = false) {
  const onSaved = vi.fn();
  const onBlockerChange = vi.fn();
  render(<LaunchSettingsCard brandId="brd_1" campaign={campaign} locked={locked} onSaved={onSaved}
    onCampaignSaved={vi.fn()} onBlockerChange={onBlockerChange} />);
  return { onSaved, onBlockerChange };
}
const lastBlocker = (fn: ReturnType<typeof vi.fn>) => fn.mock.calls.at(-1)?.[0];
const fieldOf = (label: string) => screen.getByText(label, { selector: "label" }).closest("[data-slot=setting-field]") as HTMLElement;

beforeEach(() => { vi.clearAllMocks(); });

describe("LaunchSettingsCard（list stage）", () => {
  it("每個欄位一行白話說明，建議值預先選好並標「建議」；都照建議時可以核准", async () => {
    vi.mocked(getLaunchSettings).mockResolvedValue(view());
    const { onBlockerChange } = renderCard();
    expect(await screen.findByText("每個廣告組都用這組・都是建議值")).toBeTruthy();
    expect(within(fieldOf("優化事件")).getByText("建議")).toBeTruthy();
    expect(within(fieldOf("優化事件")).getByText("Meta 要幫你找哪種人：會買的人")).toBeTruthy();
    expect((screen.getByLabelText(/像素/) as HTMLSelectElement).value).toBe("px_4821");
    expect(screen.getByText("都照建議就能送出；不確定的不用改")).toBeTruthy();
    expect(screen.getByRole("button", { name: /進階設定/ }).getAttribute("aria-expanded")).toBe("false");
    await waitFor(() => expect(lastBlocker(onBlockerChange)).toBeNull());
  });

  it("像素清單讀不到：顯示原因，改成手填像素 ID，不預選也不猜", async () => {
    vi.mocked(getLaunchSettings).mockResolvedValue(view({
      options: { ...view().options, pixels: null, pixels_error: "像素的讀取權限沒開，系統讀不到像素清單；請到廣告平台看一眼。" },
      recommended: { ...REC, pixel_id: null },
    }, { pixel_id: null }));
    vi.mocked(saveLaunchSettings).mockImplementation(async (_b, _c, values) => view({ recommended: { ...REC, pixel_id: null }, edited: ["pixel_id"] }, values));
    const user = userEvent.setup();
    renderCard();
    expect(await screen.findByText(/像素的讀取權限沒開/)).toBeTruthy();
    const input = screen.getByPlaceholderText("貼上像素 ID") as HTMLInputElement;
    expect(input.value).toBe("");
    expect(screen.queryByRole("combobox", { name: /像素/ })).toBeNull();
    await user.type(input, "1234567890");
    await waitFor(() => expect(saveLaunchSettings).toHaveBeenCalled(), { timeout: 2000 });
    expect(vi.mocked(saveLaunchSettings).mock.calls.at(-1)?.[2].pixel_id).toBe("1234567890");
  });

  it("UTM 有空格：即時顯示格式不對，標題與核准提示都擋下", async () => {
    vi.mocked(getLaunchSettings).mockResolvedValue(view());
    vi.mocked(saveLaunchSettings).mockImplementation(async (_b, _c, values) => view({
      edited: ["utm"], errors: [{ field: "utm", code: "utm_format", message: "格式不對：要像 utm_source=來源&utm_campaign=名稱，不能有空格" }],
    }, values));
    const user = userEvent.setup();
    const { onBlockerChange } = renderCard();
    await user.click(await screen.findByRole("button", { name: /進階設定/ }));
    const utm = screen.getByLabelText(/UTM 追蹤參數/) as HTMLInputElement;
    expect(screen.getByText("✓ 格式正確")).toBeTruthy();
    await user.type(utm, " x");
    expect(screen.getByText(/格式不對：要像 utm_source=來源/)).toBeTruthy();
    expect(screen.getByText("UTM 格式不對", { selector: "span" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /進階設定・UTM 格式不對/ })).toBeTruthy();
    expect(lastBlocker(onBlockerChange)).toBe("UTM 格式不對，先在「投放設定」改好");
    expect(within(fieldOf("UTM 追蹤參數")).getByText("你改的")).toBeTruthy();
  });

  it("手動版位一個都沒勾：送出手動、空清單，顯示「手動版位至少選一個」並擋核准", async () => {
    vi.mocked(getLaunchSettings).mockResolvedValue(view());
    vi.mocked(saveLaunchSettings).mockImplementation(async (_b, _c, values) => view({
      edited: ["placement"], errors: [{ field: "placement.positions", code: "positions_empty", message: "手動版位至少選一個" }],
    }, values));
    const user = userEvent.setup();
    const { onBlockerChange, onSaved } = renderCard();
    await user.click(await screen.findByRole("button", { name: "手動" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(vi.mocked(saveLaunchSettings).mock.calls[0][2].placement).toEqual({ mode: "manual", positions: [] });
    expect(screen.getByRole("checkbox", { name: "Facebook 動態" })).toBeTruthy();
    expect(screen.getAllByText("手動版位至少選一個").length).toBeGreaterThan(0);
    expect(within(fieldOf("版位")).getByText("你改的")).toBeTruthy();
    await waitFor(() => expect(lastBlocker(onBlockerChange)).toBe("手動版位至少選一個，先在「投放設定」改好"));
  });

  it("儲存失敗：改的內容留在畫面上，顯示原因與重試；重試成功才放行", async () => {
    vi.mocked(getLaunchSettings).mockResolvedValue(view());
    vi.mocked(saveLaunchSettings).mockRejectedValueOnce(new Error("連線中斷"));
    const user = userEvent.setup();
    const { onBlockerChange } = renderCard();
    const bid = await screen.findByLabelText(/出價方式/) as HTMLSelectElement;
    await user.selectOptions(bid, "cost_cap");
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText(/儲存失敗：連線中斷/)).toBeTruthy();
    expect(bid.value).toBe("cost_cap");
    expect(within(fieldOf("出價方式")).getByText("你改的")).toBeTruthy();
    expect(screen.getByText("你改了 1 項・每個廣告組都用這組")).toBeTruthy();
    expect(lastBlocker(onBlockerChange)).toBe("投放設定還沒存好，先按重試");

    vi.mocked(saveLaunchSettings).mockImplementation(async (_b, _c, values) => view({ edited: ["bid_strategy"] }, values));
    await user.click(screen.getByRole("button", { name: "重試" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect(vi.mocked(saveLaunchSettings).mock.calls.at(-1)?.[2].bid_strategy).toBe("cost_cap");
    await waitFor(() => expect(lastBlocker(onBlockerChange)).toBeNull());
  });

  it("核准後唯讀：顯示原型那句話，欄位都不能改，沒有「都照建議」那行", async () => {
    vi.mocked(getLaunchSettings).mockResolvedValue(view({}, { bid_strategy: "cost_cap" }));
    renderCard(true);
    expect(await screen.findByText("核准後已定下來；想改，改完再核准一次")).toBeTruthy();
    const bid = screen.getByLabelText(/出價方式/) as HTMLSelectElement;
    expect(bid.matches(":disabled")).toBe(true);
    expect((screen.getByRole("button", { name: "自動（建議）" }) as HTMLButtonElement).matches(":disabled")).toBe(true);
    expect(screen.queryByText("都照建議就能送出；不確定的不用改")).toBeNull();
  });

  it("讀不到投放設定：顯示讀取失敗與重試，不當成空白，核准擋下", async () => {
    vi.mocked(getLaunchSettings).mockRejectedValueOnce(new Error("伺服器沒有回應"));
    const { onBlockerChange } = renderCard();
    expect(await screen.findByText("讀取失敗")).toBeTruthy();
    expect(screen.getByText(/伺服器沒有回應/)).toBeTruthy();
    expect(lastBlocker(onBlockerChange)).toBe("投放設定讀不到，先按重試");
    vi.mocked(getLaunchSettings).mockResolvedValue(view());
    await userEvent.setup().click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByText("每個廣告組都用這組・都是建議值")).toBeTruthy();
  });
});

describe("LaunchSettingsCopy（platform stage）", () => {
  it("每一項設定都有複製", async () => {
    vi.mocked(getLaunchSettings).mockResolvedValue(view({}, { audience: { age_min: 25, age_max: 54, gender: "all", countries: ["TW"] } }));
    render(<LaunchSettingsCopy brandId="brd_1" campaignId="cmp_fall" />);
    expect(await screen.findByText("25–54 歲")).toBeTruthy();
    expect(screen.getByText("晨光官網像素（px_4821）")).toBeTruthy();
    for (const name of ["優化事件", "出價方式", "版位", "年齡", "性別", "地區", "像素", "UTM"]) {
      expect(screen.getByRole("button", { name: `複製${name}` })).toBeTruthy();
    }
  });
  it("讀取失敗顯示重試，不是空的設定", async () => {
    vi.mocked(getLaunchSettings).mockRejectedValueOnce(new Error("逾時"));
    render(<LaunchSettingsCopy brandId="brd_1" campaignId="cmp_fall" />);
    expect(await screen.findByText("讀取失敗")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "複製優化事件" })).toBeNull();
  });
});

describe("SettingsReadback（verify stage）", () => {
  const readback = (pixelState: "unreadable" | "self_confirmed" = "unreadable"): Readback => ({
    read_at: "2026-09-23T02:52:00Z",
    fields: [
      { key: "optimization_event", label: "優化事件", expected_label: "購買", observed_label: "購買", state: "match", reason: null },
      { key: "age", label: "年齡", expected_label: "25–54 歲", observed_label: "18–65+ 歲", state: "differ", reason: null },
      { key: "pixel_id", label: "像素", expected_label: "晨光官網像素（px_4821）", observed_label: null, state: pixelState, reason: "像素的讀取權限沒開，系統看不到；請到 Meta 看一眼" },
      { key: "utm", label: "UTM", expected_label: REC.utm, observed_label: REC.utm, state: "match", reason: null },
    ],
  });

  it("不一樣列出平台上的值；讀不到可按「我看過了，一樣」；有不一樣時主要動作是回平台改", async () => {
    const workspace = { settings_readback: readback("self_confirmed") } as HandoffWorkspace;
    vi.mocked(confirmLaunchSetting).mockResolvedValue(workspace as HandoffWorkspace & { settings_readback: Readback });
    const onConfirmed = vi.fn();
    const onBack = vi.fn();
    const user = userEvent.setup();
    render(<SettingsReadback brandId="brd_1" campaignId="cmp_fall" readback={readback()} platform="Meta" onConfirmed={onConfirmed} onBackToPlatform={onBack} />);
    expect(screen.getByText("1 項投放設定和核准的不一樣")).toBeTruthy();
    expect(screen.getByText(/其他 2 項對上了・1 項讀不到/)).toBeTruthy();
    const age = screen.getByText("年齡").closest("[data-slot=readback-row]") as HTMLElement;
    expect(age.textContent).toContain("Meta 上是 18–65+ 歲，這裡是 25–54 歲");
    const pixel = screen.getByText("像素").closest("[data-slot=readback-row]") as HTMLElement;
    expect(within(pixel).getByText(/讀取權限沒開/)).toBeTruthy();
    await user.click(within(pixel).getByRole("button", { name: "我看過了，一樣" }));
    expect(confirmLaunchSetting).toHaveBeenCalledWith("brd_1", "cmp_fall", "pixel_id");
    await waitFor(() => expect(onConfirmed).toHaveBeenCalledWith(workspace));
    await user.click(screen.getByRole("button", { name: "回平台改 →" }));
    expect(onBack).toHaveBeenCalled();
  });

  it("你確認過的讀不到算對上；全部一樣時沒有回平台改", () => {
    const all = readback("self_confirmed");
    all.fields = all.fields.filter((f) => f.state !== "differ");
    render(<SettingsReadback brandId="brd_1" campaignId="cmp_fall" readback={all} platform="Meta" onConfirmed={vi.fn()} onBackToPlatform={vi.fn()} />);
    expect(screen.getByText("投放設定都和核准的一樣")).toBeTruthy();
    expect(screen.getByText("你確認一樣")).toBeTruthy();
    expect(screen.getByText("對上了 3")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "回平台改 →" })).toBeNull();
    expect(screen.queryByRole("button", { name: "我看過了，一樣" })).toBeNull();
  });

  it("確認失敗顯示原因，列維持讀不到", async () => {
    vi.mocked(confirmLaunchSetting).mockRejectedValueOnce(new Error("只有讀不到的投放設定可以由你確認一樣。"));
    const onConfirmed = vi.fn();
    render(<SettingsReadback brandId="brd_1" campaignId="cmp_fall" readback={readback()} platform="Meta" onConfirmed={onConfirmed} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "我看過了，一樣" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(onConfirmed).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "我看過了，一樣" })).toBeTruthy();
  });
});
