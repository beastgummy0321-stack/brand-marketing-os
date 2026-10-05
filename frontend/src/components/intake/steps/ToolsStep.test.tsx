vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "test-org" }) }));
/** frontend/src/components/intake/steps/ToolsStep.test.tsx — brand onboarding #/b6 接上工具 (F42-I11): connector rows and
 * states from a registry fixture shaped like `app/intake/connector_catalogue.json`, Meta's inline token → account → bind
 * panel, the conversion goal saved on change, and the bar. All API calls are fakes. */
import { cleanup, act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MetaConnectPanel } from "./MetaConnectPanel";
import { ToolsStep } from "./ToolsStep";
import { saveConversionGoal } from "@/lib/intakeApi";
import { fetchOnboardingTools, type Connector, type OnboardingTools } from "@/lib/intakeOnboardingApi";
import {
  bindMetaAccount,
  connectMetaToken,
  fetchMetaAccounts,
  fetchMetaBackfillStatus,
  startMetaBackfill,
  type MetaBackfillStatus,
} from "@/lib/metaApi";
import { BRAND_STEPS, type StepNav } from "../OnboardingStepHead";

vi.mock("@/lib/intakeApi", () => ({ saveConversionGoal: vi.fn() }));
vi.mock("@/lib/intakeOnboardingApi", () => ({ fetchOnboardingTools: vi.fn() }));
vi.mock("@/lib/metaApi", () => ({
  fetchMetaAccounts: vi.fn(),
  bindMetaAccount: vi.fn(),
  connectMetaToken: vi.fn(),
  fetchMetaBackfillStatus: vi.fn(),
  startMetaBackfill: vi.fn(),
}));

const row = (key: string, group: string, label: string, icon: string, reads: string, state: Connector["state"], link: string | null = null): Connector => ({
  key, group, label, icon, reads, state, note: state === "seat" ? "即將開放" : "", link,
});

const REGISTRY: Connector[] = [
  row("meta", "廣告平台", "Meta 廣告", "M", "花費、曝光、點擊、購買", "available"),
  row("google", "廣告平台", "Google Ads", "G", "花費、搜尋字詞、轉換", "seat"),
  row("tiktok", "廣告平台", "TikTok 廣告", "T", "花費、觀看、轉換", "seat"),
  row("ga4", "網站與流量", "Google Analytics 4", "GA", "網站流量、轉換路徑、加入購物車", "seat"),
  row("gsc", "網站與流量", "Search Console（SEO）", "SC", "自然搜尋字詞、排名、點擊", "seat"),
  row("shop", "商店與訂單", "購物平台（SHOPLINE、Shopify、91APP、CYBERBIZ…）", "店", "訂單、退款、商品、會員", "seat"),
  row("csv", "商店與訂單", "上傳訂單檔", "CSV", "訂單、退款", "available", "/brands/brd_x/orders"),
  row("mcp", "給 AI 用的接口", "MCP 伺服器", "MCP", "讓 AI 直接查你其他系統的資料（例如 CRM、客服紀錄）", "seat"),
  row("api", "給 AI 用的接口", "自訂 API", "API", "照你提供的網址與欄位讀資料", "seat"),
];

const GOALS = [{ key: "purchase", label: "購買" }, { key: "lead", label: "留資料" }, { key: "booking", label: "預約" }];

function tools(over: Partial<OnboardingTools> = {}): OnboardingTools {
  return { connectors: REGISTRY, conversion_goal: "purchase", conversion_goal_options: GOALS, ...over };
}

const CONNECTED: Connector[] = REGISTRY.map((c) => (c.key === "meta" ? { ...c, state: "connected", note: "已接上：Beast Gummy 主帳戶" } : c));

const NAV: StepNav = { crumb: [{ label: "品牌建檔", strong: true }], steps: BRAND_STEPS, current: 6 };

function renderStep(onNext = vi.fn(), back = vi.fn()) {
  render(
    <MemoryRouter>
      <ToolsStep brandId="brd_x" nav={NAV} back={{ label: "素材", onClick: back }} onNext={onNext} />
    </MemoryRouter>,
  );
  return { onNext, back };
}

const connectorRow = (name: string) => screen.getByText(name).closest("[data-slot=connector]") as HTMLElement;

