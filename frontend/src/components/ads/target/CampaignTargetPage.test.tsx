/** frontend/src/components/ads/target/CampaignTargetPage.test.tsx — F19-I05：`vi.mock` 掉
 * `@/lib/adsApi`／`@/lib/adsTriageApi`／`@/lib/productsApi`，不打真的 API（e2e 才打真的後端，
 * 見 `frontend/e2e/ads-target.spec.ts`）。覆蓋 Done 6＋repair list：載入、每種依據、缺漏
 * chips、own 不接受 0、break_even 商品沒成本不給選、存檔沒解出數字不假裝完成、版本衝突、
 * 未儲存離開保護、`<select>` 的可存取名稱含可見標籤。 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CampaignDetail } from "@/lib/adsApi";
import { getCampaign } from "@/lib/adsApi";
import type { CampaignTarget } from "@/lib/adsTriageApi";
import { TriageRequestRejected, getTarget, putTarget } from "@/lib/adsTriageApi";
import type { ProductListItem } from "@/lib/productsApi";
import { fetchProductList } from "@/lib/productsApi";
import { CampaignTargetPage } from "./CampaignTargetPage";

vi.mock("@/lib/adsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsApi")>("@/lib/adsApi");
  return { ...actual, getCampaign: vi.fn() };
});
vi.mock("@/lib/adsTriageApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsTriageApi")>("@/lib/adsTriageApi");
  return { ...actual, getTarget: vi.fn(), putTarget: vi.fn() };
});
vi.mock("@/lib/productsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/productsApi")>("@/lib/productsApi");
  return { ...actual, fetchProductList: vi.fn() };
});

const mockGetCampaign = vi.mocked(getCampaign);
const mockGetTarget = vi.mocked(getTarget);
const mockPutTarget = vi.mocked(putTarget);
const mockFetchProductList = vi.mocked(fetchProductList);

function campaign(overrides: Partial<CampaignDetail> = {}): CampaignDetail {
  return {
    id: "cmp_1",
    name: "日常商品推廣",
    goal_text: null,
    objective: "購買",
    success_metric: "cpa",
    success_target: null,
    success_basis: null,
    start_date: null,
    end_date: null,
    status: "live",
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
    asset_readiness: { ready_count: 0, total: 0 },
    external_id: null,
    external_name: null,
    external_status: null,
    local_state: "unbound",
    bound_at: null,
    ...overrides,
  };
}

// F19-I06：跟 `app/ads/result_kinds.py::LABELS` 同一份詞彙，測試不自己另編一份清單。
const RESULT_KINDS = [
  { kind: "purchase", label: "購買" },
  { kind: "engagement", label: "互動" },
  { kind: "link_click", label: "點擊" },
  { kind: "lead", label: "名單" },
];

function target(overrides: Partial<CampaignTarget> = {}): CampaignTarget {
  return {
    campaign_id: "cmp_1",
    product_ids: [],
    own_value: null,
    revision: 0,
    value: null,
    basis: null,
    result_kind: null,
    result_label: "成果",
    result_kinds: RESULT_KINDS,
    missing: [],
    ...overrides,
  };
}

const products: ProductListItem[] = [
  { id: "prd_1", name: "晨光隨行杯", status: "active", fact_count: 0, pending_fact_count: 0, economics_status: "confirmed" },
  { id: "prd_2", name: "辦公室隨行杯", status: "active", fact_count: 0, pending_fact_count: 0, economics_status: "none" },
];

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/brands/brd_1/ads/campaigns/cmp_1/target"]}>
      <Routes>
        <Route
          path="/brands/:brandId/ads/campaigns/:campaignId/target"
          element={<CampaignTargetPage brandId="brd_1" campaignId="cmp_1" />}
        />
        <Route path="/brands/:brandId/ads" element={<p>投放中心首頁</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("CampaignTargetPage（F19-I05）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetchProductList.mockResolvedValue(products);
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("載入後顯示目前的成果與已解出的目標線；建議 chip 落在目前生效的依據卡上", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockGetTarget.mockResolvedValue(target({ basis: "trailing_30", value: 380, result_kind: "purchase" }));
    renderPage();

    expect(await screen.findByText("購買")).toBeTruthy();
    expect(await screen.findByText("每次購買最多花多少")).toBeTruthy();
    expect(await screen.findByText("380")).toBeTruthy();
    expect((screen.getByRole("button", { name: "儲存目標" }) as HTMLButtonElement).disabled).toBe(true);

    const badge = screen.getByText("建議");
    expect(badge.closest("button")?.textContent).toContain("自己近 30 天");
  });

  it("target.basis 是 break_even 時，建議只落在打平值卡", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockGetTarget.mockResolvedValue(target({ basis: "break_even", value: 300, product_ids: ["prd_1"] }));
    renderPage();

    const badge = await screen.findByText("建議");
    expect(badge.closest("button")?.textContent).toContain("打平值");
  });

  it("依據是 own（使用者自訂覆寫）時：任何一張卡都不顯示「建議」——resolve() 提早回傳，根本沒評估過 break_even／trailing_30", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockGetTarget.mockResolvedValue(target({ basis: "own", value: 200, own_value: 200, missing: [] }));
    renderPage();

    await screen.findByRole("heading", { name: "這個活動的目標" });
    expect(screen.queryByText("建議")).toBeNull();
  });

  it("看什麼成果尚未選擇時：分段選單沒有任何按鈕預選，標題退回「成果」（F19-I06：誠實的未選狀態，不是猜一個預設）", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockGetTarget.mockResolvedValue(target());
    renderPage();

    await screen.findByRole("heading", { name: "這個活動的目標" });
    const group = screen.getByRole("group", { name: "看什麼成果" });
    RESULT_KINDS.forEach((option) => {
      expect(within(group).getByRole("button", { name: option.label }).getAttribute("aria-pressed")).toBe("false");
    });
    expect(screen.getByText("每次成果最多花多少")).toBeTruthy();
  });

  it("選一個成果：畫面即時換標題、表單變 dirty、存檔會把 result_kind 一起送出", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockGetTarget.mockResolvedValue(target({ missing: ["trailing_30"] }));
    mockPutTarget.mockResolvedValue(
      target({ basis: "own", value: 50, own_value: 50, revision: 1, result_kind: "lead", result_label: "名單" }),
    );
    renderPage();

    const group = await screen.findByRole("group", { name: "看什麼成果" });
    fireEvent.click(within(group).getByRole("button", { name: "名單" }));
    expect(within(group).getByRole("button", { name: "名單" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("每次名單最多花多少")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /^自訂/ }));
    fireEvent.change(screen.getByLabelText("目標每次名單成本"), { target: { value: "50" } });
    const save = screen.getByRole("button", { name: "儲存目標" }) as HTMLButtonElement;
    expect(save.disabled).toBe(false);
    fireEvent.click(save);

    await waitFor(() =>
      expect(mockPutTarget).toHaveBeenCalledWith("brd_1", "cmp_1", {
        basis: "own", result_kind: "lead", expected_revision: 0, value: 50,
      }),
    );
  });

  it("own 依據：輸入金額後可以儲存，成功後回投放中心", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockGetTarget.mockResolvedValue(target({ missing: ["trailing_30"] }));
    mockPutTarget.mockResolvedValue(target({ basis: "own", value: 120, own_value: 120, revision: 1 }));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /自訂/ }));
    fireEvent.change(screen.getByLabelText("目標每次成果成本"), { target: { value: "120" } });
    const save = screen.getByRole("button", { name: "儲存目標" }) as HTMLButtonElement;
    expect(save.disabled).toBe(false);
    fireEvent.click(save);

    // review fix：沒碰過「看什麼成果」就不送 result_kind——沒有 basis 以外的欄位。
    await waitFor(() =>
      expect(mockPutTarget).toHaveBeenCalledWith("brd_1", "cmp_1", {
        basis: "own", expected_revision: 0, value: 120,
      }),
    );
    expect(await screen.findByText("投放中心首頁")).toBeTruthy();
  });

  it("review fix：已知（推導出）的成果會預選，但只改 own 數字不碰選單時，存檔不送 result_kind——避免把 resolve() 推導值凍結進使用者選擇，擋住之後的同步", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    // trailing_30 推導出的 result_kind：`ads_campaign.result_kind` 本身仍可能是 NULL（見
    // `app/ads/targets.py::resolve()`／`external_sync.py` 的 `... AND result_kind IS NULL`）。
    mockGetTarget.mockResolvedValue(
      target({ basis: "trailing_30", value: 380, result_kind: "purchase", missing: [] }),
    );
    mockPutTarget.mockResolvedValue(
      target({ basis: "own", value: 500, own_value: 500, revision: 1, result_kind: "purchase" }),
    );
    renderPage();

    const group = await screen.findByRole("group", { name: "看什麼成果" });
    expect(within(group).getByRole("button", { name: "購買" }).getAttribute("aria-pressed")).toBe("true");

    fireEvent.click(screen.getByRole("button", { name: /^自訂/ }));
    fireEvent.change(screen.getByLabelText("目標每次購買成本"), { target: { value: "500" } });
    fireEvent.click(screen.getByRole("button", { name: "儲存目標" }));

    await waitFor(() =>
      expect(mockPutTarget).toHaveBeenCalledWith("brd_1", "cmp_1", {
        basis: "own", expected_revision: 0, value: 500,
      }),
    );
  });

  it("own 依據：0 不是有效目標，按鈕不開、旁邊顯示缺什麼", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockGetTarget.mockResolvedValue(target({ missing: ["trailing_30"] }));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /自訂/ }));
    fireEvent.change(screen.getByLabelText("目標每次成果成本"), { target: { value: "0" } });
    const save = screen.getByRole("button", { name: "儲存目標" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    expect(screen.getByText("還差一個數字")).toBeTruthy();
    expect(mockPutTarget).not.toHaveBeenCalled();
  });

  it("break_even 依據：要選商品才能儲存", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockGetTarget.mockResolvedValue(target({ missing: ["product"] }));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /打平值/ }));
    const save = screen.getByRole("button", { name: "儲存目標" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    expect(screen.getByText("還差一個商品")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("商品"), { target: { value: "prd_1" } });
    expect(save.disabled).toBe(false);
  });

  it("break_even 依據：商品還沒有售價，選單裡不給選、不能存出一個會失敗的請求", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockGetTarget.mockResolvedValue(target({ missing: ["product"] }));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /打平值/ }));
    const select = screen.getByLabelText("商品") as HTMLSelectElement;
    const noneOption = Array.from(select.options).find((o) => o.value === "prd_2")!;
    expect(noneOption.disabled).toBe(true);
    expect(noneOption.textContent).toContain("尚無售價");

    fireEvent.change(select, { target: { value: "prd_2" } });
    expect((screen.getByRole("button", { name: "儲存目標" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("還差一個商品")).toBeTruthy();
    expect(mockPutTarget).not.toHaveBeenCalled();
  });

  it("缺漏原因用 chip 顯示在數字的位置，不是空白", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockGetTarget.mockResolvedValue(target({ missing: ["product", "product_cost"] }));
    renderPage();

    expect(await screen.findByText("尚未選商品")).toBeTruthy();
    expect(screen.getByText("商品還沒有成本")).toBeTruthy();
  });

  it("存檔後仍解不出數字：留在這頁顯示最新缺漏，不假裝完成、不跳轉", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockGetTarget.mockResolvedValue(target({ missing: ["product"] }));
    mockPutTarget.mockResolvedValue(target({ basis: "break_even", value: null, missing: ["product_cost"], revision: 1 }));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /打平值/ }));
    fireEvent.change(screen.getByLabelText("商品"), { target: { value: "prd_1" } });
    fireEvent.click(screen.getByRole("button", { name: "儲存目標" }));

    await waitFor(() => expect(mockPutTarget).toHaveBeenCalled());
    expect(await screen.findByText("商品還沒有成本")).toBeTruthy();
    expect(await screen.findByRole("heading", { name: "這個活動的目標" })).toBeTruthy();
    expect(screen.queryByText("投放中心首頁")).toBeNull();
  });

  it("版本衝突：用錯誤信封的 code 認出來，不靠比對中文訊息（F19-I06：訊息文字換了也認得出）", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockGetTarget.mockResolvedValueOnce(target({ missing: ["trailing_30"] }));
    // 訊息文字刻意跟 `_TARGET_ERRORS["target_conflict"]` 不一樣——只靠 `code` 判斷才會通過。
    mockPutTarget.mockRejectedValueOnce(new TriageRequestRejected("換了一句不一樣的訊息", "target_conflict"));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /自訂/ }));
    fireEvent.change(screen.getByLabelText("目標每次成果成本"), { target: { value: "50" } });
    fireEvent.click(screen.getByRole("button", { name: "儲存目標" }));

    expect(await screen.findByText(/這個活動的目標已被更新/)).toBeTruthy();

    mockGetTarget.mockResolvedValueOnce(target({ basis: "own", value: 999, revision: 1 }));
    fireEvent.click(screen.getByRole("button", { name: "重新讀取最新版本" }));
    expect(await screen.findByText("999")).toBeTruthy();
  });

  it("未儲存離開有保護：離開整頁連結會先確認", async () => {
    mockGetCampaign.mockResolvedValue(campaign());
    mockGetTarget.mockResolvedValue(target({ missing: ["trailing_30"] }));
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /自訂/ }));
    fireEvent.change(screen.getByLabelText("目標每次成果成本"), { target: { value: "10" } });

    fireEvent.click(screen.getByRole("link", { name: "← 投放中心" }));
    expect(confirmSpy).toHaveBeenCalled();
    expect(screen.queryByText("投放中心首頁")).toBeNull();
  });
});
