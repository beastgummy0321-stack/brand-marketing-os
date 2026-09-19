/** frontend/src/components/ads/OverviewTab.test.tsx — F03-I23: 總覽 tab is a pure-props
 * component (no fetch), so this hand-builds a `CampaignDetail` literal and asserts the two
 * bugs the integration review caught are gone: an untracked Meta `0` must never print as
 * 購買, and 目前投放組合計／採用時的計畫 must stay two separately-labelled numbers instead of
 * blending into one. */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AdsActionLine, CampaignDetail, CampaignJudgment, DeliveryGroupRow } from "@/lib/adsApi";
import { OverviewTab } from "./OverviewTab";

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

  it("兩個投放組、10 天期間：目前投放組合計算對，且顯示日預算 × 天數的依據", () => {
    render(
      <OverviewTab
        campaign={campaign({
          groups: [
            group({ id: "g1", daily_budget: 1000 }),
            group({ id: "g2", daily_budget: 500 }),
          ],
          start_date: "2026-01-01",
          end_date: "2026-01-10",
        })}
        onChangeTab={vi.fn()}
      />,
    );

    expect(screen.getByText("NT$ 15,000")).toBeTruthy();
    expect(screen.getByText("日預算 NT$ 1,500／天 × 10 天")).toBeTruthy();
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

  it("labels 是名單時：Campaign 目標與提示句改印「名單」「每筆名單成本」，不是寫死的「購買」", () => {
    render(
      <OverviewTab
        campaign={campaign({
          success_metric: "cpa", success_target: 300,
          labels: { conversion: "名單", count: "名單數", cpa: "每筆名單成本" },
        })}
        onChangeTab={vi.fn()}
      />,
    );

    expect(screen.getByText(/每筆名單成本 目標/)).toBeTruthy();
    expect(screen.getByText(/名單、每筆名單成本、ROAS 等成效數字/)).toBeTruthy();
  });

  it("總覽以已保存的背景時間引導檢討，不再宣稱尚未開放或沒有待決定事項", async () => {
    const user = userEvent.setup(), onChangeTab = vi.fn();
    render(<OverviewTab campaign={campaign({ context_json: { runtime: { last_checked_at: "2026-09-19T01:00:00Z" } } })} onChangeTab={onChangeTab} />);
    expect(screen.getByText(/背景最近檢查/)).toBeTruthy();
    expect(screen.queryByText("自動執行接上後開放")).toBeNull();
    expect(screen.queryByText("目前沒有需要你決定的事")).toBeNull();
    await user.click(screen.getByRole("button", { name: "前往廣告檢討 →" }));
    expect(onChangeTab).toHaveBeenCalledWith("performance");
  });

  it("策略已產生、一個投放組兩則廣告、素材 2/2 就位、status ready：下一步按鈕是「發布 →」，按下去呼叫 onChangeTab(\"publish\")", async () => {
    const user = userEvent.setup();
    const onChangeTab = vi.fn();
    render(
      <OverviewTab
        campaign={campaign({
          status: "ready",
          budget_basis_json: {
            strategy: { allocation: [{ role: "new", label: "新客", pct: 100, rationale: null, amount: null }], why: [], unknowns: [], alternatives: [], learning_goals: [] },
          },
          groups: [
            group({
              ads: [
                {
                  id: "ad_1", campaign_id: "cmp_1", group_id: "grp_1", name: "廣告一",
                  audience_key: null, pain_key: null, angle_key: null, hook_key: null,
                  proof_key: null, offer_key: null, format_key: null, coordinates_snapshot_json: {},
                  product_id: null, asset_ready_source: null, asset_ready_by: null, asset_ready_at: null,
                  external_id: null, external_name: null, external_status: null, local_state: "unbound", bound_at: null,
                },
                {
                  id: "ad_2", campaign_id: "cmp_1", group_id: "grp_1", name: "廣告二",
                  audience_key: null, pain_key: null, angle_key: null, hook_key: null,
                  proof_key: null, offer_key: null, format_key: null, coordinates_snapshot_json: {},
                  product_id: null, asset_ready_source: null, asset_ready_by: null, asset_ready_at: null,
                  external_id: null, external_name: null, external_status: null, local_state: "unbound", bound_at: null,
                },
              ],
            }),
          ],
          asset_readiness: { ready_count: 2, total: 2, pack_id: "pack_1" },
        })}
        onChangeTab={onChangeTab}
      />,
    );

    const button = screen.getByRole("button", { name: "發布 →" });
    await user.click(button);
    expect(onChangeTab).toHaveBeenCalledWith("publish");
  });
});

function importedView(): NonNullable<CampaignDetail["external_view"]> {
  return {
    entities: [{ id: "native-root", platform: "meta", source_account: "account", native_kind: "campaign", native_id: "root", native_label: "活動", name: "平台活動", parent_native_id: null, native_status: "PAUSED", start_date: "2026-08-01", end_date: null, budget_amount: null, budget_type: "daily", budget_raw: { daily_budget: "30000" }, currency: "TWD", last_success_at: "2026-09-19", sync_error: null, creative: {} }],
    observations: [], next_entity_cursor: null, next_observation_cursor: null,
    window: { start: "2026-08-01", end: "2026-09-19" }, connections: [], sync: {}, coverage: {},
  };
}

it("匯入活動使用原總覽但不推算預算、不捏造內部歷程", () => {
  const { container } = render(<OverviewTab campaign={campaign({ origin: "imported", status: "draft", external_view: importedView(), groups: [group()], start_date: "2026-08-01", end_date: "2026-08-10" })} onChangeTab={vi.fn()} />);
  expect(screen.getByText("活動層級預算未知")).toBeTruthy();
  expect(screen.getByText("尚無已讀回成效")).toBeTruthy();
  expect(screen.getByText("平台狀態：已暫停（PAUSED）")).toBeTruthy();
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
