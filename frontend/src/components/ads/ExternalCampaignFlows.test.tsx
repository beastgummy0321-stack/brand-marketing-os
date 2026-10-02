import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import type { CampaignDetail } from "@/lib/adsApi";
import { patchCampaign } from "@/lib/adsApi";
import { existingCampaigns, externalView, importExisting, refreshExisting, type ExistingPage, type ExternalView, type NativeEntity } from "@/lib/adsExternalApi";
import { ExistingCampaignDialog } from "./ExistingCampaignDialog";
import { ExternalCampaignPanel } from "./ExternalCampaignPanel";

vi.mock("@/lib/adsExternalApi", () => ({ existingCampaigns: vi.fn(), externalView: vi.fn(), importExisting: vi.fn(), refreshExisting: vi.fn(), syncCampaign: vi.fn(), syncJob: vi.fn() }));
vi.mock("@/lib/adsApi", () => ({ patchCampaign: vi.fn() }));

function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }
function entity(id: string): NativeEntity { return { id, platform: "meta", source_account: "101", native_kind: "campaign", native_id: id, native_label: "活動", name: id, parent_native_id: null, native_status: "PAUSED", start_date: null, end_date: null, budget_amount: null, budget_type: "lifetime", budget_raw: { values: { lifetime_budget: "4000" } }, currency: "TWD", last_success_at: null, sync_error: null, creative: {} }; }
function page(account = "101", names = ["甲活動"], cursor: string | null = null): ExistingPage { return { items: names.map(id => ({ id, native_id: id, native_kind: "campaign", snapshot: entity(id) })), sources: [{ platform: "meta", label: "Meta", account_id: "101", name: "甲帳號" }, { platform: "meta", label: "Meta", account_id: "202", name: "乙帳號" }], platform: "meta", source_account: account, next_cursor: cursor, job: null }; }
function view(overrides: Partial<ExternalView> = {}): ExternalView { return { entities: [entity("活動根")], observations: [], next_entity_cursor: null, next_observation_cursor: null, window: { start: "2026-09-01", end: "2026-09-18" }, connections: [{ platform: "meta", source_account: "101", state: "connected" }], sync: {}, coverage: {}, ...overrides }; }
function campaign(id = "cmp_1"): CampaignDetail { return { id, name: id, origin: "imported", goal_text: "增加來店", objective: "增加來店", cap: { value: null, basis: null, own_value: null, break_even: null, price: null, product_id: null, result_kind: "purchase", result_label: "購買", missing: ["product"], revision: 0 }, start_date: null, end_date: null, status: "ready", budget_planned: null, budget_scenario: null, budget_basis_json: {}, budget_total: null, context_json: {}, constraints_json: {}, verdict: null, verdict_json: {}, closed_at: null, created_by: null, created_at: "2026-09-18", groups: [], actions: [], outcome: { spend: null, purchases: null, revenue: null }, asset_readiness: { ready_count: 0, total: 0, pack_id: null }, external_id: null, external_name: null, external_status: null, local_state: "unbound", bound_at: null }; }
function Location() { return <output data-testid="location">{useLocation().pathname}</output>; }
function openDialog() { const mounted = render(<MemoryRouter><ExistingCampaignDialog brandId="brand_1" /><Location /></MemoryRouter>); fireEvent.click(screen.getByRole("button", { name: "加入既有活動" })); return mounted; }
beforeEach(() => { vi.resetAllMocks(); vi.mocked(existingCampaigns).mockResolvedValue(page()); vi.mocked(externalView).mockResolvedValue(view()); });
afterEach(cleanup);