beforeEach(() => {
  sessionStorage.clear();
  vi.mocked(fetchOnboardingTools).mockReset().mockResolvedValue(tools());
  vi.mocked(saveConversionGoal).mockReset().mockResolvedValue(undefined);
  vi.mocked(fetchMetaAccounts).mockReset();
  vi.mocked(bindMetaAccount).mockReset().mockResolvedValue(undefined);
  vi.mocked(connectMetaToken).mockReset();
  vi.mocked(startMetaBackfill).mockReset().mockResolvedValue({} as never);
  vi.mocked(fetchMetaBackfillStatus).mockReset().mockResolvedValue(backfillStatus({}));
});

afterEach(() => {
  sessionStorage.clear();
  vi.useRealTimers();
});

function backfillStatus(over: Partial<MetaBackfillStatus>): MetaBackfillStatus {
  return { running: false, earliest_spend_date: null, latest_spend_date: null, ad_rows: 0, outcome: null, ...over };
}

it("shows one card per connector group, each row saying what it reads and its state", async () => {
  renderStep();

  expect(await screen.findByRole("heading", { level: 2, name: "廣告平台" })).toBeTruthy();
  expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(["廣告平台", "網站與流量", "商店與訂單", "給 AI 用的接口"]);
  expect(screen.getByText("接上後系統能讀：花費、曝光、點擊、購買")).toBeTruthy();
  expect(within(connectorRow("Meta 廣告")).getByRole("button", { name: "接上" })).toBeTruthy();
  expect(within(connectorRow("上傳訂單檔")).getByRole("link", { name: "接上" }).getAttribute("href")).toBe("/brands/brd_x/orders");
  expect(screen.getAllByText("即將開放")).toHaveLength(7);
  expect(within(connectorRow("Google Ads")).queryByRole("button")).toBeNull();
  expect(screen.queryByText(/已接上/)).toBeNull();
});

it("shows Meta connected with its account and offers 再接一個帳戶 (multi-account binding adds, never replaces)", async () => {
  vi.mocked(fetchOnboardingTools).mockResolvedValue(tools({ connectors: CONNECTED }));
  renderStep();

  expect(await screen.findByText("✓ 已接上：Beast Gummy 主帳戶")).toBeTruthy();
  expect(within(connectorRow("Meta 廣告")).getByRole("button", { name: "再接一個帳戶" })).toBeTruthy();
});

it("binds a Meta account from the inline panel: token → picking the account assigns it → backfill, then the row re-reads", async () => {
  vi.mocked(fetchMetaAccounts).mockResolvedValue({ token_tail: null, accounts: [] });
  vi.mocked(connectMetaToken).mockResolvedValue({
    token_tail: "abcd",
    accounts: [{ id: "act_1", account_id: "1001", name: "主帳戶", currency: "TWD", connected_at: "", bound_brand_ids: [] }],
  });
  renderStep();

  await userEvent.click(await screen.findByRole("button", { name: "接上" }));
  await userEvent.click(await screen.findByRole("button", { name: "讀取帳戶" }));
  expect(screen.getByText("請貼上 Meta 存取權杖。")).toBeTruthy();
  await userEvent.type(screen.getByPlaceholderText("貼上 Meta 存取權杖"), "EAAB-token");
  await userEvent.click(screen.getByRole("button", { name: "讀取帳戶" }));
  expect(connectMetaToken).toHaveBeenCalledWith("EAAB-token");

  const account = await screen.findByRole("radio", { name: /主帳戶/ });
  expect(screen.queryByRole("button", { name: "指定給這個品牌" })).toBeNull();
  vi.mocked(fetchOnboardingTools).mockResolvedValue(tools({ connectors: CONNECTED }));
  await userEvent.click(account);

  expect(bindMetaAccount).toHaveBeenCalledWith("brd_x", "act_1");
  expect(startMetaBackfill).toHaveBeenCalledWith("brd_x");
  expect(await screen.findByText("✓ 已接上：Beast Gummy 主帳戶")).toBeTruthy();
});

