import type { LearningEvidence, LearningEvidenceContext } from "@/lib/adsLearningEvidence";

function learningEvidence(id = "learning-fixture"): LearningEvidence {
  return {
    schema_version: 1, id, meaning_revision: "meaning-fixture", display_text: "歷史紀錄",
    support_label: "來源尚未核實", provenance: "unknown",
    sources: [{kind: null, id: null, version: null, period: {start: null, end: null}, label: null}],
    scope: {product_id: null, product_label: null, audience_key: null, customer_group_id: null,
      claim_key: null, claim_family: null, objective_family: null, result_kind: null, currency: null, attribution: null},
    conditions: {price_version: null, offer_key: null, offer_version: null, material_version: null,
      target_version: null, valid_until: null},
    sample: {result_events: null, sufficient: null}, independent_count: 0, same_direction_count: 0,
    contrary_count: 0, use_state: "history", reason_codes: ["unknown_source"],
    reason_labels: ["來源尚未核實，保留為歷史"], allowed_uses: [], limits: ["conditions_unknown"],
  };
}
const evidenceContext: LearningEvidenceContext = {
  schema_version: 1, revision: "context-fixture", scope_product_id: null, scope_label: null,
  eligible_count: 0, items: [], omitted: 0,
};
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/libraryApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/libraryApi")>("@/lib/libraryApi");
  return { ...actual, fetchLibrary: vi.fn() };
});
vi.mock("@/lib/adsLearningsApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adsLearningsApi")>("@/lib/adsLearningsApi");
  return { ...actual, getCoordinateLearnings: vi.fn() };
});
vi.mock("@/lib/adsWizardApi", () => ({getWizardOptions: vi.fn(async () => ({products: [], objectives: [], default_objective: null, default_platform: null}))}));
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ refreshBrands: vi.fn() }) }));
vi.mock("./tabs/FactsTab", () => ({ FactsTab: () => <p>品牌事實內容</p> }));
vi.mock("./tabs/RulesTab", () => ({ RulesTab: () => <p>限制規則內容</p> }));
vi.mock("./tabs/ClaimsTab", () => ({ ClaimsTab: () => <p>宣稱內容</p> }));
vi.mock("./tabs/AssetsTab", () => ({ AssetsTab: () => <p>官方素材內容</p> }));
vi.mock("./tabs/ChannelsTab", () => ({ ChannelsTab: () => <p>自有渠道內容</p> }));
vi.mock("./tabs/CustomerVoiceTab", () => ({
  CustomerVoiceTab: ({ jobs }: { jobs: { job_key: string; status: string }[] }) => (
    <p>顧客原話內容{jobs.map((job) => `｜${job.job_key}:${job.status}`).join("")}</p>
  ),
}));
vi.mock("./tabs/CoordinatesTab", () => ({ CoordinatesTab: () => <p>創意座標內容</p> }));

import { fetchLibrary, type LibraryData } from "@/lib/libraryApi";
import { getCoordinateLearnings, type CoordinateLearnings } from "@/lib/adsLearningsApi";
import { LibraryPage } from "./LibraryPage";
import {getWizardOptions} from "@/lib/adsWizardApi";
import {libraryEvidenceFixture, libraryOptionsFixture} from "../ads/learnings/learningEvidence.fixtures";