describe("既有活動來源與原始資料", () => {
  it("載入更多保留首批，匯入直接使用回傳 Campaign ID 導工作區", async () => {
    vi.mocked(existingCampaigns).mockResolvedValueOnce(page("101", ["首批活動"], "next")).mockResolvedValueOnce(page("101", ["第二批活動"]));
    vi.mocked(importExisting).mockResolvedValue({ campaign: { id: "imported_42" } });
    openDialog(); await screen.findByText("首批活動");
    fireEvent.click(screen.getByRole("button", { name: "載入更多活動" })); await screen.findByText("第二批活動");
    expect(screen.queryByText("首批活動")).not.toBeNull();
    fireEvent.click(screen.getAllByRole("button", { name: "納入並開啟" })[1]);
    await waitFor(() => expect(screen.getByTestId("location").textContent).toBe("/brands/brand_1/ads/campaigns/imported_42"));
    expect(importExisting).toHaveBeenCalledWith("brand_1", { platform: "meta", source_account: "101", native_kind: "campaign", native_id: "第二批活動" });
  });

  it("切帳號取消前帳號分頁，忽略仍然回來的舊結果", async () => {
    const old = deferred<ExistingPage>();
    vi.mocked(existingCampaigns).mockResolvedValueOnce(page("101", ["首批活動"], "next")).mockReturnValueOnce(old.promise).mockResolvedValueOnce(page("202", ["乙活動"]));
    openDialog(); await screen.findByText("首批活動");
    fireEvent.click(screen.getByRole("button", { name: "載入更多活動" }));
    const oldSignal = vi.mocked(existingCampaigns).mock.calls[1][2]!;
    fireEvent.change(screen.getByLabelText("品牌綁定帳號"), { target: { value: "meta|202" } });
    await screen.findByText("乙活動"); expect(oldSignal.aborted).toBe(true);
    await act(async () => old.resolve(page("101", ["過期甲活動"])));
    expect(screen.queryByText("過期甲活動")).toBeNull(); expect(screen.queryByText("乙活動")).not.toBeNull();
  });

  it("F47-I08：平台狀態說中文、日期與最近成功不印 ISO、已在工作區的活動標出來並改成打開", async () => {
    const listed = page("101", ["已納入活動", "新活動"]);
    listed.items[0] = { ...listed.items[0], campaign_id: "cmp_in", snapshot: { ...entity("已納入活動"), native_status: "ACTIVE", start_date: "2026-10-03", end_date: "2026-10-09" } };
    listed.items[1] = { ...listed.items[1], snapshot: { ...entity("新活動"), native_status: "WITH_ISSUES" } };
    listed.job = { id: "job_1", status: "succeeded", last_success_at: "2026-10-01T15:10:33.055275+00:00" };
    vi.mocked(existingCampaigns).mockResolvedValue(listed);
    openDialog(); await screen.findByText("已納入活動");
    expect(screen.getByText("開啟中 · 10/03 – 10/09")).not.toBeNull();
    expect(screen.getByText("平台狀態不明 · 開始日未知 – 結束日未知")).not.toBeNull();
    expect(screen.queryByText(/ACTIVE|WITH_ISSUES|2026-10-01T/)).toBeNull();
    const d = new Date("2026-10-01T15:10:33.055275+00:00"); const pad = (n: number) => String(n).padStart(2, "0");
    expect(screen.getByText(new RegExp(`最近成功：${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`))).not.toBeNull();
    expect(screen.getByText("已在工作區")).not.toBeNull();
    expect(screen.getAllByRole("button", { name: "納入並開啟" })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "打開" }));
    await waitFor(() => expect(screen.getByTestId("location").textContent).toBe("/brands/brand_1/ads/campaigns/cmp_in"));
    expect(importExisting).not.toHaveBeenCalled();
  });

  it("refresh 期間凍結帳號，離開後舊 refresh 不再啟動清單讀取", async () => {
    const refresh = deferred<Awaited<ReturnType<typeof refreshExisting>>>();
    vi.mocked(refreshExisting).mockReturnValue(refresh.promise);
    vi.mocked(existingCampaigns).mockImplementation(async (_brand, options) => options?.source_account === "202" ? page("202", ["乙活動"]) : page("101", ["甲活動"]));
    const mounted = openDialog(); await screen.findByText("甲活動"); fireEvent.click(screen.getByRole("button", { name: "更新清單" }));
    expect((screen.getByLabelText("品牌綁定帳號") as HTMLSelectElement).disabled).toBe(true);
    mounted.unmount();
    await act(async () => refresh.resolve({ job: { id: "old", status: "pending", last_success_at: null } }));
    expect(existingCampaigns).toHaveBeenCalledTimes(1);
  });

  it("unknown度量保持未知，購買收入與真正零值分開；同步失敗與涵蓋範圍獨立顯示", async () => {
    vi.mocked(externalView).mockResolvedValue(view({ observations: [{ id: "day_1", entity_id: "活動根", day: "2026-09-17", metric_scope: "ad", attribution_key: "7d_click", currency: "TWD", spend: 0, impressions: null, clicks: null, purchases: null, revenue: null, availability: {} }], sync: { structure: { status: "success", last_success_at: "2026-09-18" }, observations: { status: "error", error: "分頁失敗，保留上次資料" } }, coverage: { structure: { complete: true }, observations: null } }));
    render(<ExternalCampaignPanel brandId="brand_1" campaign={campaign()} onCampaignChange={vi.fn()} />);
    await screen.findByText("分頁失敗，保留上次資料");
    fireEvent.click(screen.getByText(/^原始成效 ·/));
    const row = screen.getByText("2026-09-17").closest("tr")!; const cells = within(row).getAllByRole("cell");
    expect(cells.slice(4).map(c => c.textContent)).toEqual(["0", "未知", "未知", "未知", "未知"]);
    expect(screen.queryByText(/資料涵蓋範圍：未知／尚未完整/)).not.toBeNull();
    expect(screen.queryByText(/原生結構：success/)).not.toBeNull();
  });

  it("總提示採用已保存的分區成功時間，即使原生節點沒有成功時間", async () => {
    vi.mocked(externalView).mockResolvedValue(view({ sync: {
      structure: { status: "success", last_success_at: "2026-09-18T01:00:00Z" },
      creatives: { status: "success", last_success_at: "2026-09-18T02:00:00Z" },
      observations: { status: "success", last_success_at: "2026-09-18T03:00:00Z" },
    } }));
    render(<ExternalCampaignPanel brandId="brand_1" campaign={campaign()} onCampaignChange={vi.fn()} />);
    expect(await screen.findByText(/^最近成功：2026-09-18T03:00:00Z/)).not.toBeNull();
    expect(screen.queryByText(/尚未成功讀回/)).toBeNull();
  });

  it("沒有分區成功時間時仍保留原生節點時間作補充", async () => {
    vi.mocked(externalView).mockResolvedValue(view({ entities: [{ ...entity("活動根"), last_success_at: "2026-09-17T01:00:00Z" }] }));
    render(<ExternalCampaignPanel brandId="brand_1" campaign={campaign()} onCampaignChange={vi.fn()} />);
    expect(await screen.findByText(/^最近成功：2026-09-17T01:00:00Z/)).not.toBeNull();
  });

  it("結構分頁不丟棄原有結構或另一維度的觀測", async () => {
    vi.mocked(externalView).mockResolvedValueOnce(view({ next_entity_cursor: "entity_2", observations: [{ id: "saved_day", entity_id: "活動根", day: "2026-09-16", metric_scope: "ad", attribution_key: "saved-window", currency: "TWD", spend: 30, impressions: 100, clicks: 2, purchases: null, revenue: null, availability: {} }] })).mockResolvedValueOnce(view({ entities: [entity("第二個原生節點")] }));
    render(<ExternalCampaignPanel brandId="brand_1" campaign={campaign()} onCampaignChange={vi.fn()} />);
    await screen.findByText(/活動 · 活動根/); fireEvent.click(screen.getByText(/^原生結構與預算/));
    fireEvent.click(screen.getByRole("button", { name: "載入更多結構" })); await screen.findByText(/第二個原生節點/);
    expect(screen.queryByText(/活動 · 活動根/)).not.toBeNull();
    expect(vi.mocked(externalView).mock.calls[1][2]).toEqual({ entity_cursor: "entity_2" });
    expect(screen.queryByText("saved-window")).not.toBeNull();
  });

  it("原生素材呈現圖片、影片縮圖、輪播與動態文字，影片不冒充可播放原檔", async () => {
    vi.mocked(externalView).mockResolvedValue(view({ entities: [
      { ...entity("image"), creative: { kind: "image", fields: { body: "原生圖片文案", image_url: "https://media.example/image.png" } } },
      { ...entity("video"), creative: { kind: "video", fields: { thumbnail_url: "https://media.example/video-thumb.png", object_story_spec: { video_data: { message: "原生影片文案", video_id: "v123" } } } } },
      { ...entity("carousel"), creative: { kind: "carousel", fields: { object_story_spec: { link_data: { child_attachments: [{ name: "輪播第一張", picture: "https://media.example/carousel.png" }] } } } } },
      { ...entity("dynamic"), creative: { kind: "dynamic", fields: { asset_feed_spec: { bodies: [{ text: "動態素材已讀文案" }], images: [{ hash: "no-public-url" }] } } } },
    ] }));
    const mounted = render(<ExternalCampaignPanel brandId="brand_1" campaign={campaign()} onCampaignChange={vi.fn()} />);
    await screen.findByText("內文：原生圖片文案"); fireEvent.click(screen.getByText(/^原生結構與預算/));
    expect(screen.getByRole("img", { name: "平台回傳圖片" }).getAttribute("src")).toBe("https://media.example/image.png");
    expect(screen.getByRole("img", { name: "平台素材縮圖" }).getAttribute("src")).toBe("https://media.example/video-thumb.png");
    expect(screen.queryByText(/影片原檔尚未取得/)).not.toBeNull();
    expect(mounted.container.querySelector("video")).toBeNull();
    expect(screen.queryByText("標題：輪播第一張")).not.toBeNull();
    expect(screen.getByRole("img", { name: "輪播 1 圖片" }).getAttribute("src")).toBe("https://media.example/carousel.png");
    expect(screen.queryByText("文案：動態素材已讀文案")).not.toBeNull();
    expect(screen.queryByText(/不代表每次實際曝光組合/)).not.toBeNull();
    expect(screen.queryByText(/僅有識別資料，未提供可查看圖片/)).not.toBeNull();
  });

  it("切換活動後，舊活動 saveGoal 的完成不得回填新的工作區", async () => {
    const pending = deferred<CampaignDetail>(); const changed = vi.fn(); vi.mocked(patchCampaign).mockReturnValue(pending.promise);
    const mounted = render(<ExternalCampaignPanel brandId="brand_1" campaign={campaign()} onCampaignChange={changed} />);
    await screen.findByText(/來源 meta/); fireEvent.click(screen.getByRole("button", { name: "儲存目標" }));
    mounted.rerender(<ExternalCampaignPanel brandId="brand_2" campaign={campaign("cmp_2")} onCampaignChange={changed} />);
    await act(async () => pending.resolve(campaign()));
    expect(changed).not.toHaveBeenCalled();
  });
});
