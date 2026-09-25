/** frontend/src/components/ads/flow/HandoffPage.test.tsx — F22-I03：`vi.mock` 掉
 * `@/lib/adsChangeApi`／`@/lib/adsTriageApi`，不打真的 API。覆蓋 Done 4：三種 kind 各自畫出對應
 * 手動步驟、「↗ 打開平台」沒有 `platform_url` 時退回複製編號、打勾狀態只在頁面上（不送後端）、
 * 「我做完了」依序呼叫 report／check 並導去核對結果（check 失敗仍導去）、走錯步驟自動導正、
 * 多項變更清單連去既有變更與核對。 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as changeApi from "@/lib/adsChangeApi";
import type { ChangeItem, ChangeSet } from "@/lib/adsChangeApi";
import * as triageApi from "@/lib/adsTriageApi";
import type { QueueItem, QueuePayload, TriageItem } from "@/lib/adsTriageApi";
import * as handoffApi from "@/lib/adsHandoffApi";
import * as externalApi from "@/lib/adsExternalApi";
import { HandoffPage } from "./HandoffPage";

vi.mock("@/lib/adsChangeApi", async (importOriginal) => ({
  ...(await importOriginal<typeof changeApi>()),
  getChangeControl: vi.fn(), actOnChangeItem: vi.fn(),
}));
vi.mock("@/lib/adsTriageApi", async (importOriginal) => ({
  ...(await importOriginal<typeof triageApi>()),
  getQueue: vi.fn(),
}));
// F27-I15: `new_ad`'s handoff step embeds `ManualHandoffPanel` (`NewAdHandoffPanel.tsx`), which
// calls these directly — mocked here purely so that branch mounts without hitting a real API,
// same mocks (and `useWorkspace` stand-in) `ManualHandoffPanel.test.tsx` already uses.
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "user:org" }) }));
vi.mock("@/lib/adsHandoffApi", async (importOriginal) => ({
  ...(await importOriginal<typeof handoffApi>()),
  getHandoff: vi.fn(),
}));
vi.mock("@/lib/adsExternalApi", async (importOriginal) => ({
  ...(await importOriginal<typeof externalApi>()),
  existingCampaigns: vi.fn(), externalView: vi.fn(),
}));

function triage(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "aex_1", native_id: "native_1", name: "1150706 健身情境單圖", campaign_id: "cmp_1",
    campaign_name: "【銷售】測試活動", thumbnail_url: null, class: "stop_loss", label: "停損",
    reason_code: "spend_over_stop_loss",
    grade: "wasted", grade_label: "沒賣出", previous_grade: null, grade_move: null,
    window: { start: "2026-08-25", end: "2026-09-21", days: 9, previous_start: "2026-07-28", previous_end: "2026-08-24", extended_from: null },
    target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: 1420, result_count: 0, cost_per_result: null, result_kind: null, result_label: "成果", derived_zero_days: 0, reason: null },
    previous: { spend: null, result_count: null, cost_per_result: null, result_kind: null, result_label: "成果", derived_zero_days: 0, reason: null },
    change_pct: null,
    sample: { gate: false, spend_multiple: null, days_with_events: 0 },
    ...overrides,
  };
}
function queueItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    id: "int_1", org_id: "org_1", brand_id: "brd_1", campaign_period_id: null,
    dedupe_key: "k1", category: "ads_triage_stop_loss", kind: null, severity: "money_loss",
    message: "m", action_url: null, visible_from: null, status: "open",
    created_at: "2026-09-22T00:00:00Z", resolved_at: null, kind_key: "stop_loss",
    triage: triage(), proposal: null,
    ...overrides,
  };
}
function queue(items: QueueItem[] = []): QueuePayload {
  return { items, counts: { stop_loss: items.length, worse: 0, better: 0, flat: 0, insufficient: 0, no_target: 0 }, total_ads: items.length, kinds_available: ["stop_loss"], kinds_pending: [] };
}
function changeItem(overrides: Partial<ChangeItem> = {}): ChangeItem {
  return {
    id: "item_1", kind: "pause", target_id: "aex_1",
    target: { id: "aex_1", name: "1150706 健身情境單圖", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "native_1" },
    before: { status: "PAUSED" }, after: { status: "PAUSED" }, reason: "花費超過停損線（目標 × 3）仍未達成目標",
    verification_state: "pending", evidence_json: {}, reported_at: null, first_observed_at: null, verified_at: null,
    platform_url: "https://adsmanager.facebook.com/adsmanager/manage/ads?act=1&selected_ad_ids=native_1",
    ...overrides,
  };
}
function changeSet(overrides: Partial<ChangeSet> = {}): ChangeSet {
  return {
    id: "acs_1", campaign_id: "cmp_1", title: "暫停「1150706 健身情境單圖」", month: "2026-09",
    operation_id: "op_1", content_hash: "hash_1", status: "approved", reason: null, revisit_at: null,
    approval_id: "apv_1", created_at: "2026-09-21T00:00:00Z", approved_at: "2026-09-21T00:00:00Z", items: [changeItem()],
    can_revise: false,
    ...overrides,
  };
}

function HandoffRoute() {
  const { brandId, campaignId, setId } = useParams<{ brandId: string; campaignId: string; setId: string }>();
  return <HandoffPage brandId={brandId ?? ""} campaignId={campaignId ?? ""} setId={setId ?? ""} />;
}
function LocationProbe() {
  return <p data-testid="probe-path">{useLocation().pathname}</p>;
}
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/brands/:brandId/ads/campaigns/:campaignId/changes/:setId/handoff" element={<HandoffRoute />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}
const handoffPath = (id = "acs_1") => `/brands/brd_1/ads/campaigns/cmp_1/changes/${id}/handoff`;

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem()]));
  vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [changeSet()] });
});

describe("HandoffPage（F22-I03）三種 kind", () => {
  it("pause：打開平台＋我關了兩個手動步驟", async () => {
    renderAt(handoffPath());
    expect(await screen.findByText("打開平台上的這則廣告")).toBeTruthy();
    expect(screen.getByText("把這則廣告的開關關掉")).toBeTruthy();
    const link = screen.getByRole("link", { name: "↗ 打開平台" }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe(changeItem().platform_url);
    expect(link.getAttribute("target")).toBe("_blank");
    expect(screen.getByRole("button", { name: "我關了" })).toBeTruthy();
    expect(screen.getByText("回來按「我做完了」")).toBeTruthy();
    expect(screen.getByText("第 1 件／共 1 件")).toBeTruthy();
  });

  it("copy：先複製新文案，再到平台貼上，並有看舊文案的收合", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        kind: "copy", before: { title: "舊標題", body: "舊內文" }, after: { title: "新標題", body: "新內文" },
      })] })],
    });
    renderAt(handoffPath());
    expect(await screen.findByText("複製新文案")).toBeTruthy();
    expect(screen.getByText("新標題")).toBeTruthy();
    expect(screen.getByRole("button", { name: "複製標題" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "複製內文" })).toBeTruthy();
    expect(screen.getByText("在平台編輯這則廣告，貼上")).toBeTruthy();
    expect(screen.queryByText("舊標題")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "看舊文案" }));
    expect(screen.getByText("舊標題")).toBeTruthy();
  });

  it("budget：打開平台後複製每日預算金額", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        kind: "budget", before: { daily_amount: 1000 }, after: { daily_amount: 1200 },
        target: { id: "adset_1", name: "日常商品推廣・轉換", platform: "meta", source_account: "acc_1", native_kind: "adset", native_id: "native_adset_1" },
      })] })],
    });
    renderAt(handoffPath());
    expect(await screen.findByText("打開平台上的「日常商品推廣・轉換」")).toBeTruthy();
    expect(screen.getByText("1,200")).toBeTruthy();
    expect(screen.getByRole("button", { name: "複製金額" })).toBeTruthy();
  });
});

describe("HandoffPage（F22-I03）沒有 platform_url 時退回複製編號", () => {
  it("換成標的名稱＋原生編號＋複製編號按鈕，沒有「打開平台」連結", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({ platform_url: null })] })],
    });
    renderAt(handoffPath());
    await screen.findByText("打開平台上的這則廣告");
    expect(screen.queryByRole("link", { name: "↗ 打開平台" })).toBeNull();
    expect(screen.getByText("1150706 健身情境單圖")).toBeTruthy();
    expect(screen.getByText("native_1")).toBeTruthy();
    expect(screen.getByRole("button", { name: "複製編號" })).toBeTruthy();
  });
});

describe("HandoffPage（F22-I03）打勾狀態只在頁面上", () => {
  it("按「我關了」把第二步標成已完成", async () => {
    const user = userEvent.setup();
    renderAt(handoffPath());
    await screen.findByText("把這則廣告的開關關掉");
    expect(screen.queryByLabelText("已完成")).toBeNull();
    await user.click(screen.getByRole("button", { name: "我關了" }));
    expect(screen.getByLabelText("已完成")).toBeTruthy();
  });
});

describe("HandoffPage（F22-I03）我做完了，開始核對", () => {
  it("依序呼叫 report、check，成功後導去核對結果", async () => {
    const user = userEvent.setup();
    vi.mocked(changeApi.actOnChangeItem)
      .mockResolvedValueOnce(changeSet({ items: [changeItem({ verification_state: "reported" })] }))
      .mockResolvedValueOnce(changeSet({ items: [changeItem({ verification_state: "confirmed", reported_at: "2026-09-22T00:00:00Z" })] }));
    renderAt(handoffPath());
    await user.click(await screen.findByRole("button", { name: "我做完了，開始核對 →" }));
    await waitFor(() => expect(changeApi.actOnChangeItem).toHaveBeenCalledTimes(2));
    expect(vi.mocked(changeApi.actOnChangeItem).mock.calls[0]).toEqual(["brd_1", "cmp_1", "acs_1", "item_1", "report"]);
    expect(vi.mocked(changeApi.actOnChangeItem).mock.calls[1]).toEqual(["brd_1", "cmp_1", "acs_1", "item_1", "check"]);
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/verify"));
  });

  it("report 成功但 check 失敗仍然導去核對結果（那裡顯示核對中）", async () => {
    const user = userEvent.setup();
    vi.mocked(changeApi.actOnChangeItem)
      .mockResolvedValueOnce(changeSet({ items: [changeItem({ verification_state: "reported" })] }))
      .mockRejectedValueOnce(new Error("未收到伺服器回應，結果尚未確認。請沿用原操作重試，不要重做平台操作。"));
    renderAt(handoffPath());
    await user.click(await screen.findByRole("button", { name: "我做完了，開始核對 →" }));
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/verify"));
  });

  it("report 失敗留在頁面上並顯示錯誤，不呼叫 check", async () => {
    const user = userEvent.setup();
    vi.mocked(changeApi.actOnChangeItem).mockRejectedValueOnce(new Error("目前無法完成，已保存的內容會保留。請稍後重試。"));
    renderAt(handoffPath());
    await user.click(await screen.findByRole("button", { name: "我做完了，開始核對 →" }));
    expect(await screen.findByText("目前無法完成，已保存的內容會保留。請稍後重試。")).toBeTruthy();
    expect(changeApi.actOnChangeItem).toHaveBeenCalledTimes(1);
  });
});

describe("HandoffPage（F22-I03）步驟導正與例外", () => {
  it("清單還是草稿，導去確認提議頁", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ status: "draft", approved_at: null, items: [changeItem({ verification_state: "pending", reported_at: null })] })],
    });
    renderAt(handoffPath());
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/confirm"));
  });

  it("已經回報過，導去核對結果頁", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({ verification_state: "confirmed", reported_at: "2026-09-21T01:00:00Z" })] })],
    });
    renderAt(handoffPath());
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/verify"));
  });

  it("多項變更的清單連去既有變更與核對", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem(), changeItem({ id: "item_2", target_id: "aex_2" })] })],
    });
    renderAt(handoffPath());
    expect(await screen.findByText("這份清單有多項變更")).toBeTruthy();
    const link = screen.getByRole("link", { name: "前往變更與核對" }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toContain("tab=changes");
  });

  it("找不到這份變更清單", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [] });
    renderAt(handoffPath());
    expect(await screen.findByText("找不到這份變更清單")).toBeTruthy();
  });
});

describe("HandoffPage（F27-I15）new_ad kind：嵌入既有的 ManualHandoffPanel", () => {
  it("畫出交接面板，「看目前核對結果」重新讀取清單", async () => {
    const user = userEvent.setup();
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({ id: "item_new", kind: "new_ad", target_id: "plc_1" })] })],
    });
    vi.mocked(handoffApi.getHandoff).mockResolvedValue({
      items: [], items_truncated: false, ready_placements: [], destinations: [], destinations_truncated: false,
      launch_stale: null, notice: "物件存在、設定相符與素材核對分別記錄；人工交接不代表平台已投遞。",
    });
    vi.mocked(externalApi.existingCampaigns).mockResolvedValue({ items: [], sources: [], next_cursor: null, job: null });
    vi.mocked(externalApi.externalView).mockResolvedValue({
      entities: [], observations: [], next_entity_cursor: null, next_observation_cursor: null,
      window: { start: "2026-09-01", end: "2026-09-21" }, connections: [], sync: {}, coverage: {},
    });
    renderAt(handoffPath());
    expect(await screen.findByText("人工交接與平台核對")).toBeTruthy();
    expect(await screen.findByText(/物件存在、設定相符與素材核對分別記錄/)).toBeTruthy();
    expect(changeApi.getChangeControl).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "看目前核對結果 →" }));
    await waitFor(() => expect(changeApi.getChangeControl).toHaveBeenCalledTimes(2));
  });
});

describe("HandoffPage（F27-I15 Contract F）cleanup kind", () => {
  function cleanupChangeSet(): ChangeSet {
    return changeSet({
      items: [
        changeItem({ id: "item_low1", target_id: "aex_low1", target: { id: "aex_low1", name: "1150701 情境圖 A", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "native_low1" }, platform_url: "https://adsmanager.facebook.com/x?id=low1" }),
        changeItem({ id: "item_low2", target_id: "aex_low2", target: { id: "aex_low2", name: "1150702 情境圖 B", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "native_low2" }, platform_url: null }),
      ],
    });
  }
  const CLEANUP_KIND = "cleanup" as unknown as QueueItem["kind_key"];
  function cleanupQueueItem(): QueueItem {
    return queueItem({
      kind_key: CLEANUP_KIND, category: "ads_triage_cleanup",
      proposal: { kind: "cleanup", change_set_id: "acs_1", campaign_id: "cmp_1", status: "approved", verification_state: "pending", reason: null, revisit_at: null, multi: true },
    });
  }

  it("一則廣告一個 TodoRow，各自的打開平台按鈕", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem()]));
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [cleanupChangeSet()] });
    renderAt(handoffPath());
    expect(await screen.findByText(/打開平台上的「1150701 情境圖 A」，把開關關掉/)).toBeTruthy();
    expect(screen.getByText(/打開平台上的「1150702 情境圖 B」，把開關關掉/)).toBeTruthy();
    const opened = screen.getAllByRole("link", { name: "↗ 打開平台" });
    expect(opened).toHaveLength(1);
    expect((opened[0] as HTMLAnchorElement).getAttribute("href")).toBe("https://adsmanager.facebook.com/x?id=low1");
    expect(screen.getByRole("button", { name: "複製編號" })).toBeTruthy();
    expect(screen.getByText("native_low2")).toBeTruthy();
  });

  it("F28-I14：四步驟 提議／確認／到平台完成／核對結果，目前在第三步，確認可回去", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem()]));
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [cleanupChangeSet()] });
    renderAt(handoffPath());
    const current = await screen.findByRole("listitem", { current: "step" });
    const labels = screen.getAllByRole("listitem").map((li) => li.textContent?.replace(/^\d/, ""));
    expect(labels).toEqual(["提議", "確認", "到平台完成", "核對結果"]);
    expect(current.textContent).toContain("到平台完成");
    expect(screen.queryByText("確認提議")).toBeNull();
    expect(screen.getByRole("link", { name: "回到確認" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/confirm");
    expect(screen.queryByRole("link", { name: "回到提議" })).toBeNull();
  });

  it("「我都做完了」依序對每一則呼叫 report／check，成功後導去核對結果", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem()]));
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [cleanupChangeSet()] });
    vi.mocked(changeApi.actOnChangeItem)
      .mockResolvedValueOnce(cleanupChangeSet())
      .mockResolvedValueOnce(cleanupChangeSet())
      .mockResolvedValueOnce(cleanupChangeSet())
      .mockResolvedValueOnce(changeSet({
        items: [
          changeItem({ id: "item_low1", target_id: "aex_low1", verification_state: "confirmed", reported_at: "2026-09-22T00:00:00Z" }),
          changeItem({ id: "item_low2", target_id: "aex_low2", verification_state: "confirmed", reported_at: "2026-09-22T00:00:00Z" }),
        ],
      }));
    renderAt(handoffPath());
    await user.click(await screen.findByRole("button", { name: "我都做完了，開始核對 →" }));
    await waitFor(() => expect(changeApi.actOnChangeItem).toHaveBeenCalledTimes(4));
    expect(vi.mocked(changeApi.actOnChangeItem).mock.calls[0]).toEqual(["brd_1", "cmp_1", "acs_1", "item_low1", "report"]);
    expect(vi.mocked(changeApi.actOnChangeItem).mock.calls[1]).toEqual(["brd_1", "cmp_1", "acs_1", "item_low1", "check"]);
    expect(vi.mocked(changeApi.actOnChangeItem).mock.calls[2]).toEqual(["brd_1", "cmp_1", "acs_1", "item_low2", "report"]);
    expect(vi.mocked(changeApi.actOnChangeItem).mock.calls[3]).toEqual(["brd_1", "cmp_1", "acs_1", "item_low2", "check"]);
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/verify"));
  });
});

// F29-I10 Contract K: the queue is context on this step; its failure is said out loud (ReadFailed + 重試) and never
// changes what the step is — a cleanup set names itself (`source: "cleanup"`).
describe("HandoffPage（F29-I10）佇列讀取失敗", () => {
  it("單項清單：步驟照舊，只多一塊讀取失敗；重試重讀佇列後補回「第幾件」", async () => {
    vi.mocked(triageApi.getQueue).mockReset();
    vi.mocked(triageApi.getQueue).mockRejectedValueOnce(new Error("queue down")).mockResolvedValueOnce(queue([queueItem()]));
    renderAt(handoffPath());
    expect(await screen.findByText(/待決定清單讀不到/)).toBeTruthy();
    expect(screen.getByText("打開平台上的這則廣告")).toBeTruthy();
    expect(screen.queryByText("第 1 件／共 1 件")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByText("第 1 件／共 1 件")).toBeTruthy();
    expect(screen.queryByText(/待決定清單讀不到/)).toBeNull();
    expect(triageApi.getQueue).toHaveBeenCalledTimes(2);
  });

  it("清理清單（source: cleanup）：佇列讀不到仍畫逐則步驟，不說「多項變更」", async () => {
    vi.mocked(triageApi.getQueue).mockRejectedValue(new Error("queue down"));
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({
        source: "cleanup",
        items: [
          changeItem({ id: "item_low1", target_id: "aex_low1", target: { id: "aex_low1", name: "1150701 情境圖 A", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "native_low1" } }),
          changeItem({ id: "item_low2", target_id: "aex_low2", target: { id: "aex_low2", name: "1150702 情境圖 B", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "native_low2" } }),
        ],
      })],
    });
    renderAt(handoffPath());
    expect(await screen.findByText(/打開平台上的「1150701 情境圖 A」，把開關關掉/)).toBeTruthy();
    expect(screen.queryByText("這份清單有多項變更")).toBeNull();
    expect(screen.getByText(/待決定清單讀不到/)).toBeTruthy();
  });

  it("已核准的步驟不給「先不要」出口（出口只在還沒決定時）", async () => {
    renderAt(handoffPath());
    expect(await screen.findByText("打開平台上的這則廣告")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /先不要，回投放中心/ })).toBeNull();
  });
});