const mockFetchLibrary = vi.mocked(fetchLibrary);
const mockLearnings = vi.mocked(getCoordinateLearnings);
// Contract L, one closed campaign with two ranked rows (shape of app/tests/test_ads_learnings_api.py).
const LEARNED: CoordinateLearnings = {
  evidence_context: evidenceContext, campaigns: [{
    campaign_id: "adc_1", campaign_name: "三盒組・第一期", sell_way_id: "prd_box", start_date: "2026-09-05", end_date: "2026-09-18",
    closed_on: "2026-09-19", cap: 450, currency: "TWD", spend: 2580, sales: 4, cost_per_sale: 645, counts: { keep: 1, replace: 1 },
    rule_text: "1 則每筆低於上限 450 → 留下；其餘換掉", empty_reason: null,
    rows: [
      { rank: 1, of: 2, ad_id: "ada_1", ad_name: "備考生・讀到深夜", customer_group: { id: "pcg_1", who: "學生備考" }, coordinates: [], spend: 1160, sales: 4, cost_per_sale: 290, verdict: "keep", verdict_label: "留下", flags: ["樣本少"], evidence: learningEvidence(), learning_id: "lrn_1" },
      { rank: 2, of: 2, ad_id: "ada_2", ad_name: "會議前・午休", customer_group: { id: "pcg_1", who: "學生備考" }, coordinates: [], spend: 1420, sales: 0, cost_per_sale: null, verdict: "replace", verdict_label: "換掉", flags: [], evidence: learningEvidence(), learning_id: "lrn_2" },
    ],
  }],
  groups: [{ customer_group_id: "pcg_1", who: "學生備考", ads: 2, spend: 2580, sales: 4, cap: 450, cost_per_sale: 645 }],
  next: { sell_way_id: "prd_box", new_campaign_href: "/brands/brand-1/ads/new?sell_way=prd_box" },
};
const DATA: LibraryData = {
  brand: { id: "brand-1", name: "測試品牌", client_name: null, status: "active", market_region: "TW", conversion_goal: "purchase", advertising_history: null, regulatory_regime: null, delete_impact: [] },
  products: [], facts: [], rules: [], claims: [], assets: [], channels: [], customer_voices: [],
};

function view(entry = "/brands/brand-1/library") {
  mockFetchLibrary.mockResolvedValue(DATA);
  if (!mockLearnings.getMockImplementation()) mockLearnings.mockResolvedValue(LEARNED);
  return render(<MemoryRouter initialEntries={[entry]}><LibraryPage brandId="brand-1" /></MemoryRouter>);
}

afterEach(() => vi.resetAllMocks());

describe("LibraryPage 一般與進階內容", () => {
  it("預設顯示品牌事實，宣稱也留在一般層可直接進入", async () => {
    view();
    expect(await screen.findByText("品牌事實內容")).toBeTruthy();
    expect(screen.getByRole("button", { name: /品牌事實/ }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: /宣稱/ })).toBeTruthy();
    expect(screen.getByText("進階內容").closest("details")?.open).toBe(false);
  });

  it("既有創意座標深連結會打開同頁進階區", async () => {
    view("/brands/brand-1/library?tab=coordinates");
    expect(await screen.findByText("創意座標內容")).toBeTruthy();
    expect(screen.getByText("進階內容").closest("details")?.open).toBe(true);
    // F42-I14: the 調研報告 tab left with the retired research → paste stage.
    expect(screen.queryByRole("button", { name: "調研報告" })).toBeNull();
  });

  it("標題列的建檔入口叫「品牌資料（建檔時填的）」，連到品牌建檔", async () => {
    view();
    const link = await screen.findByRole("link", { name: "品牌資料（建檔時填的）" });
    expect(link.getAttribute("href")).toBe("/brands/brand-1/intake");
    expect(screen.queryByRole("link", { name: "品牌調研" })).toBeNull();
  });
});

describe("LibraryPage 顧客原話背景工作（F50-I16）", () => {
  it("passes the payload's customer_voice_jobs to the tab, so a reload keeps a running extraction", async () => {
    mockFetchLibrary.mockResolvedValue({
      ...DATA,
      customer_voice_jobs: [{ job_key: "cvjob_1", status: "running", error: null, started_at: "2026-10-05T02:00:00+00:00" }],
    });
    mockLearnings.mockResolvedValue(LEARNED);
    render(<MemoryRouter initialEntries={["/brands/brand-1/library?tab=customer-voice"]}><LibraryPage brandId="brand-1" /></MemoryRouter>);
    expect(await screen.findByText("顧客原話內容｜cvjob_1:running")).toBeTruthy();
  });

  it("an older payload without the field passes no jobs", async () => {
    view("/brands/brand-1/library?tab=customer-voice");
    expect(await screen.findByText("顧客原話內容")).toBeTruthy();
  });
});

