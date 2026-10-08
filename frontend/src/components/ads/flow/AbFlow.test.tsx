import type { LearningEvidence } from "@/lib/adsLearningEvidence";

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
/** frontend/src/components/ads/flow/AbFlow.test.tsx — F29-I14: the A/B "pause the loser" flow (Contract F,
 * `source: "ab"` change sets) on the existing `changes/:setId/{confirm,handoff,verify}` routes — prototype v10
 * `confirmBody()`／`stepPlat()`／`stepChk()` for kind `ab`. Fixtures are shaped like the real reads: the set view
 * carries `source`/`ab` straight off its plan, the live pair comes from `GET …/ab-pairs`, break-even from the campaign
 * triage. Nothing here writes to a platform. */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as abApi from "@/lib/adsAbApi";
import type { AbPair } from "@/lib/adsAbApi";
import * as changeApi from "@/lib/adsChangeApi";
import type { AbChangeBlock, ChangeItem, ChangeSet } from "@/lib/adsChangeApi";
import * as triageApi from "@/lib/adsTriageApi";
import type { CampaignTriage, QueuePayload, TriageItem } from "@/lib/adsTriageApi";
import { ConfirmPage } from "./ConfirmPage";
import { HandoffPage } from "./HandoffPage";
import { VerifyPage } from "./VerifyPage";
import {comparativeEvidenceFixture, pauseEvidenceFixture} from "../patterns/LearningReceipt.fixtures";
import { seedAdsRules } from "../patterns/rules";
import { RULES_FIXTURE } from "../patterns/rulesFixture";

vi.mock("@/components/layout/WorkspaceContext", () => ({ useWorkspace: () => ({ scope: "u:o", identity: { user: { id: "u", email: "a@example.com" }, org: { id: "o", name: "測試", kind: "personal", role: "owner", timezone: "Asia/Taipei", today: "2026-09-28" }, orgs: [] } }) }));
vi.mock("@/lib/adsChangeApi", async (importOriginal) => ({
  ...(await importOriginal<typeof changeApi>()),
  getChangeControl: vi.fn(), approveChangeSet: vi.fn(), decideChangeSet: vi.fn(), createChangeSet: vi.fn(), actOnChangeItem: vi.fn(),
}));
vi.mock("@/lib/adsTriageApi", async (importOriginal) => ({
  ...(await importOriginal<typeof triageApi>()),
  getQueue: vi.fn(), getTriage: vi.fn(),
}));
vi.mock("@/lib/adsAbApi", async (importOriginal) => ({
  ...(await importOriginal<typeof abApi>()),
  getAbPairs: vi.fn(),
}));

const LOSER = "開箱 15 秒・單手開蓋｜1150706 最高數量 - 複本 2";
const WINNER = "晨光隨行杯・日常出發";

const ab: AbChangeBlock = {
  pair_id: "aad_1:aad_2", dimension_label: "開場",
  winner: { ad_id: "aad_2", entity_id: "aex_2", name: WINNER, value_label: "出門情境", cost_per_result: 45.26 },
  loser: { ad_id: "aad_1", entity_id: "aex_1", name: LOSER, value_label: "開箱畫面", cost_per_result: 56.4 },
  window: { start: "2026-09-10", end: "2026-09-16" },
};

function pair(overrides: Partial<AbPair> = {}): AbPair {
  return {
    pair_id: "aad_1:aad_2", group_id: "grp_A", group_name: "廣告組 A", dimension: "hook", dimension_label: "開場",
    a: { ad_id: "aad_1", entity_id: "aex_1", name: LOSER, value_label: "開箱畫面", thumbnail_url: "https://cdn.example/a.jpg", spend: 1128, results: 20, cost_per_result: 56.4 },
    b: { ad_id: "aad_2", entity_id: "aex_2", name: WINNER, value_label: "出門情境", thumbnail_url: "https://cdn.example/b.jpg", spend: 1041, results: 23, cost_per_result: 45.26 },
    window: { start: "2026-09-10", end: "2026-09-16" }, days: 7,
    rules: { min_days: 7, min_conversions_each: 10, relative_difference: 0.1 },
    state: "judged", missing: { days: 0, a_results: 0, b_results: 0 }, winner: "b", difference_pct: 19.8, reason: null,
    decision: { change_set_id: "acs_ab", status: "draft", verification_state: null },
    ...overrides,
  };
}