it("再接一個帳戶 opens the panel with the bound account marked and no token field", async () => {
  vi.mocked(fetchOnboardingTools).mockResolvedValue(tools({ connectors: CONNECTED }));
  vi.mocked(fetchMetaAccounts).mockResolvedValue({
    token_tail: "abcd",
    accounts: [
      { id: "act_1", account_id: "1001", name: "主帳戶", currency: "TWD", connected_at: "", bound_brand_ids: ["brd_x"] },
      { id: "act_2", account_id: "1002", name: "副帳戶", currency: "TWD", connected_at: "", bound_brand_ids: [] },
    ],
  });
  renderStep();

  await userEvent.click(await screen.findByRole("button", { name: "再接一個帳戶" }));
  expect(await screen.findByText("已指定給這個品牌")).toBeTruthy();
  expect(screen.getByRole("radio", { name: /主帳戶/ })).toHaveProperty("disabled", true);
  expect(screen.queryByPlaceholderText("貼上 Meta 存取權杖")).toBeNull();
  await userEvent.click(screen.getByRole("radio", { name: /副帳戶/ }));
  expect(bindMetaAccount).toHaveBeenCalledWith("brd_x", "act_2");
});

it("picking an account shows 指定中… on that row while the assign runs; a failure shows the error and leaves it unpicked", async () => {
  vi.mocked(fetchMetaAccounts).mockResolvedValue({
    token_tail: "abcd",
    accounts: [{ id: "act_2", account_id: "1002", name: "副帳戶", currency: "TWD", connected_at: "", bound_brand_ids: [] }],
  });
  let fail: (e: Error) => void = () => undefined;
  vi.mocked(bindMetaAccount).mockReturnValue(new Promise<void>((_, reject) => { fail = reject; }));
  renderStep();

  await userEvent.click(await screen.findByRole("button", { name: "接上" }));
  expect(await screen.findByText("權杖已存，還沒指定給這個品牌。")).toBeTruthy();
  const radio = await screen.findByRole("radio", { name: /副帳戶/ });
  await userEvent.click(radio);
  expect(bindMetaAccount).toHaveBeenCalledTimes(1);
  expect(within(radio.closest("label") as HTMLElement).getByText("指定中…")).toBeTruthy();
  expect(radio).toHaveProperty("checked", true);
  expect(radio).toHaveProperty("disabled", true);

  fail(new Error("綁定失敗（狀態碼 500）"));
  expect(await screen.findByText("綁定失敗（狀態碼 500）")).toBeTruthy();
  expect(screen.queryByText("指定中…")).toBeNull();
  expect(radio).toHaveProperty("checked", false);
  expect(radio).toHaveProperty("disabled", false);
  expect(startMetaBackfill).not.toHaveBeenCalled();
  expect(screen.getByText("權杖已存，還沒指定給這個品牌。")).toBeTruthy();
});

it("a token that lists no account or hits a Meta outage keeps the token input with the server's sentence (drill-10 R3/R4)", async () => {
  vi.mocked(fetchMetaAccounts).mockResolvedValue({ token_tail: null, accounts: [] });
  vi.mocked(connectMetaToken)
    .mockRejectedValueOnce(new Error("這把權杖讀不到任何廣告帳戶：可能填錯，或這個帳號沒有廣告帳戶的權限。"))
    .mockRejectedValueOnce(new Error("Meta 暫時讀不到（代碼 2），這把權杖還沒驗證、沒有存。請稍後再試。"));
  renderStep();

  await userEvent.click(await screen.findByRole("button", { name: "接上" }));
  const input = await screen.findByPlaceholderText("貼上 Meta 存取權杖");
  await userEvent.type(input, "EAAB-wrong");
  await userEvent.click(screen.getByRole("button", { name: "讀取帳戶" }));
  expect(await screen.findByText("這把權杖讀不到任何廣告帳戶：可能填錯，或這個帳號沒有廣告帳戶的權限。")).toBeTruthy();
  expect(screen.getByPlaceholderText("貼上 Meta 存取權杖")).toHaveProperty("value", "EAAB-wrong");
  expect(screen.queryByText(/權杖已存/)).toBeNull();

  await userEvent.click(screen.getByRole("button", { name: "讀取帳戶" }));
  expect(await screen.findByText(/Meta 暫時讀不到（代碼 2）/)).toBeTruthy();
  expect(screen.getByPlaceholderText("貼上 Meta 存取權杖")).toBeTruthy();
});

it("a stored token offers 換一把權杖, and one that lists no account shows the token input at once", async () => {
  vi.mocked(fetchMetaAccounts).mockResolvedValue({
    token_tail: "abcd",
    accounts: [{ id: "act_2", account_id: "1002", name: "副帳戶", currency: "TWD", connected_at: "", bound_brand_ids: [] }],
  });
  renderStep();
  await userEvent.click(await screen.findByRole("button", { name: "接上" }));
  expect(screen.queryByPlaceholderText("貼上 Meta 存取權杖")).toBeNull();
  await userEvent.click(await screen.findByRole("button", { name: "換一把權杖" }));
  expect(screen.getByPlaceholderText("貼上 Meta 存取權杖")).toBeTruthy();
});

