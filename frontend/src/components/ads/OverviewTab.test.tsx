/** frontend/src/components/ads/OverviewTab.test.tsx — F03-I23: 總覽 tab is a pure-props
 * component (no fetch), so this hand-builds a `CampaignDetail` literal and asserts the two
 * bugs the integration review caught are gone: an untracked Meta `0` must never print as
 * 購買. F48-I10 (Contract M): 總預算 is the server's one `budget_total` — after adoption it equals the chosen
 * total, so the old 目前投放組合計／採用時的計畫 pair is gone and nothing is re-derived here. */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AdsActionLine, CampaignDetail, CampaignJudgment, DeliveryGroupRow } from "@/lib/adsApi";
import { OverviewTab } from "./OverviewTab";
// F50 Contract K: the org clock reads the workspace org zone; dates assert Asia/Taipei output, never the runner's.
vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "user:org", identity: { user: { id: "u", email: "a@example.com" }, org: { id: "o", name: "測試", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-10-01" }, orgs: [] } }) }));

function group(overrides: Partial<DeliveryGroupRow> = {}): DeliveryGroupRow {
  return {
    id: "grp_1",
    campaign_id: "cmp_1",
    channel_key: "meta",
    name: "投放組",
    role: "new",
    daily_budget: 1000,
    start_date: null,
    end_date: null,
    ads: [],
    external_id: null,
    external_name: null,
    external_status: null,
    local_state: "unbound",
    bound_at: null,
    ...overrides,
  };
}

function campaign(overrides: Partial<CampaignDetail> = {}): CampaignDetail {
  return {
    id: "cmp_1",
    name: "測試 Campaign",
    goal_text: "想在雙十一衝一波業績",
    objective: "conversion",
    cap: { value: null, basis: null, own_value: null, break_even: null, price: null, product_id: null, result_kind: "purchase", result_label: "購買", missing: ["product"], revision: 0 },
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
    judgment: { tone: "neutral", text: "投放中", detail: "還沒有花費資料" },
    action_lines: [],
    external_id: null,
    external_name: null,
    external_status: null,
    local_state: "unbound",
    bound_at: null,
    ...overrides,
  };
}

describe("OverviewTab（F03-I23）", () => {
  it("已發布但 outcome 全是 0：印「還沒有成效資料」，畫面上不出現「購買」這個假 0", () => {
    render(
      <OverviewTab
        campaign={campaign({ status: "live", outcome: { spend: 0, purchases: 0, revenue: 0 } })}
        onChangeTab={vi.fn()}
      />,
    );

    expect(screen.getByText("還沒有成效資料")).toBeTruthy();
    expect(screen.queryByText("購買")).toBeNull();
  });

  it("F48 Contract M: 總預算 is the server's budget_total as sent — never re-derived from the groups in the browser", () => {
    render(
      <OverviewTab
        campaign={campaign({
          // The groups would sum to 15,000 over 10 days; the served total is what prints.
          groups: [
            group({ id: "g1", daily_budget: 1000 }),
            group({ id: "g2", daily_budget: 500 }),
          ],
          start_date: "2026-01-01",
          end_date: "2026-01-10",
          budget_total: 14990,
          outcome: { spend: 3000, purchases: 2, revenue: 4000 },
        })}
        onChangeTab={vi.fn()}
      />,
    );

    expect(screen.getByText("NT$ 14,990")).toBeTruthy();
    expect(screen.queryByText("NT$ 15,000")).toBeNull();
    expect(screen.getByText("投放組每日預算 × 投放天數")).toBeTruthy();
    expect(screen.queryByText(/1,500/)).toBeNull();
    // No share of the total is priced here.
    expect(screen.queryByText(/佔總預算/)).toBeNull();
  });

  it("a chosen budget before the plan is adopted: 總預算 says it is not set yet and names the chosen amount once", () => {
    render(<OverviewTab campaign={campaign({ status: "draft", budget_planned: 30000, budget_total: null })} onChangeTab={vi.fn()} />);
    expect(screen.getByText("已選 NT$ 30,000，展開投放組後算總預算")).toBeTruthy();
  });

  it("budget_planned 跟起訖日都是 null：顯示「尚未設定」，不顯示「累積中」", () => {
    render(
      <OverviewTab
        campaign={campaign({ budget_planned: null, start_date: null, end_date: null })}
        onChangeTab={vi.fn()}
      />,
    );

    expect(screen.getAllByText("尚未設定").length).toBeGreaterThan(0);
    expect(screen.queryByText(/累積中/)).toBeNull();
  });

  it("judgment 是後端組好的句子：畫面原樣印，前端不重拼", () => {
    const judgment: CampaignJudgment = {
      tone: "warn",
      text: "投放中，預算花得比時間快",
      detail: "第 3／10 天，已花費佔預算 45%",
    };
    render(<OverviewTab campaign={campaign({ judgment })} onChangeTab={vi.fn()} />);

    expect(screen.getByText("投放中，預算花得比時間快")).toBeTruthy();
  });

  it("action_lines 是空陣列：印誠實空狀態，且原始 JSON 鍵值不外洩", () => {
    render(<OverviewTab campaign={campaign({ action_lines: [] })} onChangeTab={vi.fn()} />);

    expect(screen.getByText("這個 Campaign 還沒有異動紀錄。")).toBeTruthy();
    expect(screen.queryByText(/daily_budget/)).toBeNull();
  });

  it("有異動紀錄時印後端組好的三句話", () => {
    const line: AdsActionLine = {
      campaign_id: "cmp_1",
      campaign_name: "測試 Campaign",
      time_text: "3 小時前",
      title: "調整了每日預算",
      detail: "從 NT$ 1,000 調整為 NT$ 1,500",
    };
    render(<OverviewTab campaign={campaign({ action_lines: [line] })} onChangeTab={vi.fn()} />);

    expect(screen.getByText("調整了每日預算")).toBeTruthy();
    expect(screen.queryByText(/daily_budget/)).toBeNull();
  });

  it("labels 是名單時：上限與提示句改印「名單」「每筆名單成本」，不是寫死的「購買」", () => {
    render(
      <OverviewTab
        campaign={campaign({
          cap: { value: 300, basis: "own", own_value: 300, break_even: null, price: null, product_id: null, result_kind: "purchase", result_label: "購買", missing: [], revision: 1 },
          labels: { conversion: "名單", count: "名單數", cpa: "每筆名單成本" },
        })}
        onChangeTab={vi.fn()}
      />,
    );

    expect(screen.getByText(/每筆名單成本上限 NT\$ 300/)).toBeTruthy();
    expect(screen.getByText(/名單、每筆名單成本、ROAS 等成效數字/)).toBeTruthy();
  });

  it("總覽以已保存的背景時間引導檢討，不再宣稱尚未開放或沒有待決定事項", async () => {
    const user = userEvent.setup(), onChangeTab = vi.fn();
    render(<OverviewTab campaign={campaign({ context_json: { runtime: { last_checked_at: "2026-09-19T01:00:00Z" } } })} onChangeTab={onChangeTab} />);
    expect(screen.getByText(/背景最近檢查/)).toBeTruthy();
    expect(screen.queryByText("自動執行接上後開放")).toBeNull();
    expect(screen.queryByText("目前沒有需要你決定的事")).toBeNull();
    await user.click(screen.getByRole("button", { name: "前往廣告檢討 →" }));
    expect(onChangeTab).toHaveBeenCalledWith("perf");
  });

  it("the old stage timeline, next-step card and shortcut tiles are gone (rail, bar and tabs carry them)", () => {
    render(<OverviewTab campaign={campaign()} onChangeTab={vi.fn()} />);
    expect(screen.queryByText("狀態時間軸")).toBeNull();
    expect(screen.queryByText("更多 Campaign 資訊")).toBeNull();
    expect(screen.queryByRole("button", { name: /發布 →|前往策略 →/ })).toBeNull();
  });
});

function importedView(): NonNullable<CampaignDetail["external_view"]> {
  return {
    entities: [{ id: "native-root", platform: "meta", source_account: "account", native_kind: "campaign", native_id: "root", native_label: "活動", name: "平台活動", parent_native_id: null, native_status: "PAUSED", delivery_label: "已暫停", start_date: "2026-08-01", end_date: null, budget_amount: null, budget_type: "daily", budget_raw: { daily_budget: "30000" }, currency: "TWD", last_success_at: "2026-09-19", sync_error: null, creative: {} }],
    observations: [], next_entity_cursor: null, next_observation_cursor: null,
    window: { start: "2026-08-01", end: "2026-09-19" }, connections: [], sync: {}, coverage: {},
  };
}

it("匯入活動使用原總覽但不推算預算、不捏造內部歷程", () => {
  const { container } = render(<OverviewTab campaign={campaign({ origin: "imported", status: "draft", external_view: importedView(), groups: [group()], start_date: "2026-08-01", end_date: "2026-08-10" })} onChangeTab={vi.fn()} />);
  expect(screen.getByText("活動層級預算未知")).toBeTruthy();
  expect(screen.getByText("尚無已讀回成效")).toBeTruthy();
  // F49 Contract L: the root's served delivery word, never the platform code.
  expect(screen.getByText("平台狀態：已暫停")).toBeTruthy();
  expect(document.body.textContent).not.toContain("PAUSED");
  expect(screen.queryByText("草稿")).toBeNull();
  expect(container.querySelectorAll(".bg-success").length).toBe(0);
  expect(screen.queryByText(/日預算.*×/)).toBeNull();
});
it("原生活動有預算時保留幣別與預算方式，不跨層加總花費", () => {
  const view = importedView(); view.entities[0].budget_amount = 300;
  view.observations = [{ id: "o", entity_id: "native-root", day: "2026-09-01", metric_scope: "campaign", attribution_key: "default", currency: "USD", spend: 42, impressions: null, clicks: null, purchases: null, revenue: null, availability: {} }];
  render(<OverviewTab campaign={campaign({ origin: "imported", external_view: view })} onChangeTab={vi.fn()} />);
  expect(screen.getByText("300 TWD")).toBeTruthy();
  expect(screen.getByText("查看成效分頁")).toBeTruthy();
});
it("匯入活動：平台連線、最近成功與重新讀取平台在這個收合裡；同步失敗照原句顯示", async () => {
  const user = userEvent.setup(), onSync = vi.fn();
  const view = importedView();
  view.connections = [{ platform: "meta", source_account: "act_1150706", state: "connected" }];
  view.sync = { entities: { last_success_at: "2026-09-19T01:00:00Z" }, insights: { error: "權限不足" } };
  render(<OverviewTab campaign={campaign({ origin: "imported", external_view: view })} onChangeTab={vi.fn()} platformSync={{ onSync, syncing: false, error: "同步失敗：授權過期" }} />);
  expect(screen.getByText(/Meta · act_1150706 · 已連線/)).toBeTruthy();
  expect(screen.getByText(/insights：權限不足/)).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toBe("同步失敗：授權過期");
  await user.click(screen.getByRole("button", { name: "重新讀取平台" }));
  expect(onSync).toHaveBeenCalledTimes(1);
});
it("F49 Contract L: a root without a served delivery word reads 平台狀態不明", () => {
  const view = importedView(); delete view.entities[0].delivery_label;
  render(<OverviewTab campaign={campaign({ origin: "imported", external_view: view })} onChangeTab={vi.fn()} />);
  expect(screen.getByText("平台狀態：平台狀態不明")).toBeTruthy();
});
it("F49 Contract O: the last platform read's served outcome prints under 重新讀取平台 (a failed read names why)", () => {
  render(<OverviewTab campaign={campaign({ origin: "imported", external_view: importedView() })} onChangeTab={vi.fn()}
    platformSync={{ onSync: vi.fn(), syncing: false, error: "", note: { state: "failed", text: "這次沒讀到平台資料：平台授權已失效或權限不足，請重新授權" } }} />);
  const status = screen.getByRole("status");
  expect(status.textContent).toBe("這次沒讀到平台資料：平台授權已失效或權限不足，請重新授權");
  expect(status.className).toContain("text-danger");
});