function changeItem(overrides: Partial<ChangeItem> = {}): ChangeItem {
  return {
    id: "item_ab", kind: "pause", target_id: "aex_1",
    target: { id: "aex_1", name: LOSER, platform: "meta", source_account: "acc_1", native_kind: "ad", native_id: "238500001" },
    before: { status: "ACTIVE" }, after: { status: "PAUSED" },
    reason: "A/B 比較：「開場」用「出門情境」比「開箱畫面」划算，暫停較貴的一則。",
    verification_state: "pending", evidence_json: {}, reported_at: null, first_observed_at: null, verified_at: null, learning: {recorded: false, confidence: null, count: 0, evidence: null}, platform_url: null,
    ...overrides,
  };
}
function abSet(overrides: Partial<ChangeSet> = {}): ChangeSet {
  return {
    id: "acs_ab", campaign_id: "cmp_1", title: `暫停 A/B 比較中較貴的一則：${LOSER}`, month: "2026-09",
    operation_id: "op_ab", content_hash: "h", status: "draft", reason: null, revisit_at: null,
    approval_id: null, created_at: "2026-09-23T02:00:00Z", approved_at: null, items: [changeItem()],
    can_revise: true, source: "ab", ab,
    ...overrides,
  };
}

function triageItem(): TriageItem {
  return {
    entity_id: "aex_2", native_id: "n2", name: WINNER, campaign_id: "cmp_1", campaign_name: "日常商品推廣・轉換",
    thumbnail_url: null, class: "flat", label: "持平", reason_code: "x", grade: "on_target", grade_label: "划算",
    previous_grade: "on_target", grade_move: null,
    window: { start: "2026-09-10", end: "2026-09-23", days: 14, previous_start: "2026-08-27", previous_end: "2026-09-09", extended_from: null },
    target: { value: 450, basis: "own", result_kind: "purchase", result_label: "購買", missing: [], break_even: 520 },
    current: { spend: 1041, result_count: 23, cost_per_result: 45.26, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    previous: { spend: null, result_count: null, cost_per_result: null, result_kind: "purchase", result_label: "購買", derived_zero_days: 0, reason: null },
    change_pct: null, sample: { gate: true, spend_multiple: 2.3, days_with_events: 14 }, campaign_objective: "sales",
  };
}
const emptyQueue: QueuePayload = { items: [], counts: { stop_loss: 0, worse: 0, better: 0, flat: 0, insufficient: 0, no_target: 0 }, total_ads: 0, kinds_available: [], kinds_pending: [] };

function Route3({ step }: { step: "confirm" | "handoff" | "verify" }) {
  const { brandId, campaignId, setId } = useParams<{ brandId: string; campaignId: string; setId: string }>();
  const props = { brandId: brandId ?? "", campaignId: campaignId ?? "", setId: setId ?? "" };
  return step === "confirm" ? <ConfirmPage {...props} /> : step === "handoff" ? <HandoffPage {...props} /> : <VerifyPage {...props} />;
}
function LocationProbe() {
  return <p data-testid="probe-path">{useLocation().pathname}</p>;
}
const base = "/brands/brd_1/ads/campaigns/cmp_1/changes/acs_ab";
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/brands/:brandId/ads/campaigns/:campaignId/changes/:setId/confirm" element={<Route3 step="confirm" />} />
        <Route path="/brands/:brandId/ads/campaigns/:campaignId/changes/:setId/handoff" element={<Route3 step="handoff" />} />
        <Route path="/brands/:brandId/ads/campaigns/:campaignId/changes/:setId/verify" element={<Route3 step="verify" />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}
/** What a block reads on screen: glossary sentences (the hidden `role=tooltip` of each dotted term) are not text. */
function seen(el: Element): string {
  const copy = el.cloneNode(true) as Element;
  copy.querySelectorAll("[role=tooltip]").forEach((tip) => tip.remove());
  return copy.textContent ?? "";
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(triageApi.getQueue).mockResolvedValue(emptyQueue);
  vi.mocked(triageApi.getTriage).mockResolvedValue({ window_days: 14, items: [triageItem()] } as unknown as CampaignTriage);
  vi.mocked(abApi.getAbPairs).mockResolvedValue({ pairs: [pair()], unavailable: null });
  vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [abSet()] });
});