it("a stored token with no account (stored before F47) shows the token input, not 權杖已存", async () => {
  vi.mocked(fetchMetaAccounts).mockResolvedValue({ token_tail: "abcd", accounts: [] });
  renderStep();
  await userEvent.click(await screen.findByRole("button", { name: "接上" }));
  expect(await screen.findByPlaceholderText("貼上 Meta 存取權杖")).toBeTruthy();
  expect(screen.queryByText(/權杖已存/)).toBeNull();
  expect(screen.queryByText("這把權杖沒有列出任何帳戶。")).toBeNull();
});

it("saves the conversion goal on change", async () => {
  renderStep();

  const group = await screen.findByRole("radiogroup", { name: "成效目標" });
  expect(within(group).getByRole("radio", { name: "購買" }).getAttribute("aria-checked")).toBe("true");
  await userEvent.click(within(group).getByRole("radio", { name: "留資料" }));

  expect(saveConversionGoal).toHaveBeenCalledWith("brd_x", "lead");
  expect(await screen.findByText("已儲存")).toBeTruthy();
  await waitFor(() => expect(within(group).getByRole("radio", { name: "留資料" }).getAttribute("aria-checked")).toBe("true"));
});

it("keeps the unsaved choice and says so when saving fails", async () => {
  vi.mocked(saveConversionGoal).mockRejectedValue(new Error("儲存失敗"));
  renderStep();

  const group = await screen.findByRole("radiogroup", { name: "成效目標" });
  await userEvent.click(within(group).getByRole("radio", { name: "預約" }));

  expect(await screen.findByText("儲存失敗")).toBeTruthy();
  expect(within(group).getByRole("radio", { name: "預約" }).getAttribute("aria-checked")).toBe("true");
  expect(screen.getByText("尚未儲存，重新選取可再試")).toBeTruthy();
});

it("picks no goal when none is saved yet", async () => {
  vi.mocked(fetchOnboardingTools).mockResolvedValue(tools({ conversion_goal: null }));
  renderStep();

  const group = await screen.findByRole("radiogroup", { name: "成效目標" });
  expect(within(group).queryByRole("radio", { checked: true })).toBeNull();
});

it("bar: back to 素材, the reconnect hint, and 完成品牌建檔 without connecting anything", async () => {
  const { onNext, back } = renderStep();

  await screen.findByRole("heading", { level: 2, name: "廣告平台" });
  expect(screen.getByText("之後回到「品牌資料」或投放中心的資料連線再接")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "← 素材" }));
  expect(back).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole("button", { name: "完成品牌建檔 →" }));
  expect(onNext).toHaveBeenCalledTimes(1);
  expect(bindMetaAccount).not.toHaveBeenCalled();
});

it("a failed read offers 重新載入 and still lets the user finish", async () => {
  vi.mocked(fetchOnboardingTools).mockRejectedValueOnce(new Error("讀取失敗了"));
  const { onNext } = renderStep();

  expect(await screen.findByText("讀取失敗了")).toBeTruthy();
  expect(screen.queryByText(/已接上/)).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "重新載入" }));
  expect(await screen.findByRole("heading", { level: 2, name: "廣告平台" })).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "完成品牌建檔 →" }));
  expect(onNext).toHaveBeenCalledTimes(1);
});

