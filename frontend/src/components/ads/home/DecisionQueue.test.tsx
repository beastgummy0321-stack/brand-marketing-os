/** frontend/src/components/ads/home/DecisionQueue.test.tsx — F19-I03：v7 `home()` 的 `row`
 * （prototype ≈ 195–203）落地後的列內容斷言。殼／loading／error 已經是 F19-I02 的範圍
 * （`AdsHomePage.test.tsx` 蓋），這支只管 `DecisionQueue`／`QueueRow` 自己印出來的東西：
 * 四種分類各自的量尺文案＋寬度、金額格式（最多兩位小數、不四捨五入到整數）、未知數字的兩種
 * 誠實句（量測值「累積中」／配置值「尚未設定」）、只有第一列主要按鈕、按鈕不看量尺畫不畫得
 * 出來、篩選鈕、空狀態不重複頁首那句話＋佔位列同時可見、未認得的 pending 代碼、鍵盤順序。
 * F25-I02：加上 `scale_budget`（可加預算）／`refresh_creative`（補素材）兩種列，以及
 * `refresh_creative` 永遠排最後、`kinds_pending` 空陣列時佔位列全消失。 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type {
  QueueCleanup, QueueCleanupProposal, QueueInsufficient, QueueItem, QueueKind, QueuePauseProposal,
  QueuePayload, QueueProposal, QueueRefresh, QueueReviewProposal, QueueScale, TriageItem,
} from "@/lib/adsTriageApi";
import { DecisionQueue, type QueueState } from "./DecisionQueue";
import { isQueueItemDone, proposalAction } from "./status";

function triageItem(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "ad_1", native_id: "native_1", name: "晨光隨行杯・日常出發", campaign_id: "cmp_1",
    campaign_name: "晨光隨行杯上市", thumbnail_url: null,
    class: "stop_loss", label: "停損", reason_code: "spend_over_stop_loss",
    window: { start: "2026-09-01", end: "2026-09-07", days: 7, previous_start: "2026-08-25", previous_end: "2026-08-31", extended_from: null },
    target: { value: 450, basis: "break_even", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: 5200, result_count: 0, cost_per_result: null, result_kind: "purchase", result_label: "購買", derived_zero_days: 7, reason: null },
    previous: { spend: 4900, result_count: 15, cost_per_result: 326.7, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    change_pct: null, sample: { gate: true, spend_multiple: 3.2, days_with_events: 7 },
    ...overrides,
  };
}

// F25-I02: `extra` carries the scale_budget／refresh_creative-only fields — `kind_key` defaults to
// mirroring `triage.class` (unchanged for every existing stop_loss／worse fixture below), scale
// and refresh fixtures always pass an explicit `kind_key` since their `triage.class` is the *ad's*
// own classification (e.g. `better`), never one of the two row kinds.
function queueItem(
  id: string,
  overrides: Partial<TriageItem> = {},
  proposal: QueueProposal | null = null,
  extra: {
    kind_key?: QueueKind; scale?: QueueScale; refresh?: QueueRefresh; action_url?: string;
    insufficient?: QueueInsufficient; cleanup?: QueueCleanup;
  } = {},
): QueueItem {
  const triage = triageItem(overrides);
  return {
    id, org_id: "org_1", brand_id: "brd_1", campaign_period_id: null, dedupe_key: `k_${id}`,
    category: "ads_triage", kind: null, severity: "rule_warning",
    message: "待決定", action_url: extra.action_url ?? `/brands/brd_1/ads/campaigns/cmp_1?tab=performance`,
    visible_from: null, status: "open", created_at: "2026-09-19T00:00:00Z", resolved_at: null,
    kind_key: extra.kind_key ?? (triage.class === "worse" ? "worse" : "stop_loss"),
    triage, proposal, scale: extra.scale, refresh: extra.refresh, insufficient: extra.insufficient,
    cleanup: extra.cleanup,
  };
}

// F27-I17 Contract F: `QueueCleanup`／`QueueCleanupProposal` skeletons, same style as `refresh`／
// `insufficient` above — each test only overrides what it asserts on.
function cleanupPayload(overrides: Partial<QueueCleanup> = {}): QueueCleanup {
  return {
    campaign_id: "cmp_1", campaign_name: "晨光隨行杯上市", can_support: 4, active_ads: 6,
    ads: [
      { entity_id: "ad_low", name: "晨光隨行杯・清倉版", thumbnail_url: "https://cdn.example/low.jpg", spend_7d: 120 },
      { entity_id: "ad_low2", name: "晨光隨行杯・過季版", thumbnail_url: null, spend_7d: 180 },
    ],
    ...overrides,
  };
}
function cleanupProposal(overrides: Partial<QueueCleanupProposal> = {}): QueueCleanupProposal {
  return {
    kind: "cleanup", change_set_id: "set_clean_1", campaign_id: "cmp_1",
    status: "draft", verification_state: "pending",
    reason: null, revisit_at: null, multi: true,
    ...overrides,
  };
}

function scaleOwner(overrides: Partial<QueueScale["owner"]> = {}): QueueScale["owner"] {
  return {
    id: "adset_1", name: "晨光隨行杯・投放組", native_kind: "adset", native_id: "native_adset_1",
    ads_count: 3, currency: "TWD", ...overrides,
  };
}
function scale(overrides: Partial<QueueScale> = {}): QueueScale {
  return {
    owner: scaleOwner(), from: 500, to: 600,
    cost_per_result: 300, previous_cost_per_result: 310,
    target: { value: 450, basis: "break_even", result_kind: "purchase", result_label: "購買", missing: [] },
    window_days: 7, month: { available: 12000, extra_needed: 700 },
    ...overrides,
  };
}
function refresh(overrides: Partial<QueueRefresh> = {}): QueueRefresh {
  return {
    campaign_id: "cmp_1", campaign_name: "晨光隨行杯上市",
    readable_count: 2, classified_count: 5, thumbnails: ["https://cdn.example/a.jpg", null],
    ...overrides,
  };
}
function insufficient(overrides: Partial<QueueInsufficient> = {}): QueueInsufficient {
  return {
    campaign_id: "cmp_1", campaign_name: "晨光隨行杯上市",
    missing_days: ["2026-09-17", "2026-09-18"], sync_state: "disconnected",
    coverage: { start: "2026-08-24", end: "2026-09-22" },
    ...overrides,
  };
}

// F22-I05: `QueuePauseProposal` 的一則骨架，測試各個狀態時只覆寫要斷言的欄位。
function proposal(overrides: Partial<QueuePauseProposal> = {}): QueuePauseProposal {
  return {
    kind: "pause", change_set_id: "set_1", campaign_id: "cmp_1",
    status: "draft", verification_state: "pending",
    reason: null, revisit_at: null, multi: false,
    ...overrides,
  };
}

// F23-I01: `QueueReviewProposal` 的一則骨架，同上只覆寫要斷言的欄位。
function reviewProposal(overrides: Partial<QueueReviewProposal> = {}): QueueReviewProposal {
  return {
    kind: "review", review_id: "arv_1", status: "ready", decision: null,
    reason: null, revisit_at: null, recommendation_id: null,
    change_set_id: null, change_set_status: null, verification_state: null, multi: false,
    ...overrides,
  };
}

function queue(overrides: Partial<QueuePayload> = {}): QueuePayload {
  return {
    items: [], counts: { stop_loss: 0, worse: 0, better: 0, flat: 0, insufficient: 0, no_target: 0 },
    total_ads: 0, kinds_available: ["stop_loss", "worse"], kinds_pending: ["scale_budget", "refresh_creative"],
    ...overrides,
  };
}

function ready(overrides: Partial<QueuePayload> = {}): QueueState {
  return { status: "ready", queue: queue(overrides) };
}

function renderQueue(state: QueueState, recovering = false) {
  return render(
    <MemoryRouter>
      <DecisionQueue state={state} onRetry={() => {}} recovering={recovering} />
    </MemoryRouter>,
  );
}

describe("DecisionQueue／QueueRow（F19-I03）", () => {
  it("停損列：量尺對停損線（3×目標），文案帶花費、筆數、停損線；填色頂到 100%、marker 在停損線位置", () => {
    renderQueue(ready({ items: [queueItem("q1")] }));

    expect(screen.getByText("停損")).toBeTruthy();
    expect(screen.getByText("花了 5,200・0 筆購買")).toBeTruthy();
    expect(screen.getByText("停損線 1,350")).toBeTruthy();
    expect(screen.getByTestId("meter")).toBeTruthy();
    // value=5200 遠超 marker(=450*3=1350)，量尺自己的上限是 marker*1.5=2025——填色本來會超過
    // 100%，必須頂住（lead review fix 2）。
    expect(screen.getByTestId("meter-fill").style.width).toBe("100%");
    expect(screen.getByTestId("meter-marker").style.left).toBe(`${(1350 / (1350 * 1.5)) * 100}%`);
  });

  it("變差列：量尺對目標（中間值，不頂滿），▲% 只看 change_pct、不是從成本／目標反推", () => {
    // cost(600)／target(450) 本身的差是 33%，change_pct 另外給 0.66——兩者刻意不一樣，證明
    // 「▲66%」印的是 change_pct 這個欄位，不是畫面自己拿 600/450 算出來的（lead review fix 3）。
    renderQueue(ready({
      items: [queueItem("q1", {
        class: "worse", label: "變差",
        target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [] },
        current: { spend: 3000, result_count: 5, cost_per_result: 600, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
        change_pct: 0.66,
      })],
    }));

    expect(screen.getByText("變差")).toBeTruthy();
    expect(screen.getByText("每次購買成本 600 ▲66%")).toBeTruthy();
    expect(screen.getByText("目標 450")).toBeTruthy();
    expect(screen.getByTestId("meter")).toBeTruthy();
    // 中間值：600 對 marker(=450)，量尺上限 450*1.5=675，填色跟 marker 都不頂滿（lead review fix 2）。
    expect(screen.getByTestId("meter-fill").style.width).toBe(`${(600 / (450 * 1.5)) * 100}%`);
    expect(screen.getByTestId("meter-marker").style.left).toBe(`${(450 / (450 * 1.5)) * 100}%`);
  });

  it("金額格式：最多兩位小數、不四捨五入到整數（5200/15 印 346.67，3.1 留著 3.1，不是 3）", () => {
    renderQueue(ready({
      items: [
        queueItem("q1", {
          class: "worse", label: "變差",
          target: { value: null, basis: null, result_kind: "purchase", result_label: "購買", missing: ["target"] },
          current: { spend: 5200, result_count: 15, cost_per_result: 5200 / 15, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
        }),
        queueItem("q2", {
          class: "worse", label: "變差",
          target: { value: null, basis: null, result_kind: "purchase", result_label: "購買", missing: ["target"] },
          current: { spend: 310, result_count: 100, cost_per_result: 3.1, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
        }),
      ],
    }));

    expect(screen.getByText("每次購買成本 346.67")).toBeTruthy();
    expect(screen.getByText("每次購買成本 3.1")).toBeTruthy();
  });

  it("目標未知：不畫量尺，文字寫「尚未設定」而不是「累積中」或 0（目標是沒設定的配置值，不是還在累積的量測值）", () => {
    renderQueue(ready({
      items: [queueItem("q1", {
        target: { value: null, basis: null, result_kind: "purchase", result_label: "購買", missing: ["target"] },
      })],
    }));

    expect(screen.getByText("停損線 尚未設定")).toBeTruthy();
    expect(screen.queryByTestId("meter")).toBeNull();
    expect(screen.queryByText(/停損線 0/)).toBeNull();
  });

  it("量尺畫不出來（目標未知）不影響按鈕：proposal 沒有回合時「看證據」就還在（lead review fix 1）", () => {
    renderQueue(ready({
      items: [queueItem("q1", {
        class: "worse", label: "變差",
        target: { value: null, basis: null, result_kind: "purchase", result_label: "購買", missing: ["target"] },
        current: { spend: 3000, result_count: 5, cost_per_result: 450, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
      })],
    }));

    expect(screen.queryByTestId("meter")).toBeNull();
    expect(screen.getByRole("link", { name: "看證據" })).toBeTruthy();
  });

  it("停損列不再印靜態的「暫停提議・接上後開放」——proposal 已經接上，按鈕本身就是進度", () => {
    renderQueue(ready({ items: [queueItem("q1")] }));

    expect(screen.queryByText("暫停提議・接上後開放")).toBeNull();
  });

  it("只有第一列是主要按鈕樣式，其餘是次要（停損列沒有提案時印「看提議」，變差列維持「看證據」）", () => {
    renderQueue(ready({
      items: [
        queueItem("q1"),
        queueItem("q2", { class: "worse", label: "變差", name: "晨光隨行杯・辦公室一角" }),
      ],
    }));

    const goLink = screen.getByRole("link", { name: "看提議" });
    const evidenceLink = screen.getByRole("link", { name: "看證據" });
    expect(goLink.getAttribute("data-variant")).toBe("default");
    expect(evidenceLink.getAttribute("data-variant")).toBe("outline");
  });

  describe("F22-I05：停損列的按鈕由 item.proposal 決定", () => {
    it("none（沒有提案）：「看提議」導向提議頁（F25-I02：home 這一列的字樣，不是 detail 頁的「去處理」）", () => {
      renderQueue(ready({ items: [queueItem("q1", { entity_id: "ad_1", campaign_id: "cmp_1" })] }));

      const link = screen.getByRole("link", { name: "看提議" });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/propose/pause/ad_1");
      expect(link.getAttribute("data-variant")).toBe("default");
    });

    it("draft：「等你核准」導向 confirm", () => {
      renderQueue(ready({
        items: [queueItem("q1", {}, proposal({ status: "draft" }))],
      }));

      const link = screen.getByRole("link", { name: "等你核准" });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/set_1/confirm");
    });

    it("approved + pending：「到平台完成」導向 handoff", () => {
      renderQueue(ready({
        items: [queueItem("q1", {}, proposal({ status: "approved", verification_state: "pending" }))],
      }));

      const link = screen.getByRole("link", { name: "到平台完成" });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/set_1/handoff");
    });

    it.each([
      ["reported", "核對中"],
      ["unknown", "核對中"],
      ["deviated", "與核准不符"],
      ["stale", "需重新檢討"],
    ] as const)("approved + %s：「%s」導向 verify", (state, label) => {
      renderQueue(ready({
        items: [queueItem("q1", {}, proposal({ status: "approved", verification_state: state }))],
      }));

      const link = screen.getByRole("link", { name: label });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/set_1/verify");
      expect(link.getAttribute("data-variant")).not.toBe("ghost");
    });

    it("confirmed：「已核對」是 ghost 按鈕（已完成）", () => {
      renderQueue(ready({
        items: [queueItem("q1", {}, proposal({ status: "approved", verification_state: "confirmed" }))],
      }));

      const link = screen.getByRole("link", { name: "已核對" });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/set_1/verify");
      expect(link.getAttribute("data-variant")).toBe("ghost");
    });

    it("rejected：「已拒絕」是 ghost 按鈕", () => {
      renderQueue(ready({
        items: [queueItem("q1", {}, proposal({ status: "rejected" }))],
      }));

      const link = screen.getByRole("link", { name: "已拒絕" });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/changes/set_1/confirm");
      expect(link.getAttribute("data-variant")).toBe("ghost");
    });

    it("deferred：標籤是 revisit_at 換算的「M/D 重看」（瀏覽器本地時區），ghost 按鈕", () => {
      renderQueue(ready({
        items: [queueItem("q1", {}, proposal({ status: "deferred", revisit_at: "2026-10-03T02:00:00Z" }))],
      }));

      const d = new Date("2026-10-03T02:00:00Z");
      const expected = `${d.getMonth() + 1}/${d.getDate()} 重看`;
      const link = screen.getByRole("link", { name: expected });
      expect(link.getAttribute("data-variant")).toBe("ghost");
    });

    it("multi：連去活動工作區，不是特定步驟頁", () => {
      renderQueue(ready({
        items: [queueItem("q1", {}, proposal({ status: "draft", multi: true }))],
      }));

      const link = screen.getByRole("link", { name: "等你核准" });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1");
    });
  });

  // F23-I01：`worse` 列的按鈕邏輯（`status.ts::proposalAction`／`isQueueItemDone` 的 review 分支，
  // feature Decisions "Queue row state for `worse` rows"）——純函式層級的完整狀態機斷言，直接
  // 呼叫 `proposalAction`／`isQueueItemDone`，不透過 `DecisionQueue` 畫面。F23-I05 把
  // `home/QueueRow.tsx` 接上這支 helper 後，下面「F23-I05」那個 describe 補畫面層級的斷言
  // （none／ready／completed／deferred），這裡繼續留著當狀態機的完整覆蓋，不重複。
  describe("F23-I01：worse 列的 review 分支（proposalAction／isQueueItemDone）", () => {
    const call = (p: QueueReviewProposal | null) =>
      proposalAction("brd_1", "cmp_1", "ad_1", p, "review");

    it("none（沒有回合）：「看證據」導向 review/:entityId", () => {
      const action = call(null);
      expect(action).toEqual({
        label: "看證據", href: "/brands/brd_1/ads/campaigns/cmp_1/review/ad_1", done: false,
      });
    });

    it.each(["queued", "running"] as const)("%s：「整理證據中」導向 reviews/:id", (status) => {
      const action = call(reviewProposal({ status }));
      expect(action).toEqual({
        label: "整理證據中", href: "/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1", done: false,
      });
    });

    it("waiting：「資料不足」導向 reviews/:id", () => {
      const action = call(reviewProposal({ status: "waiting" }));
      expect(action).toEqual({
        label: "資料不足", href: "/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1", done: false,
      });
    });

    it.each(["failed", "unknown"] as const)("%s：「證據沒整理成」導向 reviews/:id", (status) => {
      const action = call(reviewProposal({ status }));
      expect(action).toEqual({
        label: "證據沒整理成", href: "/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1", done: false,
      });
    });

    it("ready：「等你決定」導向 reviews/:id", () => {
      const action = call(reviewProposal({ status: "ready" }));
      expect(action).toEqual({
        label: "等你決定", href: "/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1", done: false,
      });
    });

    it("completed 無文案清單：「選方向」導向 reviews/:id/prepare", () => {
      const action = call(reviewProposal({ status: "completed", decision: "completed" }));
      expect(action).toEqual({
        label: "選方向",
        href: "/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1/prepare",
        done: false,
      });
    });

    it("completed 帶文案清單（draft）：沿用停損那支的 label／連結（changes/:id/confirm）", () => {
      const action = call(reviewProposal({
        status: "completed", decision: "completed",
        change_set_id: "set_9", change_set_status: "draft", verification_state: "pending",
      }));
      expect(action).toEqual({
        label: "等你核准",
        href: "/brands/brd_1/ads/campaigns/cmp_1/changes/set_9/confirm",
        done: false,
      });
    });

    it("completed 帶文案清單（approved+confirmed）：ghost、已完成", () => {
      const action = call(reviewProposal({
        status: "completed", decision: "completed",
        change_set_id: "set_9", change_set_status: "approved", verification_state: "confirmed",
      }));
      expect(action).toEqual({
        label: "已核對",
        href: "/brands/brd_1/ads/campaigns/cmp_1/changes/set_9/verify",
        done: true,
      });
    });

    it("deferred：標籤是 revisit_at 換算的「M/D 重看」，已完成", () => {
      const action = call(reviewProposal({
        status: "deferred", decision: "deferred", revisit_at: "2026-10-03T02:00:00Z",
      }));
      const d = new Date("2026-10-03T02:00:00Z");
      expect(action).toEqual({
        label: `${d.getMonth() + 1}/${d.getDate()} 重看`,
        href: "/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1",
        done: true,
      });
    });

    it("unjudgeable：「無法判定」，已完成", () => {
      const action = call(reviewProposal({ status: "unjudgeable", decision: "unjudgeable" }));
      expect(action).toEqual({
        label: "無法判定", href: "/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1", done: true,
      });
    });

    it("isQueueItemDone：worse 列 ready 未完成、deferred 已完成，跟按鈕的 done 一致", () => {
      const readyItem = queueItem("q1", { class: "worse" }, reviewProposal({ status: "ready" }));
      const deferredItem = queueItem(
        "q2", { class: "worse" }, reviewProposal({ status: "deferred", decision: "deferred" }),
      );
      expect(isQueueItemDone(readyItem)).toBe(false);
      expect(isQueueItemDone(deferredItem)).toBe(true);
    });

    it("isQueueItemDone：worse 列沒有提案時未完成", () => {
      const item = queueItem("q1", { class: "worse" }, null);
      expect(isQueueItemDone(item)).toBe(false);
    });
  });

  // F23-I05：`home/QueueRow.tsx` 現在把 `worse` 列接上 `proposalAction(..., "review")`（不再看
  // `item.action_url`）——上面 F23-I01 已經覆蓋狀態機本身，這裡只確認畫面真的接上：連結文字／
  // href／按鈕樣式（primary/ghost 跟停損列同一條規則：`action.done ? "ghost" : primary ? "default" : "outline"`）。
  describe("F23-I05：worse 列在畫面上接上 review 分支", () => {
    it("none（沒有回合）：「看證據」導向 review/:entityId，非 ghost", () => {
      renderQueue(ready({
        items: [queueItem("q1", { class: "worse", label: "變差", entity_id: "ad_1", campaign_id: "cmp_1" }, null)],
      }));

      const link = screen.getByRole("link", { name: "看證據" });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/review/ad_1");
      expect(link.getAttribute("data-variant")).not.toBe("ghost");
    });

    it("ready：「等你決定」導向 reviews/:id", () => {
      renderQueue(ready({
        items: [queueItem("q1", { class: "worse", label: "變差" }, reviewProposal({ status: "ready" }))],
      }));

      const link = screen.getByRole("link", { name: "等你決定" });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1");
      expect(link.getAttribute("data-variant")).not.toBe("ghost");
    });

    it("completed 無文案清單：「選方向」導向 reviews/:id/prepare", () => {
      renderQueue(ready({
        items: [queueItem(
          "q1", { class: "worse", label: "變差" },
          reviewProposal({ status: "completed", decision: "completed" }),
        )],
      }));

      const link = screen.getByRole("link", { name: "選方向" });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1/prepare");
    });

    it("deferred：標籤是 revisit_at 換算的「M/D 重看」，ghost 按鈕（已完成）", () => {
      renderQueue(ready({
        items: [queueItem(
          "q1", { class: "worse", label: "變差" },
          reviewProposal({ status: "deferred", decision: "deferred", revisit_at: "2026-10-03T02:00:00Z" }),
        )],
      }));

      const d = new Date("2026-10-03T02:00:00Z");
      const link = screen.getByRole("link", { name: `${d.getMonth() + 1}/${d.getDate()} 重看` });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/reviews/arv_1");
      expect(link.getAttribute("data-variant")).toBe("ghost");
    });
  });

  // F25-I02：proposalAction 的 "budget" 分支——同 F23-I01 的做法，直接呼叫純函式做完整狀態機
  // 覆蓋，不透過 DOM（下面「可加預算列」describe 補畫面層級的斷言）。
  describe("F25-I02：proposalAction 的 budget 分支（scale_budget 列，跟 pause 分支共用同一套狀態機）", () => {
    const call = (p: QueueProposal | null) => proposalAction("brd_1", "cmp_1", "adset_1", p, "budget");

    it("none（沒有提案）：「看提議」導向 propose/budget/:ownerId", () => {
      expect(call(null)).toEqual({
        label: "看提議", href: "/brands/brd_1/ads/campaigns/cmp_1/propose/budget/adset_1", done: false,
      });
    });

    it("draft：「等你核准」導向 confirm（跟 pause 分支同一套 label／連結，budget 分支＝pause 分支）", () => {
      const budgetProposal: QueueProposal = {
        kind: "budget", change_set_id: "set_5", campaign_id: "cmp_1",
        status: "draft", verification_state: "pending", reason: null, revisit_at: null, multi: false,
      };
      expect(call(budgetProposal)).toEqual({
        label: "等你核准", href: "/brands/brd_1/ads/campaigns/cmp_1/changes/set_5/confirm", done: false,
      });
    });

    it("approved + pending：「到平台完成」導向 handoff", () => {
      const budgetProposal: QueueProposal = {
        kind: "budget", change_set_id: "set_5", campaign_id: "cmp_1",
        status: "approved", verification_state: "pending", reason: null, revisit_at: null, multi: false,
      };
      expect(call(budgetProposal)).toEqual({
        label: "到平台完成", href: "/brands/brd_1/ads/campaigns/cmp_1/changes/set_5/handoff", done: false,
      });
    });

    it("approved + confirmed：「已核對」ghost、已完成", () => {
      const budgetProposal: QueueProposal = {
        kind: "budget", change_set_id: "set_5", campaign_id: "cmp_1",
        status: "approved", verification_state: "confirmed", reason: null, revisit_at: null, multi: false,
      };
      expect(call(budgetProposal)).toEqual({
        label: "已核對", href: "/brands/brd_1/ads/campaigns/cmp_1/changes/set_5/verify", done: true,
      });
    });
  });

  describe("F25-I02：可加預算列（scale_budget，feature Decisions \"Home rows\"）", () => {
    it("KindMark 可加預算、標題是預算擁有者名稱、量尺 tone success、文案「<成果標籤>成本 X」／「目標 Y」，沒有提案時「看提議」導向 propose/budget/:ownerId", () => {
      renderQueue(ready({
        kinds_pending: [],
        items: [queueItem("q1", { class: "flat", label: "持平" }, null, {
          kind_key: "scale_budget", scale: scale(),
        })],
      }));

      expect(screen.getByText("可加預算")).toBeTruthy();
      expect(screen.getByText("晨光隨行杯・投放組")).toBeTruthy();
      expect(screen.getByText("購買成本 300")).toBeTruthy();
      expect(screen.getByText("目標 450")).toBeTruthy();
      expect(screen.getByTestId("meter-fill").className).toContain("bg-success");

      const link = screen.getByRole("link", { name: "看提議" });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/propose/budget/adset_1");
    });

    it("owner.name 是 null：標題退回「（未命名）」，不是空白", () => {
      renderQueue(ready({
        kinds_pending: [],
        items: [queueItem("q1", {}, null, {
          kind_key: "scale_budget", scale: scale({ owner: scaleOwner({ name: null }) }),
        })],
      }));

      expect(screen.getByText("（未命名）")).toBeTruthy();
    });

    it("成本或目標未知：不畫量尺，文案照印誠實句（量測值「累積中」／配置值「尚未設定」）", () => {
      renderQueue(ready({
        kinds_pending: [],
        items: [queueItem("q1", {}, null, {
          kind_key: "scale_budget",
          scale: scale({
            cost_per_result: null,
            target: { value: null, basis: null, result_kind: "purchase", result_label: "購買", missing: ["target"] },
          }),
        })],
      }));

      expect(screen.queryByTestId("meter")).toBeNull();
      expect(screen.getByText("購買成本 累積中")).toBeTruthy();
      expect(screen.getByText("目標 尚未設定")).toBeTruthy();
    });
  });

  describe("F25-I02：補素材列（refresh_creative，feature Decisions \"Home rows\"）", () => {
    it("KindMark 補素材、標題「能判讀的素材只剩 N 則」、縮圖格補到 4 格，按鈕「準備新素材」導向 item.action_url，非 ghost", () => {
      renderQueue(ready({
        kinds_pending: [],
        items: [queueItem("q1", {}, null, {
          kind_key: "refresh_creative",
          refresh: refresh({ readable_count: 2, thumbnails: ["https://cdn.example/a.jpg", null] }),
          action_url: "/brands/brd_1/ads/campaigns/cmp_1?tab=assets&material_new=1",
        })],
      }));

      expect(screen.getByText("補素材")).toBeTruthy();
      expect(screen.getByText("能判讀的素材只剩 2 則")).toBeTruthy();
      // 2 則 thumbnails（一則有圖、一則沒有但仍是「真的一格」）＋ 2 格補到 4 格的中空虛線。
      expect(screen.getAllByTestId("refresh-tile-hollow")).toHaveLength(2);

      const link = screen.getByRole("link", { name: "準備新素材" });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1?tab=assets&material_new=1");
      expect(link.getAttribute("data-variant")).not.toBe("ghost");
    });

    it("縮圖全空：4 格都印中空虛線（不是後端漏做，是前端自己補）", () => {
      renderQueue(ready({
        kinds_pending: [],
        items: [queueItem("q1", {}, null, { kind_key: "refresh_creative", refresh: refresh({ thumbnails: [] }) })],
      }));

      expect(screen.getAllByTestId("refresh-tile-hollow")).toHaveLength(4);
    });

    it("永遠不算完成——isQueueItemDone 恆 false（沒有提案流程，也沒有「已完成」樣式）", () => {
      const item = queueItem("q1", {}, null, { kind_key: "refresh_creative", refresh: refresh() });
      expect(isQueueItemDone(item)).toBe(false);
    });
  });

  describe("F26-I02：資料不足列（insufficient_data，feature Decisions \"I01 also raises...\"）", () => {
    it("分類 chip「！資料不足」、標題「這個活動暫時無法判斷」、DayTiles＋缺天數／同步狀態兩行文案、按鈕「去處理」導向 item.action_url，非 ghost", () => {
      renderQueue(ready({
        kinds_pending: [],
        items: [queueItem("q1", {}, null, {
          kind_key: "insufficient_data",
          insufficient: insufficient(),
          action_url: "/brands/brd_1/ads/campaigns/cmp_1/wait",
        })],
      }));

      expect(screen.getByText("！資料不足")).toBeTruthy();
      expect(screen.getByText("這個活動暫時無法判斷")).toBeTruthy();
      expect(screen.getByText("缺 9/17、9/18")).toBeTruthy();
      expect(screen.getByText("讀取權限失效")).toBeTruthy(); // sync_state: "disconnected"
      const days = document.querySelector('[data-slot="day-tiles"]');
      expect(days).toBeTruthy();
      expect(days!.children).toHaveLength(7);

      const link = screen.getByRole("link", { name: "去處理" });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/wait");
      expect(link.getAttribute("data-variant")).not.toBe("ghost");
    });

    it.each([
      ["disconnected", "讀取權限失效"],
      ["failed", "讀取失敗"],
      ["ok", "缺資料"],
      ["syncing", "缺資料"],
      ["never", "缺資料"],
    ] as const)("sync_state=%s：右側文案「%s」", (state, label) => {
      renderQueue(ready({
        kinds_pending: [],
        items: [queueItem("q1", {}, null, {
          kind_key: "insufficient_data", insufficient: insufficient({ sync_state: state }),
        })],
      }));

      expect(screen.getByText(label)).toBeTruthy();
    });

    it("missing_days 空（單純同步異常，不是缺天）：左側「缺 …」不印，右側同步狀態照印", () => {
      renderQueue(ready({
        kinds_pending: [],
        items: [queueItem("q1", {}, null, {
          kind_key: "insufficient_data",
          insufficient: insufficient({ missing_days: [], sync_state: "failed" }),
        })],
      }));

      expect(screen.queryByText(/^缺 /)).toBeNull();
      expect(screen.getByText("讀取失敗")).toBeTruthy();
    });

    it("coverage 是 null（從沒同步過）：DayTiles 照常畫 7 格（用今天當右邊界），不當機", () => {
      renderQueue(ready({
        kinds_pending: [],
        items: [queueItem("q1", {}, null, {
          kind_key: "insufficient_data",
          insufficient: insufficient({ coverage: null, missing_days: [], sync_state: "disconnected" }),
        })],
      }));

      const days = document.querySelector('[data-slot="day-tiles"]');
      expect(days).toBeTruthy();
      expect(days!.children).toHaveLength(7);
    });

    it("永遠不算完成——isQueueItemDone 恆 false（沒有提案流程，也沒有「已完成」樣式）", () => {
      const item = queueItem("q1", {}, null, { kind_key: "insufficient_data", insufficient: insufficient() });
      expect(isQueueItemDone(item)).toBe(false);
    });
  });

  describe("F27-I17 Done 1：真的縮圖（triage.thumbnail_url）", () => {
    it("有值：印真的 <img>，src 是 thumbnail_url", () => {
      renderQueue(ready({
        items: [queueItem("q1", { thumbnail_url: "https://cdn.example/ad.jpg" })],
      }));

      // 圖片本身是裝飾用（外層容器 aria-hidden），用 src 屬性直接找比較穩。
      expect(document.querySelector('img[src="https://cdn.example/ad.jpg"]')).toBeTruthy();
    });

    it("null：退回中性圖示，不印 <img>（停損／變差列以外的其餘 kind 維持既有的固定圖示，這裡只測預設分支）", () => {
      renderQueue(ready({ items: [queueItem("q1", { thumbnail_url: null })] }));

      expect(document.querySelector("img")).toBeNull();
    });
  });

  describe("F27-I17 Contract F：清理列（cleanup）", () => {
    it("KindMark fresh「清理」、標題「同時 N 則，預算約撐 M 則」、ThumbTiles 最多 4 格、沒有提案時「看提議」導向 item.action_url", () => {
      renderQueue(ready({
        kinds_pending: [],
        items: [queueItem("q1", {}, null, {
          kind_key: "cleanup",
          cleanup: cleanupPayload({ active_ads: 6, can_support: 4 }),
          action_url: "/brands/brd_1/ads/campaigns/cmp_1/propose/cleanup/cmp_1",
        })],
      }));

      expect(screen.getByText("清理")).toBeTruthy();
      expect(screen.getByText("同時 6 則，預算約撐 4 則")).toBeTruthy();
      const tiles = document.querySelector('[data-slot="thumb-tiles"]');
      expect(tiles).toBeTruthy();

      const link = screen.getByRole("link", { name: "看提議" });
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/propose/cleanup/cmp_1");
      expect(link.getAttribute("data-variant")).not.toBe("ghost");
    });

    it("有提案：跟其餘 multi-item 變更清單同一套 label／連結（proposalAction 的泛用開關）", () => {
      renderQueue(ready({
        kinds_pending: [],
        items: [queueItem("q1", {}, cleanupProposal({ status: "draft" }), {
          kind_key: "cleanup", cleanup: cleanupPayload(),
        })],
      }));

      const link = screen.getByRole("link", { name: "等你核准" });
      // multi:true → 連去活動工作區，不是特定步驟頁。
      expect(link.getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1");
    });

    it("已核對（confirmed）：ghost、isQueueItemDone 為 true", () => {
      const confirmed = cleanupProposal({ status: "approved", verification_state: "confirmed" });
      const item = queueItem("q1", {}, confirmed, { kind_key: "cleanup", cleanup: cleanupPayload() });
      renderQueue(ready({ kinds_pending: [], items: [item] }));

      const link = screen.getByRole("link", { name: "已核對" });
      expect(link.getAttribute("data-variant")).toBe("ghost");
      expect(isQueueItemDone(item)).toBe(true);
    });

    it("沒有提案時 isQueueItemDone 為 false", () => {
      const item = queueItem("q1", {}, null, { kind_key: "cleanup", cleanup: cleanupPayload() });
      expect(isQueueItemDone(item)).toBe(false);
    });
  });

  describe("F27-I17：系統剛恢復期間（recovering），每一列按鈕都換成同一顆佔位", () => {
    it("停損列：按鈕變成 Chip「補完資料後更新」，不是原本的「看提議」連結", () => {
      renderQueue(ready({ items: [queueItem("q1")] }), true);

      expect(screen.queryByRole("link", { name: "看提議" })).toBeNull();
      expect(screen.getByText("補完資料後更新")).toBeTruthy();
    });

    it("補素材列／清理列也不例外（固定按鈕的兩種 kind 一樣被蓋掉）", () => {
      renderQueue(ready({
        kinds_pending: [],
        items: [
          queueItem("q1", {}, null, {
            kind_key: "refresh_creative", refresh: refresh(),
            action_url: "/brands/brd_1/ads/campaigns/cmp_1?tab=assets&material_new=1",
          }),
          queueItem("q2", {}, null, { kind_key: "cleanup", cleanup: cleanupPayload() }),
        ],
      }), true);

      expect(screen.queryByRole("link", { name: "準備新素材" })).toBeNull();
      expect(screen.queryByRole("link", { name: "看提議" })).toBeNull();
      expect(screen.getAllByText("補完資料後更新")).toHaveLength(2);
    });

    it("recovering 為 false（預設）：按鈕照舊，不受影響", () => {
      renderQueue(ready({ items: [queueItem("q1")] }));

      expect(screen.getByRole("link", { name: "看提議" })).toBeTruthy();
      expect(screen.queryByText("補完資料後更新")).toBeNull();
    });
  });

  it("順序：refresh_creative 列永遠排在篩選後清單最後，primary 按鈕落在它前面那列，不管 payload 順序（feature Decisions \"Home rows\"：\"refresh rows...are last in order\"）", () => {
    renderQueue(ready({
      kinds_pending: [],
      items: [
        queueItem("q_refresh", { name: "補素材活動" }, null, {
          kind_key: "refresh_creative", refresh: refresh(),
          action_url: "/brands/brd_1/ads/campaigns/cmp_1?tab=assets&material_new=1",
        }),
        queueItem("q_stop", { name: "停損廣告" }),
      ],
    }));

    const stopLink = screen.getByRole("link", { name: "看提議" });
    const refreshLink = screen.getByRole("link", { name: "準備新素材" });
    expect(stopLink.getAttribute("data-variant")).toBe("default");
    expect(refreshLink.getAttribute("data-variant")).toBe("outline");
  });

  it("kinds_pending 空陣列：佔位列完全消失（F25-I01 之後後端一律回 []）", () => {
    renderQueue(ready({ kinds_pending: [] }));

    expect(screen.queryByText("可加預算")).toBeNull();
    expect(screen.queryByText("補素材")).toBeNull();
    expect(screen.queryByText("接上後開放")).toBeNull();
  });

  it("篩選鈕：單一活動也照印「全部 N」＋那顆活動 pill（v7 行為），不印 id 充當名稱", () => {
    // Lead review fix 2026-09-21：名稱／計數分成兩個 <span>（見下一則測試），DOM 上不再有單一
    // 元素印出「全部 2」這串完整字——可存取名稱（aria-label）還是「名稱 計數」，用 role 查。
    renderQueue(ready({ items: [queueItem("q1"), queueItem("q2")] }));

    expect(screen.getByRole("button", { name: "全部 2" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "晨光隨行杯上市 2" })).toBeTruthy();
    expect(screen.queryByText(/cmp_1/)).toBeNull();
  });

  it("篩選鈕：活動名稱很長也不會把計數擠掉——名稱自己截斷、計數獨立一個 span 永遠印得出來", () => {
    renderQueue(ready({
      items: [
        queueItem("q1", { campaign_id: "cmp_long", campaign_name: "夏季全通路轉換衝刺計畫・北中南三區加碼最終版本" }),
        queueItem("q2", { campaign_id: "cmp_long", campaign_name: "夏季全通路轉換衝刺計畫・北中南三區加碼最終版本" }),
      ],
    }));

    const pill = screen.getByRole("button", { name: "夏季全通路轉換衝刺計畫・北中南三區加碼最終版本 2" });
    expect(pill.getAttribute("title")).toBe("夏季全通路轉換衝刺計畫・北中南三區加碼最終版本");
    // 計數本身是獨立、沒被截斷的元素——不是被塞進同一個 truncate 容器裡看不見。
    expect(within(pill).getByText("2")).toBeTruthy();
  });

  it("列上有活動 chip（跟分類 chip 同一列，F27-I17 換成共用 CampaignChip），截斷有 title 但不印 id", () => {
    // Lead review fix 2026-09-21：`title` 掛在外層、負責截斷寬度的 <span>——`CampaignChip`
    // （do_not_touch）本身沒有 title 插槽。篩選鈕也帶同一個活動名稱的 `title`（見下面的篩選鈕
    // 測試），所以這裡先鎖定列本身的 `data-slot="campaign-chip"`，再往上找帶 title 的外層。
    const { container } = renderQueue(ready({ items: [queueItem("q1")] }));

    const chip = container.querySelector('[data-slot="campaign-chip"]');
    expect(chip).toBeTruthy();
    expect(chip!.closest('span[title="晨光隨行杯上市"]')).toBeTruthy();
  });

  it("多活動：逐活動篩選鈕各自計數、可用鍵盤／滑鼠切換、aria-pressed 反映狀態，篩完只留該活動的列", async () => {
    const user = userEvent.setup();
    renderQueue(ready({
      items: [
        queueItem("q1", { campaign_id: "cmp_1", campaign_name: "晨光隨行杯上市", name: "廣告A" }),
        queueItem("q2", { campaign_id: "cmp_2", campaign_name: "夜間保溫瓶回購", name: "廣告B" }),
      ],
    }));

    const all = screen.getByRole("button", { name: "全部 2" });
    const pillA = screen.getByRole("button", { name: "晨光隨行杯上市 1" });
    const pillB = screen.getByRole("button", { name: "夜間保溫瓶回購 1" });
    expect(all.getAttribute("aria-pressed")).toBe("true");
    expect(pillA.getAttribute("aria-pressed")).toBe("false");

    await user.click(pillB);
    expect(pillB.getAttribute("aria-pressed")).toBe("true");
    expect(all.getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByText("廣告B")).toBeTruthy();
    expect(screen.queryByText("廣告A")).toBeNull();
    // primary 按鈕跟著篩選後的第一列走（兩則都是預設停損列、沒有提案 → 「看提議」）。
    expect(screen.getByRole("link", { name: "看提議" }).getAttribute("data-variant")).toBe("default");
  });

  it("篩選中的活動在重新整理後消失（分流結果換了）：自動退回「全部」，不留一個誰都沒按著的篩選鈕", async () => {
    // Lead review fix 2026-09-21：`filter` state 本身不變，只有 derive 出來的 `active` 退回
    // all——之後同一個活動又回來時篩選還在，不會因為中途沒資料就永久重置。
    const user = userEvent.setup();
    const { rerender } = renderQueue(ready({
      items: [
        queueItem("q1", { campaign_id: "cmp_1", campaign_name: "晨光隨行杯上市", name: "廣告A" }),
        queueItem("q2", { campaign_id: "cmp_2", campaign_name: "夜間保溫瓶回購", name: "廣告B" }),
      ],
    }));

    await user.click(screen.getByRole("button", { name: "夜間保溫瓶回購 1" }));
    expect(screen.getByRole("button", { name: "夜間保溫瓶回購 1" }).getAttribute("aria-pressed")).toBe("true");

    // 重新讀取回來的 payload 不再有 cmp_2（那個活動的分流結果換了，或已經沒有待決定項目）。
    rerender(
      <MemoryRouter>
        <DecisionQueue
          state={ready({ items: [queueItem("q1", { campaign_id: "cmp_1", campaign_name: "晨光隨行杯上市", name: "廣告A" })] })}
          onRetry={() => {}}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole("button", { name: "全部 1" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByRole("button", { name: /夜間保溫瓶回購/ })).toBeNull();
    expect(screen.getByText("廣告A")).toBeTruthy();
  });

  it("空佇列：不重複印「都處理完了」（頁首已經講過），kinds_pending 佔位列照常可見，不印「全部 0」", () => {
    renderQueue(ready());

    expect(screen.getByText("可加預算")).toBeTruthy();
    expect(screen.getByText("補素材")).toBeTruthy();
    expect(screen.getAllByText("接上後開放")).toHaveLength(2);
    expect(screen.queryByText("目前沒有需要你決定的廣告。")).toBeNull();
    expect(screen.queryByText(/^全部/)).toBeNull();
  });

  it("kinds_pending 有未認得的代碼：印「其他」，不印原始代碼", () => {
    renderQueue(ready({ kinds_pending: ["some_future_kind"] }));

    expect(screen.getByText("其他")).toBeTruthy();
    expect(screen.queryByText("some_future_kind")).toBeNull();
  });

  it("鍵盤順序：Tab 先落在篩選鈕（全部→逐活動），再依序落在每一列的按鈕", async () => {
    const user = userEvent.setup();
    renderQueue(ready({
      items: [
        queueItem("q1", { name: "第一列" }),
        queueItem("q2", { name: "第二列", class: "worse", label: "變差" }),
      ],
    }));

    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "全部 2" }));
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "晨光隨行杯上市 2" }));
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("link", { name: "看提議" }));
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("link", { name: "看證據" }));
  });
});