describe("A/B 關掉輸家（F29-I14）確認", () => {
  it("三步流程；關掉 A、留下 B；兩則的每筆與有賺；不會新增花費；核對後寫進筆記本的那句；返回成效", async () => {
    renderAt(`${base}/confirm`);
    expect(await screen.findByRole("heading", { name: "確認關掉輸家" })).toBeTruthy();
    expect(screen.getByText("核准後才到平台操作")).toBeTruthy();
    expect([...document.querySelectorAll("[data-slot=flow-header] ol li")].map((li) => li.textContent)).toEqual(["1確認", "2到平台完成", "3核對結果"]);
    expect(await screen.findByText("關掉 A、留下 B")).toBeTruthy();
    expect(await screen.findByText("日常商品推廣・轉換")).toBeTruthy();
    expect(screen.getByText("✓ 不會新增花費")).toBeTruthy();
    expect(screen.getByText("✓ 關掉不會刪除，想反悔隨時可以再開")).toBeTruthy();
    expect(screen.getByText("B 每筆便宜 20%，兩則都跑滿 7 天、各賣到 10 筆以上")).toBeTruthy();
    const rows = screen.getAllByRole("listitem").filter((li) => /開場：/.test(li.textContent ?? ""));
    expect(rows.map(seen)).toEqual([
      `A開場：開箱畫面${LOSER}近 7 天每筆56 元・有賺（打平 520）關`,
      `B開場：出門情境${WINNER}近 7 天每筆45 元・有賺（打平 520）留`,
    ]);
    expect(screen.getByText("「開場」用「出門情境」比「開箱畫面」划算")).toBeTruthy();
    expect(screen.getByText("每筆 45 vs 56")).toBeTruthy();
    expect(document.querySelector("[data-slot=money-rule]")).toBeTruthy();
    expect(screen.getByRole("button", { name: "核准關掉 A →" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "← 成效" }).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/detail");
    expect(screen.getByRole("link", { name: "✕ 先不要，回投放中心" }).getAttribute("href")).toBe("/brands/brd_1/ads");
    // Not an angle-learning pause: no 「這則主打什麼？」.
    expect(screen.queryByText("這則主打什麼？")).toBeNull();
  });

  it("核准：核准這份清單本身，導去到平台完成", async () => {
    const user = userEvent.setup();
    vi.mocked(changeApi.approveChangeSet).mockResolvedValue(abSet({ status: "approved", approved_at: "2026-09-23T02:05:00Z" }));
    renderAt(`${base}/confirm`);
    await user.click(await screen.findByRole("button", { name: "核准關掉 A →" }));
    await waitFor(() => expect(changeApi.approveChangeSet).toHaveBeenCalled());
    expect(vi.mocked(changeApi.approveChangeSet).mock.calls[0][2].id).toBe("acs_ab");
    expect(changeApi.createChangeSet).not.toHaveBeenCalled();
    // The canonical step of an approved set with nothing reported yet is 到平台完成.
    expect(await screen.findByRole("heading", { name: "到平台完成" })).toBeTruthy();
  });

  it("比較讀不到：凍結的數字照舊，A／B 改用說法稱呼，並說讀取失敗", async () => {
    vi.mocked(abApi.getAbPairs).mockRejectedValue(new Error("down"));
    renderAt(`${base}/confirm`);
    expect(await screen.findByText("關掉「開箱畫面」、留下「出門情境」")).toBeTruthy();
    expect(await screen.findByText(/縮圖、A／B 標記或打平線讀不到/)).toBeTruthy();
    expect(screen.getByText("「出門情境」每筆便宜 20%，兩則都跑滿 7 天、各賣到 10 筆以上")).toBeTruthy();
    expect(screen.getByRole("button", { name: "核准關掉較貴的一則 →" })).toBeTruthy();
  });

  it("比較讀不到時用伺服器給的 A/B 規則（F48 Contract R-API），規則也還沒讀到就只說話不寫數字", async () => {
    vi.mocked(abApi.getAbPairs).mockRejectedValue(new Error("down"));
    seedAdsRules({ ...RULES_FIXTURE, ab: { min_days: 14, min_conversions_each: 20, relative_difference: 0.1 } });
    try {
      const first = renderAt(`${base}/confirm`);
      expect(await screen.findByText("「出門情境」每筆便宜 20%，兩則都跑滿 14 天、各賣到 20 筆以上")).toBeTruthy();
      first.unmount();
      seedAdsRules(null);
      renderAt(`${base}/confirm`);
      expect(await screen.findByText("「出門情境」每筆便宜 20%，兩則都跑滿天數、各賣到足夠的筆數")).toBeTruthy();
    } finally {
      seedAdsRules(RULES_FIXTURE);
    }
  });

  it("已拒絕的清單：只顯示決定，沒有核准；核對頁也導回確認", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [abSet({ status: "rejected", reason: "開箱版還在檔期" })] });
    renderAt(`${base}/confirm`);
    expect(await screen.findByText("已拒絕・開箱版還在檔期")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /核准關掉/ })).toBeNull();
    expect(screen.queryByRole("link", { name: /先不要/ })).toBeNull();
    // Still the A/B card, not a plain stop-loss.
    expect(await screen.findByText("關掉 A、留下 B")).toBeTruthy();
  });

  it("已拒絕的清單走到核對頁：導回確認頁", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [abSet({ status: "rejected", reason: "開箱版還在檔期" })] });
    renderAt(`${base}/verify`);
    await waitFor(() => expect(screen.queryByText("已拒絕・開箱版還在檔期")).toBeTruthy());
  });
});