// F50-I16 (Contract J, R7 A12): the panel's backfill line reads the stored outcome (`GET …/backfill`), also when it opens
// on a brand already bound (a reload).
describe("MetaConnectPanel backfill outcome", () => {
  const BOUND = {
    token_tail: "abcd",
    accounts: [{ id: "act_1", account_id: "1001", name: "主帳戶", currency: "TWD", connected_at: "", bound_brand_ids: ["brd_x"] }],
  };
  const UNBOUND = {
    token_tail: "abcd",
    accounts: [{ id: "act_1", account_id: "1001", name: "主帳戶", currency: "TWD", connected_at: "", bound_brand_ids: [] }],
  };

  it("empty: a bound brand's panel says the pull finished with no ad data", async () => {
    vi.mocked(fetchMetaAccounts).mockResolvedValue(BOUND);
    vi.mocked(fetchMetaBackfillStatus).mockResolvedValue(backfillStatus({
      outcome: { state: "empty", code: "no_rows", text: "2023-09-05 ~ 2026-10-05 這段期間 Meta 沒有回任何成效資料。", finished_at: "2026-10-05T03:00:00+00:00" },
    }));
    render(<MetaConnectPanel brandId="brd_x" onBound={vi.fn()} />);
    expect(await screen.findByText("拉完了：這段期間沒有廣告資料")).toBeTruthy();
    expect(screen.getByText("2023-09-05 ~ 2026-10-05 這段期間 Meta 沒有回任何成效資料。")).toBeTruthy();
  });

  it("failed: shows the served reason; 再試一次 starts the pull again", async () => {
    vi.mocked(fetchMetaAccounts).mockResolvedValue(BOUND);
    vi.mocked(fetchMetaBackfillStatus).mockResolvedValueOnce(backfillStatus({
      outcome: { state: "failed", code: "account_failed", text: "主帳戶（act_1001）：權杖過期，請重新接上 Meta。", finished_at: "2026-10-05T03:00:00+00:00" },
    }));
    render(<MetaConnectPanel brandId="brd_x" onBound={vi.fn()} />);
    expect(await screen.findByText("主帳戶（act_1001）：權杖過期，請重新接上 Meta。")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "再試一次" }));
    expect(startMetaBackfill).toHaveBeenCalledWith("brd_x");
    await waitFor(() => expect(screen.queryByText("主帳戶（act_1001）：權杖過期，請重新接上 Meta。")).toBeNull());
  });

  it("done after binding: the running line, then 拉完了 with the stored range", async () => {
    vi.mocked(fetchMetaAccounts).mockResolvedValue(UNBOUND);
    vi.mocked(fetchMetaBackfillStatus).mockResolvedValue(backfillStatus({
      earliest_spend_date: "2023-09-01", latest_spend_date: "2026-10-04", ad_rows: 120,
      outcome: { state: "done", code: null, text: null, finished_at: "2026-10-05T03:00:00+00:00" },
    }));
    render(<MetaConnectPanel brandId="brd_x" onBound={vi.fn()} />);
    expect(fetchMetaBackfillStatus).not.toHaveBeenCalled();
    await userEvent.click(await screen.findByRole("radio", { name: /主帳戶/ }));
    expect(await screen.findByText("拉完了：2023/09/01～2026/10/04，共 120 筆廣告每日數字")).toBeTruthy();
  });

  it("a failed status read shows the read error instead of nothing", async () => {
    vi.mocked(fetchMetaAccounts).mockResolvedValue(BOUND);
    vi.mocked(fetchMetaBackfillStatus).mockRejectedValue(new Error("讀取失敗（狀態碼 500）"));
    render(<MetaConnectPanel brandId="brd_x" onBound={vi.fn()} />);
    expect(await screen.findByText("讀取失敗（狀態碼 500）")).toBeTruthy();
    expect(screen.getByRole("button", { name: "重新載入" })).toBeTruthy();
  });

  it("polls while running and stops polling on unmount", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(fetchMetaAccounts).mockResolvedValue(BOUND);
    vi.mocked(fetchMetaBackfillStatus).mockResolvedValue(backfillStatus({
      running: true, outcome: { state: "running", code: null, text: null, finished_at: null },
    }));
    const { unmount } = render(<MetaConnectPanel brandId="brd_x" onBound={vi.fn()} />);
    expect(await screen.findByText(/正在把過去的花費拉進來/)).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    const calls = vi.mocked(fetchMetaBackfillStatus).mock.calls.length;
    expect(calls).toBeGreaterThanOrEqual(2);
    unmount();
    await vi.advanceTimersByTimeAsync(20000);
    expect(vi.mocked(fetchMetaBackfillStatus).mock.calls.length).toBe(calls);
  });
});


it("restores a failed goal choice without reporting it saved", async () => {
  vi.mocked(saveConversionGoal).mockRejectedValue(new Error("儲存失敗"));
  renderStep();
  await userEvent.click(await screen.findByRole("radio", {name:"預約"}));
  await screen.findByText("儲存失敗");
  cleanup();
  renderStep();
  await waitFor(() => expect(screen.getByRole("radio", {name:"預約"}).getAttribute("aria-checked")).toBe("true"));
  expect(screen.queryByText("已儲存")).toBeNull();
  expect(screen.getByText("尚未儲存，重新選取可再試")).toBeTruthy();
});
