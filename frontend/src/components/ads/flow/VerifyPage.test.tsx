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
// F50 Contract K: the org clock reads the workspace org zone; dates assert Asia/Taipei output, never the runner's.
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "user:org", identity: { user: { id: "u", email: "a@example.com" }, org: { id: "o", name: "測試", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-10-01" }, orgs: [] } }) }));

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
    triage: triage(), proposal: null, done: false,
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
    verification_state: "confirmed", verification_label: "已核對相符",
    evidence_json: { setting_matches: true, observed_at: "2026-09-22T02:13:00Z" },
    // F49 Contract L: the served words of the platform status on each side (`change_control_data.status_labels`).
    status_labels: { before: "已暫停", after: "已暫停", observed: "已暫停" },
    reported_at: "2026-09-22T02:00:00Z", first_observed_at: "2026-09-22T02:13:00Z", verified_at: "2026-09-22T02:13:00Z",
    platform_url: "https://adsmanager.facebook.com/adsmanager/manage/ads?act=1&selected_ad_ids=native_1",
    ...overrides,
  };
}
/** F49 Contract B: each served state with its served word (`change_control_data.VERIFICATION_LABELS`). */
const LABEL = {
  pending: "尚未回報", reported: "已回報，待讀回", unknown: "讀到了，還不能確認",
  confirmed: "已核對相符", deviated: "與核准內容不同", stale: "設定已變，需要重新檢視",
} as const;
function served(state: ChangeItem["verification_state"]): Pick<ChangeItem, "verification_state" | "verification_label"> {
  return { verification_state: state, verification_label: LABEL[state] };
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
    // F49 Contract L: the served status word, never a local map of platform statuses.
    expect(screen.getByText("狀態：已暫停")).toBeTruthy();
    // F27-I16 Contract H/D：沒有 `timeline`／`learning`（既有 factory 沒帶這兩個欄位）當作
    // 「還不知道」，跟「明天確認」／「沒標主打，未記入」畫同一格，不是省略整格。
    expect(screen.getByText("花費停止")).toBeTruthy();
    expect(screen.getByText("明天確認")).toBeTruthy();
    expect(screen.getByText("品牌學習")).toBeTruthy();
    expect(screen.getByText("沒標主打，未記入")).toBeTruthy();
    expect(screen.getByRole("button", { name: "⟳ 重新核對" })).toBeTruthy();
    const home = screen.getByRole("link", { name: "← 回投放中心" }) as HTMLAnchorElement;
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

  it("budget（F48-I11）：「下次檢查 M/D」讀 timeline.next_review_at，不再印固定的「學習期 3–5 天」", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        kind: "budget", before: { daily_amount: 1000 }, after: { daily_amount: 1200 },
        timeline: { spend_stopped: null, delivery_started: null, next_review_at: "2026-09-25" },
      })] })],
    });
    renderAt(verifyPath());
    await screen.findByText("平台上的每日預算已經是 1,200");
    expect(screen.getByText("下次檢查")).toBeTruthy();
    expect(screen.getByText("9/25")).toBeTruthy();
    expect(screen.queryByText("學習期")).toBeNull();
    expect(screen.queryByText(/3–5 天/)).toBeNull();
    // One cell for the one date — 成效回看 would print the same 9/25 twice.
    expect(screen.queryByText("成效回看")).toBeNull();
  });

  it("budget（F48-I11）：還沒排檢查就沒有「下次檢查」格，只照實寫「尚未排定」", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        kind: "budget", before: { daily_amount: 1000 }, after: { daily_amount: 1200 },
        timeline: { spend_stopped: null, delivery_started: null, next_review_at: null },
      })] })],
    });
    renderAt(verifyPath());
    await screen.findByText("平台上的每日預算已經是 1,200");
    expect(screen.queryByText("下次檢查")).toBeNull();
    expect(screen.getByText("成效回看")).toBeTruthy();
    expect(screen.getByText("尚未排定")).toBeTruthy();
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
        done: true,
      }),
    ]));
    renderAt(verifyPath());
    await screen.findByText("平台上這則廣告已經關閉");
    expect(screen.getByRole("link", { name: "← 回投放中心" })).toBeTruthy();
  });

  it("F49 Contract Q：下一件跳過通知列（decision: false），照 served position 挑最前面的", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([
      queueItem({ decision: true, position: 1 }),
      queueItem({ id: "int_gap", kind_key: "insufficient_data", decision: false, position: null, action_url: "/brands/brd_1/ads/campaigns/cmp_9/wait", triage: triage({ entity_id: "aex_9", campaign_id: "cmp_9" }) }),
      queueItem({ id: "int_4", triage: triage({ entity_id: "aex_4", campaign_id: "cmp_4" }), decision: true, position: 4 }),
      queueItem({ id: "int_2", triage: triage({ entity_id: "aex_2", campaign_id: "cmp_2" }), decision: true, position: 2 }),
    ]));
    renderAt(verifyPath());
    const next = await screen.findByRole("link", { name: "下一件 →" });
    expect(next.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_2/propose/pause/aex_2");
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
        ...served("deviated"),
        evidence_json: { observed_at: "2026-09-22T05:00:00Z", observed: { status: "ACTIVE" } },
        status_labels: { before: "投放中", after: "已暫停", observed: "投放中" },
      })] })],
    });
    renderAt(verifyPath());
    expect(await screen.findByText("平台上的狀態和核准的不一樣")).toBeTruthy();
    expect(screen.getByText("狀態：已暫停")).toBeTruthy();
    expect(screen.getByText("狀態：投放中")).toBeTruthy();
    const link = screen.getByRole("link", { name: "回平台改成核准內容 →" }) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/handoff");
    // F49 Contract Q: a forward exit beside the state's own action.
    expect(screen.getByRole("link", { name: "← 回投放中心" })).toBeTruthy();
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
    expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/propose/pause/aex_1?from=verify&ref=acs_1");
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

