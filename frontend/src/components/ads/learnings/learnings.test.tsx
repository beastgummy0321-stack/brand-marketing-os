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
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { CoordinateLearnings, LearningCampaign, LearningRow } from "@/lib/adsLearningsApi";
import { GroupSummary } from "./GroupSummary";
import { LearningsTab, learningsCount, type LearningsLoad } from "./LearningsTab";
import { LearningsTable } from "./LearningsTable";
import { RULES_FIXTURE } from "../patterns/rulesFixture";

const G_STUDY = { id: "pcg_study", who: "學生備考" };
const G_COMMUTE = { id: "pcg_commute", who: "通勤上班族" };
const G_GONE = { id: "pcg_gone", who: "已刪除的顧客群" };

const coords = (pain: string, angle: string, format = "單張圖") => [
  { dimension: "audience", dimension_label: "受眾", key: "cold", label: "沒聽過品牌的人" },
  { dimension: "pain", dimension_label: "痛點", key: "effort", label: pain },
  { dimension: "angle", dimension_label: "角度", key: "box", label: angle },
  { dimension: "offer", dimension_label: "優惠", key: "bundle3", label: "三盒組 NT$999" },
  { dimension: "format", dimension_label: "格式", key: "single_image", label: format },
];

let n = 0;
const row = (o: Partial<LearningRow> & Pick<LearningRow, "rank" | "of" | "ad_name">): LearningRow => ({
  ad_id: `ada_${++n}`, customer_group: G_STUDY, coordinates: coords("考前熬夜讀不完", "書包裡放一盒就好"),
  spend: 0, sales: 0, cost_per_sale: null, verdict: "replace", verdict_label: "換掉", flags: [], evidence: learningEvidence(), learning_id: `lrn_${n}`,
  ...o,
});

// Drill-10 shape: cap 450, nothing under it → the best and those within 30% are 留下 (相對最好), 沒賣出 last.
const B: LearningCampaign = {
  campaign_id: "adc_B", campaign_name: "三盒組・09/19～10/01", sell_way_id: "prd_box",
  start_date: "2026-09-19", end_date: "2026-10-01", closed_on: "2026-10-02", cap: 450, currency: "TWD",
  spend: 16301, sales: 20, cost_per_sale: 815.05, counts: { keep: 3, replace: 3 },
  rule_text: "沒有一則低於上限 450 → 留下最好的 555 和 721 以內的；其餘換掉", empty_reason: null,
  rows: [
    row({ rank: 1, of: 6, ad_name: "考前一週・書包一盒", spend: 2775, sales: 5, cost_per_sale: 555, verdict: "keep_relative", verdict_label: "留下", flags: ["相對最好，仍高於上限"] }),
    row({ rank: 2, of: 6, ad_name: "通勤族・地鐵十分鐘", customer_group: G_COMMUTE, spend: 3720, sales: 6, cost_per_sale: 620, verdict: "keep_relative", verdict_label: "留下", flags: ["相對最好，仍高於上限"] }),
    row({ rank: 3, of: 6, ad_name: "備考生・圖書館閉館前", spend: 2100, sales: 3, cost_per_sale: 700, verdict: "keep_relative", verdict_label: "留下", flags: ["樣本少", "相對最好，仍高於上限"] }),
    row({ rank: 4, of: 6, ad_name: "早晨第一顆", customer_group: G_GONE, spend: 3000, sales: 4, cost_per_sale: 750, flags: ["樣本少"] }),
    row({ rank: 5, of: 6, ad_name: "通勤族・下班後加班", customer_group: null, spend: 3286, sales: 2, cost_per_sale: 1643, flags: ["樣本少"] }),
    row({ rank: 6, of: 6, ad_name: "會議前・午休五分鐘", customer_group: G_COMMUTE, spend: 1420, sales: 0, cost_per_sale: null }),
  ],
};
const A: LearningCampaign = {
  campaign_id: "adc_A", campaign_name: "三盒組・09/05～09/18", sell_way_id: "prd_box",
  start_date: "2026-09-05", end_date: "2026-09-18", closed_on: "2026-09-19", cap: 450, currency: "TWD",
  spend: 4698, sales: 6, cost_per_sale: 783, counts: { keep: 1, replace: 1 },
  rule_text: "1 則每筆低於上限 450 → 留下；其餘換掉", empty_reason: null,
  rows: [
    row({ rank: 1, of: 2, ad_name: "備考生・讀到深夜", spend: 1160, sales: 4, cost_per_sale: 290, verdict: "keep", verdict_label: "留下", flags: ["樣本少"] }),
    row({ rank: 2, of: 2, ad_name: "通勤族・早上第一顆", customer_group: G_COMMUTE, spend: 3538, sales: 2, cost_per_sale: 1769, flags: ["樣本少"] }),
  ],
};
const GAP: LearningCampaign = {
  campaign_id: "adc_gap", campaign_name: "單盒・09/01～09/04", sell_way_id: "prd_single",
  start_date: "2026-09-01", end_date: "2026-09-04", closed_on: "2026-09-05", cap: null, currency: null,
  spend: null, sales: null, cost_per_sale: null, counts: { keep: 0, replace: 0 },
  rule_text: "", empty_reason: "資料缺天，這期沒有記學習", rows: [],
};
const DATA: CoordinateLearnings = {
  evidence_context: evidenceContext, campaigns: [B, A, GAP],
  groups: [
    { customer_group_id: "pcg_study", who: "學生備考", ads: 3, spend: 6035, sales: 12, cap: 450, cost_per_sale: 502.9 },
    { customer_group_id: "pcg_gone", who: "已刪除的顧客群", ads: 1, spend: 3000, sales: 4, cap: 450, cost_per_sale: 750 },
    { customer_group_id: "pcg_commute", who: "通勤上班族", ads: 3, spend: 8678, sales: 8, cap: 450, cost_per_sale: 1084.75 },
  ],
  next: { sell_way_id: "prd_box", new_campaign_href: "/brands/brd_1/ads/new?sell_way=prd_box" },
};