describe("LibraryPage 投放學到的（F46-I06）", () => {
  it("投放成果 group in the sub-nav, count shown once read; existing tabs unchanged", async () => {
    view();
    expect(await screen.findByText("品牌事實內容")).toBeTruthy();
    expect(screen.getByText("投放成果")).toBeTruthy();
    expect(await screen.findByRole("button", { name: /^投放學到的\s*2$/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /投放學到的/ }).getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: /投放學到的/ }));
    fireEvent.click(await screen.findByRole("button", {name: "每期廣告排名"}));
    expect(await screen.findByRole("region", { name: "三盒組・第一期" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /投放學到的/ }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByText("品牌事實內容")).toBeNull();
  });

  it("?campaign= lands on the tab and highlights that campaign", async () => {
    view("/brands/brand-1/library?tab=ads-learnings&campaign=adc_1");
    const camp = await screen.findByRole("region", { name: "三盒組・第一期" });
    expect(camp.getAttribute("data-highlight")).toBe("true");
    expect(within(camp).getByText("剛結案")).toBeTruthy();
  });

  it("a failed read says so with 重新讀取 (never the empty state) and retries", async () => {
    mockLearnings.mockRejectedValueOnce(new Error("讀取投放學到的失敗。")).mockResolvedValue(LEARNED);
    view("/brands/brand-1/library?campaign=adc_1");
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByText("還沒有結案的活動")).toBeNull();
    expect(screen.getByRole("button", { name: "投放學到的" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "重新讀取" }));
    expect(await screen.findByRole("region", { name: "三盒組・第一期" })).toBeTruthy();
    expect(mockLearnings).toHaveBeenCalledTimes(2);
  });
});


it("explains why brand editing is unavailable after a failed read", async () => {
  mockFetchLibrary.mockRejectedValue(new Error("暫時讀不到"));
  mockLearnings.mockResolvedValue(LEARNED);
  render(<MemoryRouter><LibraryPage brandId="brand-1"/></MemoryRouter>);
  const reason=await screen.findByText("先重新載入品牌資料");
  const button=screen.getByRole("button",{name:"品牌資料"});
  expect(button).toHaveProperty("disabled",true);
  expect(button.getAttribute("aria-describedby")).toBe(reason.id);
});

it("scoped qualification never replaces global nav counts or the complete campaign ranks", async () => {
  vi.mocked(getWizardOptions).mockResolvedValue({...libraryOptionsFixture, products: [{...libraryOptionsFixture.products[0], id: "prd_box"}]});
  const scoped = libraryEvidenceFixture();
  scoped.evidence_context.scope_product_id = "prd_box";
  scoped.campaigns = [];
  scoped.next = {sell_way_id: "prd_box", new_campaign_href: "/brands/brand-1/ads/new?sell_way=prd_box"};
  mockLearnings.mockImplementation(async (_brand, filter) => filter?.sellWayId ? scoped : LEARNED);
  view("/brands/brand-1/library?tab=ads-learnings");
  expect(await screen.findByRole("button", {name: /^投放學到的\s*2$/})).toBeTruthy();
  expect(await screen.findByRole("link", {name: "用可參考資料規劃下一期 →"})).toBeTruthy();
  expect(screen.getByText("2 條可參考 · 其餘資料保留在歷史")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", {name: "每期廣告排名"}));
  expect(screen.getByRole("table", {name: "三盒組・第一期 每則廣告排名"})).toBeTruthy();
  expect(screen.getByText("花 2,580・成交 4・每筆 645")).toBeTruthy();
});

it("late library and global learning responses cannot replace the current brand", async () => {
  let oldLibrary!: (data: LibraryData) => void;
  let oldLearning!: (data: CoordinateLearnings) => void;
  mockFetchLibrary.mockImplementation(id => id === "brand-1" ? new Promise(resolve => {oldLibrary = resolve;}) : Promise.resolve({...DATA, brand: {...DATA.brand, id: "brand-2", name: "目前品牌"}}));
  mockLearnings.mockImplementation(id => id === "brand-1" ? new Promise(resolve => {oldLearning = resolve;}) : Promise.resolve({...LEARNED, campaigns: [], next: null}));
  const page = render(<MemoryRouter><LibraryPage brandId="brand-1"/></MemoryRouter>);
  page.rerender(<MemoryRouter><LibraryPage brandId="brand-2"/></MemoryRouter>);
  expect(await screen.findByText(/目前品牌 · 品牌事實/)).toBeTruthy();
  expect(await screen.findByRole("button", {name: /^投放學到的\s*0$/})).toBeTruthy();
  await act(async () => {oldLibrary(DATA); oldLearning(LEARNED);});
  expect(screen.getByText(/目前品牌 · 品牌事實/)).toBeTruthy();
  expect(screen.getByRole("button", {name: /^投放學到的\s*0$/})).toBeTruthy();
  expect(screen.queryByText(/測試品牌 · 品牌事實/)).toBeNull();
});
