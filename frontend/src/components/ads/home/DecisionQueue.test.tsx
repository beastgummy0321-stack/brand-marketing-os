/** frontend/src/components/ads/home/DecisionQueue.test.tsx — F19-I03：v7 `home()` 的 `row`
 * （prototype ≈ 195–203）落地後的列內容斷言。殼／loading／error 已經是 F19-I02 的範圍
 * （`AdsHomePage.test.tsx` 蓋），這支只管 `DecisionQueue`／`QueueRow` 自己印出來的東西：
 * 兩種分類各自的量尺文案＋寬度、金額格式（最多兩位小數、不四捨五入到整數）、未知數字的兩種
 * 誠實句（量測值「累積中」／配置值「尚未設定」）、只有第一列主要按鈕、按鈕不看量尺畫不畫得
 * 出來、篩選鈕、空狀態不重複頁首那句話＋佔位列同時可見、未認得的 pending 代碼、鍵盤順序。 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { QueueItem, QueuePayload, TriageItem } from "@/lib/adsTriageApi";
import { DecisionQueue, type QueueState } from "./DecisionQueue";

function triageItem(overrides: Partial<TriageItem> = {}): TriageItem {
  return {
    entity_id: "ad_1", native_id: "native_1", name: "晨光隨行杯・日常出發", campaign_id: "cmp_1",
    campaign_name: "晨光隨行杯上市",
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

  it("列上有活動 chip（跟分類 chip 同一列），截斷有 title 但不印 id", () => {
    // Lead review fix 2026-09-21：`title` 掛在外層 chip（Badge 本身），不是內層負責 truncate
    // 的 <span>——放在內層會被 Badge 自己的 `justify-center` 置中裁掉左右兩端、印不出省略號。
    // 篩選鈕也帶同一個活動名稱的 `title`（見下面的篩選鈕測試），所以這裡用列本身的 `data-slot
    // ="badge"` 標籤鎖定，不是篩選鈕的 `<button>`。
    const { container } = renderQueue(ready({ items: [queueItem("q1")] }));

    const chip = container.querySelector('span[data-slot="badge"][title="晨光隨行杯上市"]');
    expect(chip).toBeTruthy();
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
    // primary 按鈕跟著篩選後的第一列走。
    expect(screen.getByRole("link", { name: "看證據" }).getAttribute("data-variant")).toBe("default");
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

  it("鍵盤順序：Tab 先落在篩選鈕（全部→逐活動），再依序落在每一列的「看證據」連結", async () => {
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
    expect(document.activeElement).toBe(screen.getAllByRole("link", { name: "看證據" })[0]);
    await user.tab();
    expect(document.activeElement).toBe(screen.getAllByRole("link", { name: "看證據" })[1]);
  });
});
