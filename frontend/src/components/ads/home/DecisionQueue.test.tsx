/** frontend/src/components/ads/home/DecisionQueue.test.tsx — F19-I03：v7 `home()` 的 `row`
 * （prototype ≈ 195–203）落地後的列內容斷言。殼／loading／error 已經是 F19-I02 的範圍
 * （`AdsHomePage.test.tsx` 蓋），這支只管 `DecisionQueue`／`QueueRow` 自己印出來的東西：
 * 兩種分類各自的量尺文案＋寬度、金額格式（最多兩位小數、不四捨五入到整數）、未知數字的兩種
 * 誠實句（量測值「累積中」／配置值「尚未設定」）、只有第一列主要按鈕、按鈕不看量尺畫不畫得
 * 出來、篩選鈕、空狀態不重複頁首那句話＋佔位列同時可見、未認得的 pending 代碼、鍵盤順序。 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { QueueItem, QueuePayload, TriageItem } from "@/lib/adsTriageApi";
import { DecisionQueue, type QueueState } from "./DecisionQueue";

function triageItem(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "ad_1", native_id: "native_1", name: "晨光隨行杯・日常出發", campaign_id: "cmp_1",
    class: "stop_loss", label: "停損", reason_code: "spend_over_stop_loss",
    window: { start: "2026-09-01", end: "2026-09-07", days: 7, previous_start: "2026-08-25", previous_end: "2026-08-31", extended_from: null },
    target: { value: 450, basis: "break_even", result_kind: "purchase", result_label: "購買", missing: [] },
    current: { spend: 5200, result_count: 0, cost_per_result: null, result_kind: "purchase", result_label: "購買", derived_zero_days: 7, reason: null },
    previous: { spend: 4900, result_count: 15, cost_per_result: 326.7, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    change_pct: null, sample: { gate: true, spend_multiple: 3.2, days_with_events: 7 },
    ...overrides,
  };
}

function queueItem(id: string, overrides: Partial<TriageItem> = {}): QueueItem {
  return {
    id, org_id: "org_1", brand_id: "brd_1", campaign_period_id: null, dedupe_key: `k_${id}`,
    category: "ads_triage", kind: null, severity: "rule_warning",
    message: "待決定", action_url: `/brands/brd_1/ads/campaigns/cmp_1?tab=performance`,
    visible_from: null, status: "open", created_at: "2026-09-19T00:00:00Z", resolved_at: null,
    triage: triageItem(overrides),
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

function renderQueue(state: QueueState) {
  return render(
    <MemoryRouter>
      <DecisionQueue state={state} onRetry={() => {}} />
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

  it("量尺畫不出來（目標未知）不影響按鈕：action_url 還在，「看證據」就還在（lead review fix 1）", () => {
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

  it("停損列另外有一顆暫停提議的灰階佔位 chip", () => {
    renderQueue(ready({ items: [queueItem("q1")] }));

    expect(screen.getByText("暫停提議・接上後開放")).toBeTruthy();
  });

  it("只有第一列是主要按鈕樣式，其餘是次要", () => {
    renderQueue(ready({
      items: [
        queueItem("q1"),
        queueItem("q2", { class: "worse", label: "變差", name: "晨光隨行杯・辦公室一角" }),
      ],
    }));

    const links = screen.getAllByRole("link", { name: "看證據" });
    expect(links).toHaveLength(2);
    expect(links[0].getAttribute("data-variant")).toBe("default");
    expect(links[1].getAttribute("data-variant")).toBe("outline");
  });

  it("篩選鈕：只有「全部 N」——活動名稱在 payload 裡不存在，不逐活動分組、不印 id", () => {
    renderQueue(ready({ items: [queueItem("q1"), queueItem("q2")] }));

    expect(screen.getByText("全部 2")).toBeTruthy();
    expect(screen.queryByText(/cmp_1/)).toBeNull();
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

  it("鍵盤順序：Tab 依序落在每一列的「看證據」連結", async () => {
    const user = userEvent.setup();
    renderQueue(ready({
      items: [
        queueItem("q1", { name: "第一列" }),
        queueItem("q2", { name: "第二列", class: "worse", label: "變差" }),
      ],
    }));

    await user.tab();
    expect(document.activeElement).toBe(screen.getAllByRole("link", { name: "看證據" })[0]);
    await user.tab();
    expect(document.activeElement).toBe(screen.getAllByRole("link", { name: "看證據" })[1]);
  });
});
