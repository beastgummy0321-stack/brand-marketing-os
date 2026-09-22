/** frontend/src/components/ads/PublishPage.test.tsx — 發布頁保留必要的手動交接與預算確認，
 * 一般入口只提供 API 回傳的手動準備；直接指定 simulated adapter 的隔離演練仍可使用。
 * 測試也涵蓋素材警告、平台清單、Meta-only 配對邊界，以及選填交接資料收合。 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";

import type { AssetReadinessSummary, CampaignDetail, DeliveryGroupRow } from "@/lib/adsApi";
import { bindCampaign, getCampaign, getPublish, publishCampaign } from "@/lib/adsApi";
import { fetchChannels } from "@/lib/adsLaunchApi";
import { PublishPage } from "./PublishPage";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return {
    ...actual,
    getPublish: vi.fn(),
    publishCampaign: vi.fn(),
    getCampaign: vi.fn(),
    bindCampaign: vi.fn(),
  };
});

vi.mock("./ManualHandoffPanel", () => ({ ManualHandoffPanel: () => <p>逐項平台核對</p> }));
vi.mock("@/lib/adsLaunchApi", () => ({ fetchChannels: vi.fn() }));

function group(channel_key = "meta"): DeliveryGroupRow {
  return {
    id: "grp_1", campaign_id: "cmp_1", channel_key, name: "投放組", role: "new", daily_budget: 1000,
    start_date: null, end_date: null, ads: [], external_id: null, external_name: null,
    external_status: null, local_state: "unbound", bound_at: null,
  };
}

function campaign(asset_readiness: AssetReadinessSummary): CampaignDetail {
  return {
    id: "cmp_1",
    name: "測試 Campaign",
    goal_text: "想在雙十一衝一波業績",
    objective: "增加新客購買",
    success_metric: "cpa",
    success_target: null,
    success_basis: null,
    start_date: "2026-01-01",
    end_date: "2026-01-15",
    status: "ready",
    budget_planned: null,
    budget_scenario: null,
    budget_basis_json: {},
    budget_total: null,
    context_json: {},
    constraints_json: {},
    verdict: null,
    verdict_json: {},
    closed_at: null,
    created_by: null,
    created_at: "2026-01-01T00:00:00Z",
    groups: [],
    actions: [],
    outcome: { spend: 0, purchases: 0, revenue: 0 },
    asset_readiness,
    judgment: { tone: "neutral", text: "投放中", detail: "還沒有花費資料" },
    action_lines: [],
    external_id: null,
    external_name: null,
    external_status: null,
    local_state: "unbound",
    bound_at: null,
  };
}

function renderPage(c: CampaignDetail, adapter: "auto_meta" | "manual" | "simulated") {
  const onChangeAdapter = vi.fn();
  const onGoToAssets = vi.fn();
  const view = render(
    <PublishPage
      brandId="brd_1"
      campaign={c}
      adapter={adapter}
      onCampaignChange={vi.fn()}
      onClose={vi.fn()}
      onViewPerformance={vi.fn()}
      onChangeAdapter={onChangeAdapter}
      onGoToAssets={onGoToAssets}
    />,
  );
  return { onChangeAdapter, onGoToAssets, ...view };
}

describe("PublishPage（F06-I04）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getPublish).mockImplementation((_brandId, _campaignId, adapter = "manual") =>
      Promise.resolve({
        adapters: [
          { key: "manual", label: "手動發布" },
          { key: "auto_meta", label: "自動發布（未接上）" },
          { key: "simulated", label: "模擬發布（演練用）" },
        ],
        adapter,
        describe: { adapter, message: "自動發布未接上", checklist: [] },
      }),
    );
    vi.mocked(fetchChannels).mockResolvedValue([
      { key: "meta", label: "Meta", connected: true, state_text: "已接上" },
    ]);
    vi.mocked(publishCampaign).mockResolvedValue({ adapter: "manual", message: null, checklist: [] });
    vi.mocked(getCampaign).mockResolvedValue(campaign({ ready_count: 0, total: 0 }));
    vi.mocked(bindCampaign).mockResolvedValue({ message: null, campaign: campaign({ ready_count: 0, total: 0 }) });
  });

  it("auto_meta、3/3 就位：只保留 API 回傳的手動入口，不顯示一般模擬選項", async () => {
    const user = userEvent.setup();
    const { onChangeAdapter } = renderPage(campaign({ ready_count: 3, total: 3 }), "auto_meta");

    expect(await screen.findByText("自動發布未接上")).toBeTruthy();
    expect(screen.queryByText(/則廣告沒有素材/)).toBeNull();

    await user.click(screen.getByRole("button", { name: "手動發布準備" }));
    expect(onChangeAdapter).toHaveBeenCalledWith("manual");
    expect(screen.queryByRole("button", { name: /模擬發布/ })).toBeNull();
  });

  it("auto_meta、1/3 就位：印「還有 2 則廣告沒有素材」，「回到素材」呼叫 onGoToAssets，手動發布不 disabled", async () => {
    const user = userEvent.setup();
    const { onGoToAssets } = renderPage(campaign({ ready_count: 1, total: 3 }), "auto_meta");

    expect(await screen.findByText("還有 2 則廣告沒有素材")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "回到素材" }));
    expect(onGoToAssets).toHaveBeenCalledTimes(1);

    const manualButton = screen.getByRole("button", { name: "手動發布準備" }) as HTMLButtonElement;
    expect(manualButton.disabled).toBe(false);
  });

  it("manual、1/3 就位：警告帶出現", async () => {
    renderPage(campaign({ ready_count: 1, total: 3 }), "manual");
    expect(await screen.findByText("還有 2 則廣告沒有素材")).toBeTruthy();
  });

  it("simulated、1/3 就位：不出現警告帶", async () => {
    renderPage(campaign({ ready_count: 1, total: 3 }), "simulated");
    expect(await screen.findByText("演練用")).toBeTruthy();
    expect(screen.queryByText(/則廣告沒有素材/)).toBeNull();
  });
});

  it("opening manual checklist is read-only; explicit confirmation writes once", async () => {
    vi.mocked(getPublish).mockResolvedValue({ adapters: [{ key: "manual", label: "手動發布" }], adapter: "manual", describe: { adapter: "manual", message: null, checklist: [], content_hash: "current-plan-hash" } });
    vi.mocked(publishCampaign).mockResolvedValue({ adapter: "manual", message: null, checklist: [] });
    vi.mocked(getCampaign).mockResolvedValue(campaign({ ready_count: 0, total: 0 }));
    vi.mocked(publishCampaign).mockClear();
    renderPage(campaign({ ready_count: 0, total: 0 }), "manual");
    const confirm = await screen.findByRole("button", { name: "確認並記錄手動上架準備" });
    await userEvent.click(screen.getByRole("button", { name: "舊版名稱配對與紀錄（不代表本次清單完成）" }));
    expect(publishCampaign).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "我已在Meta建好，開始配對" }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(confirm);
    await waitFor(() => expect(publishCampaign).toHaveBeenCalledTimes(1));
    expect(publishCampaign).toHaveBeenCalledWith("brd_1", "cmp_1", "manual", { content_hash: "current-plan-hash", operation_id: expect.any(String) });
    expect(await screen.findByText("已記錄手動上架準備；請在平台完成設定後再配對。")).toBeTruthy();
  });

  it("非 Meta 即使 channels 顯示已連接，也不冒稱具有 Meta 專屬配對能力", async () => {
    const user = userEvent.setup();
    vi.mocked(getPublish).mockImplementation((_brandId, _campaignId, adapter = "manual") => Promise.resolve({
      adapters: [{ key: "manual", label: "手動發布" }, { key: "auto_meta", label: "自動發布（未接上）" }],
      adapter, describe: { adapter, message: adapter === "auto_meta" ? "自動發布未接上" : null, checklist: [] },
    }));
    vi.mocked(fetchChannels).mockResolvedValue([
      { key: "google_ads", label: "Google Ads", connected: true, state_text: "已接上" },
    ]);
    const c = campaign({ ready_count: 1, total: 1 });
    c.groups = [group("google_ads")];
    const first = renderPage(c, "auto_meta");
    expect(await screen.findByText("平台：Google Ads（已接上）")).toBeTruthy();
    expect(screen.queryByText(/平台：Meta/)).toBeNull();
    await user.click(screen.getByRole("button", { name: "手動發布準備" }));
    expect(first.onChangeAdapter).toHaveBeenCalledWith("manual");
    first.unmount();

    renderPage(c, "manual");
    const confirm = await screen.findByRole("button", { name: "確認並記錄手動上架準備" });
    await userEvent.click(screen.getByRole("button", { name: "舊版名稱配對與紀錄（不代表本次清單完成）" }));
    await user.click(confirm);
    expect(await screen.findByText(/目前僅支援與 Meta 配對/)).toBeTruthy();
    expect(screen.getByText(/這個 Campaign 的平台目前不能使用 Meta 配對/)).toBeTruthy();
    const pairingButton = screen.getByRole("button", { name: "我已在Meta建好，開始配對" }) as HTMLButtonElement;
    expect(pairingButton.disabled).toBe(true);
    await user.click(pairingButton);
    expect(bindCampaign).not.toHaveBeenCalled();
  });

  it("必要上架欄位直接顯示，選填 ID 與核對紀錄收合後仍可展開", async () => {
    vi.mocked(getPublish).mockResolvedValue({
      adapters: [{ key: "manual", label: "手動發布" }], adapter: "manual",
      describe: { adapter: "manual", message: null, checklist: [{
        level: "group", id: "grp_1", name: "投放組", fields: [
          { label: "每日預算", value: 1000, reason: "必要預算" },
          { label: "平台活動 ID（手動紀錄）", value: "尚未填寫", reason: "選填紀錄" },
        ],
      }] },
    });
    renderPage(campaign({ ready_count: 1, total: 1 }), "manual");
    expect(await screen.findByText("每日預算")).toBeTruthy();
    expect(screen.queryByText("平台活動 ID（手動紀錄）")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "選填 ID 與核對紀錄" }));
    expect(screen.getByText("平台活動 ID（手動紀錄）")).toBeTruthy();
  });

  it("Meta channel 狀態讀取失敗時維持未知並停用配對，不送 request", async () => {
    vi.mocked(getPublish).mockImplementation((_brandId, _campaignId, adapter = "manual") => Promise.resolve({
      adapters: [{ key: "manual", label: "手動發布" }, { key: "auto_meta", label: "自動發布（未接上）" }],
      adapter, describe: { adapter, message: null, checklist: [] },
    }));
    vi.mocked(fetchChannels).mockRejectedValue(new Error("offline"));
    const c = campaign({ ready_count: 1, total: 1 });
    c.groups = [group("meta")];
    renderPage(c, "manual");
    const confirm = await screen.findByRole("button", { name: "確認並記錄手動上架準備" });
    await userEvent.click(screen.getByRole("button", { name: "舊版名稱配對與紀錄（不代表本次清單完成）" }));
    await userEvent.click(confirm);
    expect(await screen.findByText(/Meta 連線狀態目前無法確認/)).toBeTruthy();
    const pairingButton = screen.getByRole("button", { name: "我已在Meta建好，開始配對" }) as HTMLButtonElement;
    expect(pairingButton.disabled).toBe(true);
    await userEvent.click(pairingButton);
    expect(bindCampaign).not.toHaveBeenCalled();
  });

  it("Meta 未連線時提供既有連線入口並停用配對", async () => {
    vi.mocked(getPublish).mockResolvedValue({
      adapters: [{ key: "manual", label: "手動發布" }], adapter: "manual",
      describe: { adapter: "manual", message: null, checklist: [] },
    });
    vi.mocked(fetchChannels).mockResolvedValue([
      { key: "meta", label: "Meta", connected: false, state_text: "未接上" },
    ]);
    const c = campaign({ ready_count: 1, total: 1 });
    c.groups = [group("meta")];
    renderPage(c, "manual");
    const confirm = await screen.findByRole("button", { name: "確認並記錄手動上架準備" });
    await userEvent.click(screen.getByRole("button", { name: "舊版名稱配對與紀錄（不代表本次清單完成）" }));
    await userEvent.click(confirm);
    expect(await screen.findByText(/先完成 Meta 廣告連線/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "前往 Meta 廣告連線" }).getAttribute("href")).toBe("/settings?tab=meta");
    expect((screen.getByRole("button", { name: "我已在Meta建好，開始配對" }) as HTMLButtonElement).disabled).toBe(true);
    expect(bindCampaign).not.toHaveBeenCalled();
  });

  it("confirm rejected by the server shows its message next to the button (drill 5)", async () => {
    vi.mocked(getPublish).mockResolvedValue({ adapters: [{ key: "manual", label: "手動發布" }], adapter: "manual", describe: { adapter: "manual", message: null, checklist: [], content_hash: "current-plan-hash" } });
    vi.mocked(publishCampaign).mockRejectedValue(new Error("餘額尚不確定，暫不能核准新增花費；可補資料、檢視或核准降低風險的操作。"));
    renderPage(campaign({ ready_count: 0, total: 0 }), "manual");
    await userEvent.click(await screen.findByRole("button", { name: "確認並記錄手動上架準備" }));
    expect((await screen.findByRole("alert")).textContent).toContain("餘額尚不確定");
  });