function tab(state: LearningsLoad, opts: { highlight?: string; onRetry?: () => void } = {}) {
  return render(
    <MemoryRouter>
      <LearningsTab brandId="brd_1" state={state} onRetry={opts.onRetry ?? vi.fn()} highlightCampaignId={opts.highlight} />
    </MemoryRouter>,
  );
}
const rowsOf = (name: string) => within(screen.getByRole("table", { name: `${name} 每則廣告排名` })).getAllByRole("row").slice(1);

describe("LearningsTab 投放學到的", () => {
  it("keeps the served rank order, 沒賣出 last, verdict chips and flags", () => {
    tab({ status: "ready", data: DATA });
    const rows = rowsOf(B.campaign_name);
    expect(rows.map((r) => r.getAttribute("data-verdict"))).toEqual(["keep_relative", "keep_relative", "keep_relative", "replace", "replace", "replace"]);
    expect(within(rows[0]).getByText("考前一週・書包一盒")).toBeTruthy();
    expect(within(rows[0]).getByText("555")).toBeTruthy();
    expect(within(rows[0]).getByText("2,775")).toBeTruthy();
    expect(within(rows[0]).getByText("留下")).toBeTruthy();
    expect(within(rows[0]).getByText("相對最好，仍高於上限")).toBeTruthy();
    expect(within(rows[2]).getByText("樣本少")).toBeTruthy();
    expect(within(rows[5]).getByText("沒賣出")).toBeTruthy();
    expect(within(rows[5]).getByText("換掉")).toBeTruthy();
    // Row without a group and a deleted group print what the server says, never a guess.
    expect(within(rows[4]).getByText("未指定")).toBeTruthy();
    expect(within(rows[3]).getByText("已刪除的顧客群")).toBeTruthy();
    // Under the cap → success colour; 1,769 is over it.
    expect(within(rowsOf(A.campaign_name)[0]).getByText("290").className).toContain("text-success");
  });

  it("campaign header chips: closed MM/DD, cap, totals, 留下／換掉 counts and the rule text", () => {
    tab({ status: "ready", data: DATA });
    const b = screen.getByRole("region", { name: B.campaign_name });
    expect(within(b).getByText("10/02 結案")).toBeTruthy();
    expect(within(b).getByText("上限 450")).toBeTruthy();
    expect(within(b).getByText("花 16,301・成交 20・每筆 815")).toBeTruthy();
    expect(within(b).getByText("留下 3")).toBeTruthy();
    expect(within(b).getByText("換掉 3")).toBeTruthy();
    expect(within(b).getByText(B.rule_text)).toBeTruthy();
    expect(within(b).getByRole("link", { name: "到這個活動 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/adc_B");
    expect(within(b).queryByText(/2026-/)).toBeNull();
  });

  it("a campaign with empty_reason prints the sentence instead of a table, and no cap chip when cap is null", () => {
    tab({ status: "ready", data: DATA });
    const gap = screen.getByRole("region", { name: GAP.campaign_name });
    expect(within(gap).getByText("資料缺天，這期沒有記學習")).toBeTruthy();
    expect(within(gap).queryByRole("table")).toBeNull();
    expect(within(gap).queryByText(/上限/)).toBeNull();
    expect(within(gap).getByText("09/05 結案")).toBeTruthy();
  });

  it("coordinates are folded per row and toggle open", () => {
    tab({ status: "ready", data: DATA });
    const first = rowsOf(B.campaign_name)[0];
    const toggle = within(first).getByRole("button", { name: "座標：考前一週・書包一盒" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(within(first).queryByText("痛點")).toBeNull();
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(within(first).getByText("痛點")).toBeTruthy();
    expect(within(first).getByText("考前熬夜讀不完")).toBeTruthy();
    expect(document.getElementById(toggle.getAttribute("aria-controls") ?? "")).toBeTruthy();
    fireEvent.click(toggle);
    expect(within(first).queryByText("痛點")).toBeNull();
  });

  it("header: next-plan link to next.new_campaign_href, rule strip and group summary", () => {
    tab({ status: "ready", data: DATA });
    expect(screen.getByRole("link", { name: "用這些學習排下一期 →" }).getAttribute("href")).toBe("/brands/brd_1/ads/new?sell_way=prd_box");
    // The strip prints the newest ranked campaign's served rule_text, then the served sample flag (no constant here).
    const strip = screen.getByLabelText("怎麼判");
    expect(within(strip).getByText(`最近一期：${B.rule_text}`)).toBeTruthy();
    expect(strip.textContent).toContain(`成交少於 ${RULES_FIXTURE.grade.sample_few} 筆標「${RULES_FIXTURE.labels.flags.few}」`);
    expect(screen.getByRole("heading", { name: "各顧客群・3 期合計" })).toBeTruthy();
    const groups = screen.getAllByRole("listitem");
    expect(groups.map((g) => g.getAttribute("data-group"))).toEqual(["pcg_study", "pcg_gone", "pcg_commute"]);
  });

  it("highlights the campaign from ?campaign= with 剛結案", () => {
    tab({ status: "ready", data: DATA }, { highlight: "adc_A" });
    expect(within(screen.getByLabelText("怎麼判")).getByText(`這一期：${A.rule_text}`)).toBeTruthy();
    const a = screen.getByRole("region", { name: A.campaign_name });
    expect(a.getAttribute("data-highlight")).toBe("true");
    expect(within(a).getByText("剛結案")).toBeTruthy();
    expect(screen.getByRole("region", { name: B.campaign_name }).getAttribute("data-highlight")).toBeNull();
    expect(screen.getAllByText("剛結案")).toHaveLength(1);
  });

  it("empty state: 還沒有結案的活動 with 到投放中心, no next link", () => {
    tab({ status: "ready", data: { evidence_context: evidenceContext, campaigns: [], groups: [], next: null } });
    expect(screen.getByText("還沒有結案的活動")).toBeTruthy();
    expect(screen.getByRole("link", { name: "到投放中心" }).getAttribute("href")).toBe("/brands/brd_1/ads");
    expect(screen.queryByRole("link", { name: "用這些學習排下一期 →" })).toBeNull();
  });

  it("a failed read says so with 重新讀取, never the empty state", () => {
    const onRetry = vi.fn();
    tab({ status: "error", message: "讀取投放學到的失敗。" }, { onRetry });
    expect(screen.getByRole("alert").textContent).toContain("讀取失敗");
    expect(screen.queryByText("還沒有結案的活動")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "重新讀取" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("count = ranked rows across campaigns", () => {
    expect(learningsCount(DATA)).toBe(8);
  });
});

describe("LearningsTable compact / GroupSummary", () => {
  it("compact drops 花費／成交 and the totals chip and the campaign link", () => {
    render(<MemoryRouter><LearningsTable campaign={B} compact campaignHref="/x" /></MemoryRouter>);
    const header = screen.getAllByRole("row")[0];
    expect(within(header).queryByText("花費")).toBeNull();
    expect(within(header).getByText("廣告｜顧客群")).toBeTruthy();
    expect(screen.queryByText(/^花 /)).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getAllByRole("row")).toHaveLength(7);
  });

  it("group with cap: 低於／高於上限; null cap: no chip; null cost: 沒賣出", () => {
    render(
      <GroupSummary
        groups={[
          { customer_group_id: "g1", who: "學生備考", ads: 2, spend: 900, sales: 3, cap: 450, cost_per_sale: 300 },
          { customer_group_id: "g2", who: "通勤上班族", ads: 2, spend: 3000, sales: 2, cap: 450, cost_per_sale: 1500 },
          { customer_group_id: "g3", who: "爸媽", ads: 1, spend: 500, sales: 0, cap: null, cost_per_sale: null },
        ]}
      />,
    );
    const [g1, g2, g3] = screen.getAllByRole("listitem");
    expect(within(g1).getByText("低於上限")).toBeTruthy();
    expect(within(g2).getByText("高於上限")).toBeTruthy();
    expect(within(g3).getByText("沒賣出")).toBeTruthy();
    expect(within(g3).queryByText(/上限/)).toBeNull();
    expect(screen.getAllByText("上限 450")).toHaveLength(1);
  });
});


it("different campaign caps cannot produce one group cap or a judgment", () => {
  render(<GroupSummary groups={[{customer_group_id: "mixed", who: "跨活動顧客", ads: 2, spend: 900, sales: 3, cap: 450, caps_differ: true, cost_per_sale: null}]} />);
  expect(screen.getByText("各活動上限或幣別不同")).toBeTruthy();
  expect(screen.queryByText("上限 450")).toBeNull();
  expect(screen.queryByText(/低於上限|高於上限|沒賣出/)).toBeNull();
  expect(screen.getByRole("listitem").textContent).toContain("不明");
});
