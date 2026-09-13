/** frontend/src/components/ads/ConfirmBriefPage.test.tsx — F04-I12：四個斷言，`vi.mock`
 * 掉 `@/lib/adsApi` 與 `@/lib/productsApi`（不打真的 API，這一頁是純畫面邏輯的證偽）。 */
import { render, screen, waitFor, within } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { CampaignDetail, CampaignFieldSources } from "@/lib/adsApi";
import { generateStrategy, getCampaign, patchCampaign } from "@/lib/adsApi";
import { fetchProductList } from "@/lib/productsApi";
import { ConfirmBriefPage } from "./ConfirmBriefPage";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return {
    ...actual,
    getCampaign: vi.fn(),
    patchCampaign: vi.fn(),
    generateStrategy: vi.fn(),
  };
});

vi.mock("@/lib/productsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/productsApi")>("@/lib/productsApi");
  return { ...actual, fetchProductList: vi.fn() };
});

const mockGetCampaign = vi.mocked(getCampaign);
const mockPatchCampaign = vi.mocked(patchCampaign);
const mockGenerateStrategy = vi.mocked(generateStrategy);
const mockFetchProductList = vi.mocked(fetchProductList);

function sources(overrides: Partial<CampaignFieldSources> = {}): CampaignFieldSources {
  return {
    product: "user",
    objective: "system",
    platform: "system",
    budget: "system",
    dates: "system",
    audience: "system",
    ...overrides,
  };
}

function campaign(overrides: Partial<CampaignDetail> = {}): CampaignDetail {
  return {
    id: "cmp_1",
    name: "測試 Campaign",
    goal_text: "9 月想推 Beast Gummy",
    objective: "購買",
    success_metric: "cpa",
    success_target: null,
    success_basis: null,
    start_date: "2026-09-01",
    end_date: "2026-09-30",
    status: "draft",
    budget_planned: null,
    budget_scenario: null,
    budget_basis_json: {},
    budget_total: null,
    context_json: {
      product_ids: ["prd_1"],
      audience_hint: "上班族",
      field_sources: sources(),
    },
    constraints_json: { platform: "meta", budget: 30000 },
    verdict: null,
    verdict_json: {},
    closed_at: null,
    created_by: null,
    created_at: "2026-01-01T00:00:00Z",
    groups: [],
    actions: [],
    outcome: { spend: 0, purchases: 0, revenue: 0 },
    asset_readiness: { ready_count: 0, total: 0 },
    external_id: null,
    external_name: null,
    external_status: null,
    local_state: "unbound",
    bound_at: null,
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ConfirmBriefPage brandId="brd_1" campaignId="cmp_1" />
    </MemoryRouter>,
  );
}

describe("ConfirmBriefPage（F04-I12）", () => {
  it("六張卡的 label 都在畫面上", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockFetchProductList.mockResolvedValue([{ id: "prd_1", name: "Beast Gummy", status: "active", fact_count: 0, pending_fact_count: 0, economics_status: "none" }]);

    renderPage();

    for (const label of ["商品", "目標", "平台", "預算", "時間", "受眾方向"]) {
      expect(await screen.findByText(label)).toBeTruthy();
    }
  });

  it("field_sources 混合 user／system：畫面上「你說的」與「系統帶入」都出現", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockFetchProductList.mockResolvedValue([{ id: "prd_1", name: "Beast Gummy", status: "active", fact_count: 0, pending_fact_count: 0, economics_status: "none" }]);

    renderPage();

    await screen.findByText("商品");
    expect(screen.getAllByText("你說的").length).toBeGreaterThan(0);
    expect(screen.getAllByText("系統帶入").length).toBeGreaterThan(0);
  });

  it("編輯「目標」→ 選「名單」→ 儲存：patchCampaign 呼叫一次帶 objective，回傳值重畫成「你說的」", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockFetchProductList.mockResolvedValue([]);
    mockPatchCampaign.mockResolvedValue(
      campaign({
        objective: "名單",
        context_json: {
          product_ids: ["prd_1"],
          audience_hint: "上班族",
          field_sources: sources({ objective: "user" }),
        },
      }),
    );

    renderPage();
    await screen.findByText("目標");

    const objectiveLabel = screen.getByText("目標");
    const objectiveCard = objectiveLabel.closest("div.surface") as HTMLElement;
    fireEvent.click(within(objectiveCard).getAllByRole("button")[0]);

    const select = await within(objectiveCard).findByRole("combobox");
    fireEvent.change(select, { target: { value: "名單" } });
    fireEvent.click(within(objectiveCard).getByText("儲存"));

    await waitFor(() => expect(mockPatchCampaign).toHaveBeenCalledTimes(1));
    expect(mockPatchCampaign).toHaveBeenCalledWith("brd_1", "cmp_1", { objective: "名單" });

    expect(await within(objectiveCard).findByText("你說的")).toBeTruthy();
  });

  it("編輯「時間」卡：日期輸入的容器窄版直排（避免撐出卡片，見 F04-I12 Fix）", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockFetchProductList.mockResolvedValue([]);

    renderPage();
    await screen.findByText("時間");

    const dateLabel = screen.getByText("時間");
    const dateCard = dateLabel.closest("div.surface") as HTMLElement;
    fireEvent.click(within(dateCard).getAllByRole("button")[0]);

    const dateInputs = await within(dateCard).findAllByDisplayValue(/2026-09/);
    const wrapper = dateInputs[0].parentElement as HTMLElement;
    expect(wrapper.className).toContain("flex-col");
    expect(wrapper.className).not.toMatch(/flex-row/);
  });

  it("按「產生策略建議」→ generateStrategy 只被呼叫一次（不是載入時就呼叫）", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockFetchProductList.mockResolvedValue([]);
    mockGenerateStrategy.mockResolvedValue(campaign());

    renderPage();
    await screen.findByText("商品");
    expect(mockGenerateStrategy).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("產生策略建議 →"));

    await waitFor(() => expect(mockGenerateStrategy).toHaveBeenCalledTimes(1));
    expect(mockGenerateStrategy).toHaveBeenCalledWith("brd_1", "cmp_1");
  });
});