describe("A/B 關掉輸家（F29-I14）到平台完成與核對", () => {
  const approved = (item: Partial<ChangeItem> = {}) => abSet({ status: "approved", approved_at: "2026-09-23T02:05:00Z", items: [changeItem(item)] });

  it("到平台完成沿用暫停的步驟，點名要關的那一則", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({ targets: [], change_sets: [approved()] });
    renderAt(`${base}/handoff`);
    expect(await screen.findByRole("heading", { name: "到平台完成" })).toBeTruthy();
    expect([...document.querySelectorAll("[data-slot=flow-header] ol li")].map((li) => li.textContent?.replace("已完成", ""))).toEqual(["確認", "2到平台完成", "3核對結果"]);
    expect(screen.getByText(`打開平台上的「${LOSER}」`)).toBeTruthy();
    expect(screen.getByText("把這則廣告的開關關掉")).toBeTruthy();
    expect(await screen.findByText("日常商品推廣・轉換")).toBeTruthy();
  });

  it("confirmed comparison reads served qualification while preserving both frozen side amounts", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [approved({
        verification_state: "confirmed", reported_at: "2026-09-23T02:10:00Z", verified_at: "2026-09-23T02:13:00Z",
        evidence_json: { observed_at: "2026-09-23T02:13:00Z", setting_matches: true },
        learning: { recorded: true, evidence: comparativeEvidenceFixture(), confidence: "observed", count: 3 },
        timeline: { spend_stopped: null, delivery_started: null, next_review_at: null },
      })],
    });
    renderAt(`${base}/verify`);
    expect(await screen.findByText("平台上這則廣告已經關閉")).toBeTruthy();
    expect(screen.getByText("已保留這次比較紀錄")).toBeTruthy();
    expect(screen.getByText("這兩個開場版本的相對比較")).toBeTruthy();
    expect(screen.getByText("多次同向觀察 · 僅能比較兩個版本")).toBeTruthy();
    expect(screen.getByText("獨立觀察 3 次 · 連續同向 3 次 · 反向 0 次")).toBeTruthy();
    expect(screen.getByText(LOSER)).toBeTruthy();
    expect(screen.getByText(WINNER)).toBeTruthy();
    expect(screen.getByText("56 元")).toBeTruthy();
    expect(screen.getByText("45 元")).toBeTruthy();
    expect(screen.queryByText("「開場」用「出門情境」比「開箱畫面」划算")).toBeNull();
    expect(screen.getByText("花費停止")).toBeTruthy();
  });

  it("confirmed readback without recorded learning cannot claim a saved comparison; frozen numbers remain", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({targets: [], change_sets: [approved({
      verification_state: "confirmed", learning: {recorded: false, evidence: null, confidence: null, count: 0},
      evidence_json: {setting_matches: true, observed_at: "2026-09-23T02:13:00Z"},
    })]});
    renderAt(`${base}/verify`);
    await screen.findByText("比較紀錄尚未核實");
    expect(screen.getByText("本次操作尚未留紀錄；來源與適用性尚未核實")).toBeTruthy();
    expect(screen.queryByText("已保留這次比較紀錄")).toBeNull();
    expect(screen.queryByText("已記錄操作")).toBeNull();
    expect(screen.getByText("56 元")).toBeTruthy();
    expect(screen.getByText("45 元")).toBeTruthy();
    expect(screen.getByRole("button", {name: "查看來源與限制 →"}).hasAttribute("disabled")).toBe(true);
  });

  it.each([
    comparativeEvidenceFixture({use_state: "revalidation", support_label: "新結果相反 · 需重新核對", contrary_count: 1, same_direction_count: 1,
      reason_labels: ["新一期結果與過去不同，需重新核對。"], allowed_uses: ["test"]}),
    pauseEvidenceFixture(),
    learningEvidence(),
  ])("legacy confidence cannot promote a contrary, pause-only or unknown comparison", async (evidence) => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({targets: [], change_sets: [approved({
      verification_state: "confirmed", learning: {recorded: true, evidence, confidence: "validated", count: 99},
      evidence_json: {setting_matches: true},
    })]});
    renderAt(`${base}/verify`);
    await screen.findByText("已保留這次比較紀錄");
    expect(screen.getAllByText(evidence.support_label).length).toBeGreaterThan(0);
    expect(screen.getByText(evidence.display_text)).toBeTruthy();
    expect(screen.queryByText("成立")).toBeNull();
    expect(screen.queryByText(/第 99 次|再出現|對這群受眾無效/)).toBeNull();
    expect(screen.getByText("56 元")).toBeTruthy();
  });

  it("核對不符：沒有筆記本那句，回平台改", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [approved({
        verification_state: "deviated", reported_at: "2026-09-23T02:10:00Z",
        evidence_json: { observed_at: "2026-09-23T02:13:00Z", observed: { status: "ACTIVE" } },
      })],
    });
    renderAt(`${base}/verify`);
    expect(await screen.findByText("平台上的狀態和核准的不一樣")).toBeTruthy();
    expect(document.querySelector("[data-slot=learn-line]")).toBeNull();
    expect(screen.getByRole("link", { name: "回平台改成核准內容 →" })).toBeTruthy();
  });

  it("核准失效（stale）：重新檢討回到活動的成效頁，不是單則停損", async () => {
    vi.mocked(changeApi.getChangeControl).mockResolvedValue({
      targets: [], change_sets: [approved({ verification_state: "stale", reported_at: "2026-09-23T02:10:00Z", stale_reason: "這則廣告的設定變了" })],
    });
    renderAt(`${base}/verify`);
    expect((await screen.findByRole("link", { name: "重新檢討 →" })).getAttribute("href")).toBe("/brands/brd_1/ads/campaigns/cmp_1/detail");
  });
});
