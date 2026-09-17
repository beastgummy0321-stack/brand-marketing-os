/** frontend/src/components/ads/PublishPage.test.tsx — F06-I04: 發布畫面不再只印一句「自動發布
 * 未接上」，直接給「手動發布」「模擬發布（演練）」兩顆按鈕；素材沒就位時不擋，只印紅色警告帶
 * （ARCHITECTURE.md §6.2 決議 17–18）。這支測試證明警告帶只依 `asset_readiness` 出現、模擬發布
 * 不受影響，以及兩顆按鈕都呼叫 `onChangeAdapter`。 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";

import type { AssetReadinessSummary, CampaignDetail } from "@/lib/adsApi";
import { bindCampaign, getCampaign, getPublish, publishCampaign } from "@/lib/adsApi";
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
  render(
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
  return { onChangeAdapter, onGoToAssets };
}

describe("PublishPage（F06-I04）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getPublish).mockImplementation((_brandId, _campaignId, adapter = "manual") =>
      Promise.resolve({
        adapters: [],
        adapter,
        describe: { adapter, message: "自動發布未接上", checklist: [] },
      }),
    );
    vi.mocked(publishCampaign).mockResolvedValue({ adapter: "manual", message: null, checklist: [] });
    vi.mocked(getCampaign).mockResolvedValue(campaign({ ready_count: 0, total: 0 }));
    vi.mocked(bindCampaign).mockResolvedValue({ message: null, campaign: campaign({ ready_count: 0, total: 0 }) });
  });

  it("auto_meta、3/3 就位：印「自動發布未接上」，兩顆按鈕各自呼叫 onChangeAdapter，沒有警告帶", async () => {
    const user = userEvent.setup();
    const { onChangeAdapter } = renderPage(campaign({ ready_count: 3, total: 3 }), "auto_meta");

    expect(await screen.findByText("自動發布未接上")).toBeTruthy();
    expect(screen.queryByText(/則廣告沒有素材/)).toBeNull();

    await user.click(screen.getByRole("button", { name: "手動上架準備" }));
    expect(onChangeAdapter).toHaveBeenCalledWith("manual");

    await user.click(screen.getByRole("button", { name: "模擬發布（演練）" }));
    expect(onChangeAdapter).toHaveBeenCalledWith("simulated");
  });

  it("auto_meta、1/3 就位：印「還有 2 則廣告沒有素材」，「回到素材」呼叫 onGoToAssets，手動發布不 disabled", async () => {
    const user = userEvent.setup();
    const { onGoToAssets } = renderPage(campaign({ ready_count: 1, total: 3 }), "auto_meta");

    expect(await screen.findByText("還有 2 則廣告沒有素材")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "回到素材" }));
    expect(onGoToAssets).toHaveBeenCalledTimes(1);

    const manualButton = screen.getByRole("button", { name: "手動上架準備" }) as HTMLButtonElement;
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
    vi.mocked(getPublish).mockResolvedValue({ adapters: [], adapter: "manual", describe: { adapter: "manual", message: null, checklist: [] } });
    vi.mocked(publishCampaign).mockResolvedValue({ adapter: "manual", message: null, checklist: [] });
    vi.mocked(getCampaign).mockResolvedValue(campaign({ ready_count: 0, total: 0 }));
    vi.mocked(publishCampaign).mockClear();
    renderPage(campaign({ ready_count: 0, total: 0 }), "manual");
    const confirm = await screen.findByRole("button", { name: "確認並記錄手動上架準備" });
    expect(publishCampaign).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "我已在 Meta 建好，開始配對" }) as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(confirm);
    await waitFor(() => expect(publishCampaign).toHaveBeenCalledTimes(1));
    expect(publishCampaign).toHaveBeenCalledWith("brd_1", "cmp_1", "manual");
    expect(await screen.findByText("已記錄手動上架準備；請在平台完成設定後再配對。")).toBeTruthy();
  });
