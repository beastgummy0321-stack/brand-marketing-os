/** frontend/src/components/ads/flow/VerifyPage.test.tsx — F22-I04：`vi.mock` 掉
 * `@/lib/adsChangeApi`／`@/lib/adsTriageApi`，不打真的 API。覆蓋 Done 3：confirmed／deviated／
 * stale／pending(reported_at 已寫)／reported+unknown 五種畫面、「重新核對」呼叫 check、
 * 「下一件」找佇列裡下一個還沒完成的項目、走錯步驟自動導正、多項變更清單連去既有變更與核對。 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as changeApi from "@/lib/adsChangeApi";
import type { ChangeItem, ChangeSet } from "@/lib/adsChangeApi";
import * as triageApi from "@/lib/adsTriageApi";
import type { QueueItem, QueuePayload, QueueScale, QueueRefresh, TriageItem } from "@/lib/adsTriageApi";
import { VerifyPage } from "./VerifyPage";

vi.mock("@/lib/adsChangeApi", async (importOriginal) => ({
  ...(await importOriginal<typeof changeApi>()),
  getChangeControl: vi.fn(), actOnChangeItem: vi.fn(),
}));
vi.mock("@/lib/adsTriageApi", async (importOriginal) => ({
  ...(await importOriginal<typeof triageApi>()),
  getQueue: vi.fn(),
}));

function triage(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "aex_1", native_id: "native_1", name: "1150706 健身情境單圖", campaign_id: "cmp_1",
    campaign_name: "【銷售】測試活動", thumbnail_url: null, class: "stop_loss", label: "停損",
    reason_code: "spend_over_stop_loss",
    grade: "wasted", grade_label: "白花",
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
function scale(overrides: Partial<QueueScale> = {}): QueueScale {
  return {
    owner: { id: "aex_owner_G", name: "廣告組 G・廣泛受眾", native_kind: "adset", native_id: "23851", ads_count: 8, currency: "TWD" },
    from: 1000, to: 1200, cost_per_result: 306, previous_cost_per_result: 330,
    target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
    window_days: 14, month: { available: 10000, extra_needed: 1800 },
    ...overrides,
  };
}
function refresh(overrides: Partial<QueueRefresh> = {}): QueueRefresh {
  return { campaign_id: "cmp_3", campaign_name: "【銷售】測試活動三", readable_count: 2, classified_count: 9, thumbnails: [null, null], ...overrides };
}
function changeItem(overrides: Partial<ChangeItem> = {}): ChangeItem {
  return {
    id: "item_1", kind: "pause", target_id: "aex_1",
    target: { id: "aex_1", name: "1150706 健身情境單圖", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "native_1" },
    before: { status: "PAUSED" }, after: { status: "PAUSED" }, reason: "花費超過停損線（目標 × 3）仍未達成目標",
    verification_state: "confirmed", evidence_json: { setting_matches: true, observed_at: "2026-09-22T02:13:00Z" },
    reported_at: "2026-09-22T02:00:00Z", first_observed_at: "2026-09-22T02:13:00Z", verified_at: "2026-09-22T02:13:00Z",
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

function VerifyRoute() {
  const { brandId, campaignId, setId } = useParams<{ brandId: string; campaignId: string; setId: string }>();
  return <VerifyPage brandId={brandId ?? ""} campaignId={campaignId ?? ""} setId={setId ?? ""} />;
}
function LocationProbe() {
  return <p data-testid="probe-path">{useLocation().pathname}</p>;
}
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/brands/:brandId/ads/campaigns/:campaignId/changes/:setId/verify" element={<VerifyRoute />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}
const verifyPath = (id = "acs_1") => `/brands/brd_1/ads/campaigns/cmp_1/changes/${id}/verify`;

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(triageApi.getQueue).mockResolvedValue(queue([queueItem()]));
  vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [changeSet()] });
});

describe("VerifyPage（F22-I04）confirmed", () => {
  it("pause：已核對 hero、設定相符 rail、讀回時間、沒有下一件時回投放中心", async () => {
    renderAt(verifyPath());
    expect(await screen.findByText("平台上這則廣告已經關閉")).toBeTruthy();
    expect(screen.getByText(/讀回於/)).toBeTruthy();
    expect(screen.getByText("✓ 設定相符")).toBeTruthy();
    expect(screen.getByText("狀態：暫停")).toBeTruthy();
    // F27-I16 Contract H/D：沒有 `timeline`／`learning`（既有 factory 沒帶這兩個欄位）當作
    // 「還不知道」，跟「明天確認」／「沒標主打，未記入」畫同一格，不是省略整格。
    expect(screen.getByText("花費停止")).toBeTruthy();
    expect(screen.getByText("明天確認")).toBeTruthy();
    expect(screen.getByText("品牌學習")).toBeTruthy();
    expect(screen.getByText("沒標主打，未記入")).toBeTruthy();
    expect(screen.getByRole("button", { name: "⟳ 重新核對" })).toBeTruthy();
    const home = screen.getByRole("link", { name: "回投放中心 →" }) as HTMLAnchorElement;
    expect(home.getAttribute("href")).toBe("/brands/brd_1/ads");
  });

  it("pause：花費真的停止＋已記入品牌學習時，rail 顯示 ✓ 並附上完整品牌學習卡", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        timeline: { spend_stopped: true, delivery_started: null, next_review_at: null },
        learning: { recorded: true, confidence: "observed", count: 1 },
        angle: "日常出發情境",
      } as Partial<ChangeItem> & { angle: string })] })],
    });
    renderAt(verifyPath());
    await screen.findByText("平台上這則廣告已經關閉");
    expect(screen.getByText("✓ 花費停止")).toBeTruthy();
    expect(screen.getByText("已確認停止")).toBeTruthy();
    expect(screen.getByText("✓ 已記入品牌學習")).toBeTruthy();
    expect(screen.getByText("第 1 次觀察")).toBeTruthy();
    expect(screen.getByText("「日常出發情境」對這群受眾無效")).toBeTruthy();
    expect(screen.getByText("觀察到")).toBeTruthy();
    expect(screen.getByText(/再出現 1 次同方向結果會升為「可能成立」/)).toBeTruthy();
  });

  it("pause：已成立（count 3）不再顯示升級提示", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        learning: { recorded: true, confidence: "validated", count: 3 },
        angle: "日常出發情境",
      } as Partial<ChangeItem> & { angle: string })] })],
    });
    renderAt(verifyPath());
    await screen.findByText("平台上這則廣告已經關閉");
    expect(screen.getByText("成立")).toBeTruthy();
    expect(screen.getByText("下次規劃素材時會避開")).toBeTruthy();
    expect(screen.queryByText(/再出現/)).toBeNull();
  });

  it("budget：學習期固定文字＋成效回看讀 timeline.next_review_at", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        kind: "budget", before: { daily_amount: 1000 }, after: { daily_amount: 1200 },
        timeline: { spend_stopped: null, delivery_started: null, next_review_at: "2026-09-25" },
      })] })],
    });
    renderAt(verifyPath());
    await screen.findByText("平台上的每日預算已經是 1,200");
    expect(screen.getByText("學習期")).toBeTruthy();
    expect(screen.getByText("3–5 天")).toBeTruthy();
    expect(screen.getByText("成效回看")).toBeTruthy();
    expect(screen.getByText("9/25")).toBeTruthy();
  });

  it("copy：開始投遞＋成效累積，未讀到 delivery 前不是 ok", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        kind: "copy", before: { title: "舊標題", body: "舊內文" }, after: { title: "新標題", body: "新內文" },
        timeline: { spend_stopped: null, delivery_started: false, next_review_at: "2026-09-29" },
      })] })],
    });
    renderAt(verifyPath());
    await screen.findByText("平台上的文案和你核准的一樣");
    expect(screen.getByText("開始投遞")).toBeTruthy();
    expect(screen.getByText("等待中")).toBeTruthy();
    expect(screen.getByText("成效累積")).toBeTruthy();
    expect(screen.getByText("9/29 自動重看")).toBeTruthy();
    expect(screen.queryByText("✓ 開始投遞")).toBeNull();
  });

  it("有下一件開放項目時，主按鈕變成下一件", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([
      queueItem(),
      queueItem({ id: "int_2", triage: triage({ entity_id: "aex_2", campaign_id: "cmp_2" }), proposal: null }),
    ]));
    renderAt(verifyPath());
    const next = await screen.findByRole("link", { name: "下一件 →" });
    expect((next as HTMLAnchorElement).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_2/propose/pause/aex_2");
  });

  it("下一件跨到 scale_budget（F25-I03）：還沒建草稿時連去 propose/budget", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([
      queueItem(),
      queueItem({
        id: "int_2", kind_key: "scale_budget",
        triage: triage({ entity_id: "aex_2", campaign_id: "cmp_2", class: "better" }),
        proposal: null, scale: scale(),
      }),
    ]));
    renderAt(verifyPath());
    const next = await screen.findByRole("link", { name: "下一件 →" });
    expect((next as HTMLAnchorElement).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_2/propose/budget/aex_owner_G");
  });

  it("下一件跨到 refresh_creative（F25-I03）：連去素材工作檯", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([
      queueItem(),
      queueItem({
        id: "int_3", kind_key: "refresh_creative",
        triage: triage({ entity_id: "aex_3", campaign_id: "cmp_3", class: "flat" }),
        proposal: null, refresh: refresh(),
      }),
    ]));
    renderAt(verifyPath());
    const next = await screen.findByRole("link", { name: "下一件 →" });
    expect((next as HTMLAnchorElement).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_3?tab=assets&material_new=1");
  });

  it("已完成的下一項不會被當成下一件（isQueueItemDone）", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([
      queueItem(),
      queueItem({
        id: "int_2", triage: triage({ entity_id: "aex_2", campaign_id: "cmp_2" }),
        proposal: { change_set_id: "acs_2", campaign_id: "cmp_2", kind: "pause", status: "approved", verification_state: "confirmed", reason: null, revisit_at: null, multi: false },
      }),
    ]));
    renderAt(verifyPath());
    await screen.findByText("平台上這則廣告已經關閉");
    expect(screen.getByRole("link", { name: "回投放中心 →" })).toBeTruthy();
  });

  it("copy：文案相符文字＋標題內文格", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        kind: "copy", before: { title: "舊標題", body: "舊內文" }, after: { title: "新標題", body: "新內文" },
      })] })],
    });
    renderAt(verifyPath());
    expect(await screen.findByText("平台上的文案和你核准的一樣")).toBeTruthy();
    expect(screen.getByText("標題、內文")).toBeTruthy();
  });

  it("budget：每日預算金額文字", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        kind: "budget", before: { daily_amount: 1000 }, after: { daily_amount: 1200 },
      })] })],
    });
    renderAt(verifyPath());
    expect(await screen.findByText("平台上的每日預算已經是 1,200")).toBeTruthy();
    expect(screen.getByText("每日 1,200")).toBeTruthy();
  });

  it("按重新核對呼叫 check 並用回傳更新畫面", async () => {
    const user = userEvent.setup();
    vi.mocked(changeApi.actOnChangeItem).mockResolvedValueOnce(
      changeSet({ items: [changeItem({ evidence_json: { setting_matches: true, observed_at: "2026-09-22T05:00:00Z" } })] }),
    );
    renderAt(verifyPath());
    await user.click(await screen.findByRole("button", { name: "⟳ 重新核對" }));
    await waitFor(() => expect(changeApi.actOnChangeItem).toHaveBeenCalledWith("brd_1", "cmp_1", "acs_1", "item_1", "check"));
  });

  it("重新核對失敗顯示錯誤", async () => {
    const user = userEvent.setup();
    vi.mocked(changeApi.actOnChangeItem).mockRejectedValueOnce(new Error("目前無法完成，已保存的內容會保留。請稍後重試。"));
    renderAt(verifyPath());
    await user.click(await screen.findByRole("button", { name: "⟳ 重新核對" }));
    expect(await screen.findByText("目前無法完成，已保存的內容會保留。請稍後重試。")).toBeTruthy();
  });
});

describe("VerifyPage（F22-I04）deviated", () => {
  it("pause：核准與平台目前的狀態對照，主按鈕回平台改成核准內容", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        verification_state: "deviated",
        evidence_json: { observed_at: "2026-09-22T05:00:00Z", observed: { status: "ACTIVE" } },
      })] })],
    });
    renderAt(verifyPath());
    expect(await screen.findByText("平台上的狀態和核准的不一樣")).toBeTruthy();
    expect(screen.getByText("狀態：暫停")).toBeTruthy();
    expect(screen.getByText("狀態：啟用")).toBeTruthy();
    const link = screen.getByRole("link", { name: "回平台改成核准內容 →" }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/handoff");
  });

  it("copy：逐行標記平台目前跟核准內容不同的地方", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        kind: "copy", before: { title: "舊標題", body: "舊內文" }, after: { title: "新標題", body: "行一\n行二" },
        verification_state: "deviated",
        evidence_json: { observed_at: "2026-09-22T05:00:00Z", observed: { title: "新標題", body: "行一\n改過的行二" } },
      })] })],
    });
    renderAt(verifyPath());
    expect(await screen.findByText("平台上的內文和核准的不一樣")).toBeTruthy();
    expect(screen.getByText("改過的行二")).toBeTruthy();
  });

  it("copy：有 review_id 時多一顆「改用平台現在的內容」連去改文案頁並帶 prefill/set", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({
        review_id: "arv_1",
        items: [changeItem({
          kind: "copy", before: { title: "舊標題", body: "舊內文" }, after: { title: "新標題", body: "行一\n行二" },
          verification_state: "deviated",
          evidence_json: { observed_at: "2026-09-22T05:00:00Z", observed: { title: "新標題", body: "行一\n改過的行二" } },
        })],
      })],
    });
    renderAt(verifyPath());
    await screen.findByText("平台上的內文和核准的不一樣");
    const link = screen.getByRole("link", { name: "改用平台現在的內容" }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1/copy?prefill=observed&set=acs_1");
  });

  it("copy：沒有 review_id 就不畫「改用平台現在的內容」", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        kind: "copy", before: { title: "舊標題", body: "舊內文" }, after: { title: "新標題", body: "行一\n行二" },
        verification_state: "deviated",
        evidence_json: { observed_at: "2026-09-22T05:00:00Z", observed: { title: "新標題", body: "行一\n改過的行二" } },
      })] })],
    });
    renderAt(verifyPath());
    await screen.findByText("平台上的內文和核准的不一樣");
    expect(screen.queryByRole("link", { name: "改用平台現在的內容" })).toBeNull();
  });
});

describe("VerifyPage（F22-I04）stale", () => {
  it("pause：原核准不再適用，重新檢討去 propose 路由", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        verification_state: "stale", stale_reason: "廣告已經被刪除",
      })] })],
    });
    renderAt(verifyPath());
    expect(await screen.findByText("這則廣告的設定變了，原本的核准不再適用")).toBeTruthy();
    expect(screen.getByText("廣告已經被刪除")).toBeTruthy();
    const link = screen.getByRole("link", { name: "重新檢討 →" }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/propose/pause/aex_1");
  });

  it("budget：重新檢討去活動的變更與核對", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        kind: "budget", verification_state: "stale", evidence_json: { message: "預算條件已改變" },
      })] })],
    });
    renderAt(verifyPath());
    await screen.findByText("這則廣告的設定變了，原本的核准不再適用");
    expect(screen.getByText("預算條件已改變")).toBeTruthy();
    const link = screen.getByRole("link", { name: "重新檢討 →" }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toContain("tab=changes");
  });
});

describe("VerifyPage（F22-I04）pending（reported_at 已寫）", () => {
  it("平台上還是原本的設定，主按鈕回平台完成", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        verification_state: "pending", reported_at: "2026-09-22T02:00:00Z",
        evidence_json: { message: "平台仍是變更前設定，這項操作尚未完成。" },
      })] })],
    });
    renderAt(verifyPath());
    expect(await screen.findByText("平台上還是原本的設定")).toBeTruthy();
    expect(screen.getByText("平台仍是變更前設定，這項操作尚未完成。")).toBeTruthy();
    const link = screen.getByRole("link", { name: "回平台完成 →" }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/handoff");
    expect(screen.getByRole("button", { name: "⟳ 重新核對" })).toBeTruthy();
  });
});

describe("VerifyPage（F22-I04）reported／unknown", () => {
  it("reported：核對中，只有重新核對可按", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        verification_state: "reported", reported_at: "2026-09-22T02:00:00Z", evidence_json: {},
      })] })],
    });
    renderAt(verifyPath());
    expect(await screen.findByText("還沒讀到平台上的新設定")).toBeTruthy();
    expect(screen.getByText("稍後重新核對即可。")).toBeTruthy();
    expect(screen.getByRole("button", { name: "⟳ 重新核對" })).toBeTruthy();
    expect(screen.queryByRole("link", { name: /回投放中心|下一件/ })).toBeNull();
  });

  it("unknown：核對中，顯示 evidence_json.message", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        verification_state: "unknown", reported_at: "2026-09-22T02:00:00Z",
        evidence_json: { message: "核對期間有其他設定同步，保留較新資料；稍後重新核對即可，無需重複核准。" },
      })] })],
    });
    renderAt(verifyPath());
    expect(await screen.findByText("還沒讀到平台上的新設定")).toBeTruthy();
    expect(screen.getByText("核對期間有其他設定同步，保留較新資料；稍後重新核對即可，無需重複核准。")).toBeTruthy();
  });
});

describe("VerifyPage（F22-I04）步驟導正與例外", () => {
  it("還沒回報過（pending 且 reported_at 是 null），導去到平台完成頁", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({ verification_state: "pending", reported_at: null })] })],
    });
    renderAt(verifyPath());
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/handoff"));
  });

  it("清單還是草稿，導去確認提議頁", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ status: "draft", approved_at: null, items: [changeItem({ verification_state: "pending", reported_at: null })] })],
    });
    renderAt(verifyPath());
    await waitFor(() => expect(screen.getByTestId("probe-path").textContent).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/confirm"));
  });

  it("多項變更的清單連去既有變更與核對", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem(), changeItem({ id: "item_2", target_id: "aex_2" })] })],
    });
    renderAt(verifyPath());
    expect(await screen.findByText("這份清單有多項變更")).toBeTruthy();
    const link = screen.getByRole("link", { name: "前往變更與核對" }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toContain("tab=changes");
  });

  it("找不到這份變更清單", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [] });
    renderAt(verifyPath());
    expect(await screen.findByText("找不到這份變更清單")).toBeTruthy();
  });
});

describe("VerifyPage（F27-I15）new_ad kind", () => {
  function newAdItem(overrides: Partial<ChangeItem> = {}): ChangeItem {
    return changeItem({
      id: "item_new", kind: "new_ad", target_id: "plc_1",
      target: { id: "plc_1", name: "1150710 夏季新裝（新廣告）", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "native_new_1" },
      before: {}, after: { daily_amount: 0 },
      evidence_json: { setting_matches: true, observed_at: "2026-09-22T02:13:00Z", message: "本次讀回設定符合清單；不代表已開始投遞或已有足夠成效。" },
      ...overrides,
    });
  }
  it("已核對：平台上這則新廣告已經核對完成，rail 顯示已對應廣告物件", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [changeSet({ items: [newAdItem()] })] });
    renderAt(verifyPath());
    expect(await screen.findByText("平台上這則新廣告已經核對完成")).toBeTruthy();
    expect(screen.getByText("已對應平台上的廣告物件")).toBeTruthy();
  });

  it("follow_up 存在：verify 頁出現「暫停舊廣告」主按鈕，連去 propose/pause/<old>", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({
        items: [newAdItem()],
        replaces: { entity_id: "aex_old", name: "1150650 舊版單圖" },
        follow_up: { kind: "pause_old", entity_id: "aex_old" },
      })],
    });
    renderAt(verifyPath());
    const cta = await screen.findByRole("link", { name: "暫停舊廣告 →" });
    expect((cta as HTMLAnchorElement).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/propose/pause/aex_old");
  });

  it("deviated：不套用 copy／pause／budget 的逐行對照表，只顯示訊息", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({
        items: [newAdItem({ verification_state: "deviated", evidence_json: { message: "平台設定與核准內容不同，請檢視差異後重新決定。" } })],
      })],
    });
    renderAt(verifyPath());
    expect(await screen.findByText("平台上這則新廣告和核准的內容不一樣")).toBeTruthy();
    expect(screen.queryByText("你核准的")).toBeNull();
  });
});

describe("VerifyPage（F27-I15 Contract F）cleanup kind", () => {
  const CLEANUP_KIND = "cleanup" as unknown as QueueItem["kind_key"];
  function cleanupQueueItem(): QueueItem {
    return queueItem({
      kind_key: CLEANUP_KIND, category: "ads_triage_cleanup",
      proposal: { kind: "cleanup", change_set_id: "acs_1", campaign_id: "cmp_1", status: "approved", verification_state: "pending", reason: null, revisit_at: null, multi: true },
    });
  }
  function lowItem(overrides: Partial<ChangeItem> = {}): ChangeItem {
    return changeItem({
      id: "item_low1", target_id: "aex_low1",
      target: { id: "aex_low1", name: "1150701 情境圖 A", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "native_low1" },
      ...overrides,
    });
  }

  it("全部已核對：摘要 hero 顯示都已經關閉，逐列各自狀態", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem()]));
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({
        items: [lowItem(), lowItem({ id: "item_low2", target_id: "aex_low2", target: { id: "aex_low2", name: "1150702 情境圖 B", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "native_low2" } })],
      })],
    });
    renderAt(verifyPath());
    expect(await screen.findByText("這批要清理的廣告都已經關閉")).toBeTruthy();
    expect(screen.getByText("1150701 情境圖 A")).toBeTruthy();
    expect(screen.getByText("1150702 情境圖 B")).toBeTruthy();
    expect(screen.getAllByText("已核對，已關閉")).toHaveLength(2);
  });

  it("F28-I14：四步驟 提議／確認／到平台完成／核對結果，目前在最後一步，確認與到平台完成可回去", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem()]));
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [changeSet({ items: [lowItem()] })] });
    renderAt(verifyPath());
    const current = await screen.findByRole("listitem", { current: "step" });
    const labels = screen.getAllByRole("listitem").map((li) => li.textContent?.replace(/^\d/, ""));
    expect(labels).toEqual(["提議", "確認", "到平台完成", "核對結果"]);
    expect(current.textContent).toContain("核對結果");
    expect(screen.getByRole("link", { name: "回到確認" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/confirm");
    expect(screen.getByRole("link", { name: "回到到平台完成" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/handoff");
    expect(screen.queryByRole("link", { name: "回到提議" })).toBeNull();
  });

  it("其中一則已回報但還在核對：摘要 hero 挑第一個不是 confirmed 的狀態（不是嚴重度排序）", async () => {
    // `verification_state:"pending"` 且 `reported_at===null` 的項目會讓
    // `changeFlow.ts::stepFromChangeSet` 整份都還算「到平台完成」，導回 handoff 頁——這裡要留在
    // verify 頁測「摘要挑第一個非 confirmed」，兩則都要先過 reported。
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem()]));
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({
        items: [
          lowItem({ verification_state: "reported" }),
          lowItem({ id: "item_low2", target_id: "aex_low2", target: { id: "aex_low2", name: "1150702 情境圖 B", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "native_low2" } }),
        ],
      })],
    });
    renderAt(verifyPath());
    expect(await screen.findByText("還在等系統核對")).toBeTruthy();
    expect(screen.getByText("已回報，核對中")).toBeTruthy();
    expect(screen.getByText("已核對，已關閉")).toBeTruthy();
  });

  it("⟳ 全部重新核對：對每一則各呼叫一次 check", async () => {
    const user = userEvent.setup();
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem()]));
    const baseSet = changeSet({
      items: [
        lowItem({ verification_state: "reported" }),
        lowItem({ id: "item_low2", target_id: "aex_low2", target: { id: "aex_low2", name: "1150702 情境圖 B", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "native_low2" }, verification_state: "reported" }),
      ],
    });
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [baseSet] });
    vi.mocked(changeApi.actOnChangeItem).mockResolvedValueOnce(baseSet).mockResolvedValueOnce(baseSet);
    renderAt(verifyPath());
    await user.click(await screen.findByRole("button", { name: "⟳ 全部重新核對" }));
    await waitFor(() => expect(changeApi.actOnChangeItem).toHaveBeenCalledTimes(2));
    expect(vi.mocked(changeApi.actOnChangeItem).mock.calls[0]).toEqual(["brd_1", "cmp_1", "acs_1", "item_low1", "check"]);
    expect(vi.mocked(changeApi.actOnChangeItem).mock.calls[1]).toEqual(["brd_1", "cmp_1", "acs_1", "item_low2", "check"]);
  });
});