// F49 Contract B (drill-11 c3-11): `reported` (not read yet) and `unknown` (read, not provable) are told apart by their
// served words, and neither leaves the user with ⟳ alone — each carries a forward exit.
describe("VerifyPage（F22-I04, F49-I11）reported／unknown", () => {
  it("reported：印 served 的字，重新核對＋往前的出口（沒有下一件就回投放中心）", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        ...served("reported"), reported_at: "2026-09-22T02:00:00Z", evidence_json: {},
      })] })],
    });
    renderAt(verifyPath());
    expect(await screen.findByText("已回報，待讀回")).toBeTruthy();
    expect(screen.queryByText("讀到了，還不能確認")).toBeNull();
    expect(screen.getByRole("button", { name: "⟳ 重新核對" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "← 回投放中心" }).getAttribute("href")).toBe("/brands/brd_1/ads");
  });

  it("unknown：另一個字＋存下的原因，重新核對＋下一件", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([
      queueItem(),
      queueItem({ id: "int_2", triage: triage({ entity_id: "aex_2", campaign_id: "cmp_2" }), proposal: null }),
    ]));
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({ items: [changeItem({
        ...served("unknown"), reported_at: "2026-09-22T02:00:00Z",
        evidence_json: { reason_code: "unverifiable", message: "目前無法核對帳戶、物件或設定。請確認連線後重試；未標為完成。" },
      })] })],
    });
    renderAt(verifyPath());
    expect(await screen.findByText("讀到了，還不能確認")).toBeTruthy();
    expect(screen.queryByText("已回報，待讀回")).toBeNull();
    expect(screen.getByText("目前無法核對帳戶、物件或設定。請確認連線後重試；未標為完成。")).toBeTruthy();
    expect(screen.getByRole("button", { name: "⟳ 重新核對" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "下一件 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_2/propose/pause/aex_2");
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
  it("rereads the placement action without a payload and displays the retained-proof reason", async () => {
    const initial = newAdItem();
    const message = "本次讀回未完成；保留前次核對證據供查看，請稍後重試。";
    const failed = newAdItem({
      ...served("unknown"),
      evidence_json: { observed_at: null, attempted_at: "2026-09-22T05:00:00Z", message,
        peers: [{ handoff_item_id: "ahi_1", entity_id: "aex_1", status: "unknown",
          material_evidence: "unknown", previous_observation: {
            observed_at: "2026-09-22T02:13:00Z", evidence: { material_evidence: "user_verified" },
          } }],
      },
    });
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [changeSet({ items: [initial] })] });
    vi.mocked(changeApi.actOnChangeItem).mockResolvedValueOnce(changeSet({ items: [failed] }));
    renderAt(verifyPath());
    await userEvent.click(await screen.findByRole("button", { name: "⟳ 重新核對" }));
    await waitFor(() => expect(changeApi.actOnChangeItem).toHaveBeenCalledWith("brd_1", "cmp_1", "acs_1", "item_new", "check"));
    expect(await screen.findByText(message)).toBeTruthy();
    expect(screen.queryByText("平台上這則新廣告已經核對完成")).toBeNull();
  });
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
    expect((cta as HTMLAnchorElement).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/propose/pause/aex_old?from=verify&ref=acs_1");
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

  it("全部已核對：摘要 hero 顯示都已經關閉，逐列印 served 的字", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem()]));
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({
        ...served("confirmed"),
        items: [lowItem(), lowItem({ id: "item_low2", target_id: "aex_low2", target: { id: "aex_low2", name: "1150702 情境圖 B", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "native_low2" } })],
      })],
    });
    renderAt(verifyPath());
    expect(await screen.findByText("這批要清理的廣告都已經關閉")).toBeTruthy();
    expect(screen.getByText("1150701 情境圖 A")).toBeTruthy();
    expect(screen.getByText("1150702 情境圖 B")).toBeTruthy();
    expect(screen.getAllByText("已核對相符")).toHaveLength(2);
  });

  it("F28-I14：四步驟 提議／確認／到平台完成／核對結果，目前在最後一步，確認與到平台完成可回去", async () => {
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem()]));
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [changeSet({ items: [lowItem()] })] });
    renderAt(verifyPath());
    const current = await screen.findByRole("listitem", { current: "step" });
    const labels = screen.getAllByRole("listitem").map((li) => li.textContent?.replace(/^\d/, ""));
    expect(labels).toEqual(["提議", "確認", "到平台完成", "核對結果"]);
    expect(current.textContent).toContain("核對結果");
    expect(screen.getByRole("link", { name: "回到「確認」" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/confirm");
    expect(screen.getByRole("link", { name: "回到「到平台完成」" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/acs_1/handoff");
    expect(screen.queryByRole("link", { name: "回到「提議」" })).toBeNull();
  });

  it("F49 Contract B：摘要 hero 是整份 served 的最差狀態與字；unknown 的列印出存下的原因，跟 reported 不同字", async () => {
    // `verification_state:"pending"` 且 `reported_at===null` 的項目會讓
    // `changeFlow.ts::stepFromChangeSet` 整份都還算「到平台完成」，導回 handoff 頁——這裡要留在 verify 頁。
    vi.mocked(triageApi.getQueue).mockResolvedValue(queue([cleanupQueueItem()]));
    const target3 = { id: "aex_low3", name: "1150703 情境圖 C", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "native_low3" };
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({
        // The backend's `worst_state` (unknown > reported), not the first non-confirmed row.
        ...served("unknown"),
        items: [
          lowItem({ ...served("reported") }),
          lowItem({ id: "item_low2", target_id: "aex_low2", target: { id: "aex_low2", name: "1150702 情境圖 B", platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "native_low2" } }),
          lowItem({ id: "item_low3", target_id: "aex_low3", target: target3, ...served("unknown"), evidence_json: { reason_code: "chain_mismatch", message: "讀到的廣告不在原本的投放組底下，請重新核對。" } }),
        ],
      })],
    });
    renderAt(verifyPath());
    expect(await screen.findAllByText("讀到了，還不能確認")).toHaveLength(2); // hero + the unknown row
    expect(screen.getByText("已回報，待讀回")).toBeTruthy();
    expect(screen.getByText("已核對相符")).toBeTruthy();
    expect(screen.getByText("讀到的廣告不在原本的投放組底下，請重新核對。")).toBeTruthy();
    // A forward exit beside 全部重新核對.
    expect(screen.getByRole("link", { name: "← 回投放中心" })).toBeTruthy();
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

// F29-I10 Contract K: the queue is context here (chip, 第幾件, 下一件); its failure is said out loud with 重試, and a
// cleanup set names itself (`source: "cleanup"`) so the failure cannot turn it into a "multi-item" set.
describe("VerifyPage（F29-I10）佇列讀取失敗", () => {
  it("核對結果照舊，多一塊讀取失敗；重試後「下一件」回來", async () => {
    vi.mocked(triageApi.getQueue).mockReset();
    vi.mocked(triageApi.getQueue).mockRejectedValueOnce(new Error("queue down")).mockResolvedValueOnce(queue([
      queueItem(),
      queueItem({ id: "int_2", triage: triage({ entity_id: "aex_2", campaign_id: "cmp_2" }), proposal: null }),
    ]));
    renderAt(verifyPath());
    expect(await screen.findByText(/待決定清單讀不到/)).toBeTruthy();
    expect(screen.getByText("平台上這則廣告已經關閉")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "重試" }));
    expect(await screen.findByRole("link", { name: "下一件 →" })).toBeTruthy();
    expect(screen.queryByText(/待決定清單讀不到/)).toBeNull();
    expect(triageApi.getQueue).toHaveBeenCalledTimes(2);
  });

  it("清理清單（source: cleanup）：佇列讀不到仍畫逐則核對，不說「多項變更」", async () => {
    vi.mocked(triageApi.getQueue).mockRejectedValue(new Error("queue down"));
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [changeSet({
        source: "cleanup",
        items: [
          changeItem({ id: "item_low1", target_id: "aex_low1", verification_state: "confirmed", reported_at: "2026-09-21T00:00:00Z" }),
          changeItem({ id: "item_low2", target_id: "aex_low2", verification_state: "confirmed", reported_at: "2026-09-21T00:00:00Z" }),
        ],
      })],
    });
    renderAt(verifyPath());
    expect(await screen.findByRole("button", { name: "⟳ 全部重新核對" })).toBeTruthy();
    expect(screen.queryByText("這份清單有多項變更")).toBeNull();
    expect(screen.getByText(/待決定清單讀不到/)).toBeTruthy();
  });
});
