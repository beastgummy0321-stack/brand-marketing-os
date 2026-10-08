import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LearningEvidenceSource } from "../patterns/LearningEvidence";
import { StrategyEvidence } from "./StrategyEvidence";
import { StrategyCommitments } from "./StrategyCommitments";
import { evidenceFixture, strategyFixture } from "./strategyEvidence.fixtures";

describe("served strategy learning evidence", () => {
  it("separates an actual unusable citation from unreferenced planner inputs", async () => {
    const user = userEvent.setup();
    const c = strategyFixture();
    c.budget_basis_json.basis!.learnings[0].evidence.use_state = "history";
    c.budget_basis_json.basis!.learnings[0].evidence.allowed_uses = [];
    render(<StrategyEvidence basis={c.budget_basis_json.basis} decision={c.budget_basis_json.strategy!.decision} onBasis={vi.fn()} />);
    expect(screen.queryByText("這份提案未列出可用的歷史引用。")).toBeNull();
    await user.click(screen.getByRole("button", {name: "已引用但目前不可用"}));
    expect(screen.getByText("只看歷史")).toBeTruthy();
    const blocked = screen.getByRole("button", {name: "已引用但目前不可用"}).parentElement!;
    expect(blocked.textContent).toContain("夜跑上班族的反光訊息");
    await user.click(screen.getByRole("button", {name: "未用於提案的資料"}));
    const unreferenced = screen.getByRole("button", {name: "未用於提案的資料"}).parentElement!;
    expect(unreferenced.textContent).not.toContain("夜跑上班族的反光訊息");
    expect(within(blocked).queryByText("可參考")).toBeNull();
  });
  it("shows selected sources and exclusions without calling a control proven market support", async () => {
    const user = userEvent.setup();
    const c = strategyFixture();
    c.budget_basis_json.basis!.planner_context = {product_id: "prd_fixture", forbidden_count: 0,
      offers: [], previous_campaign_id: null, continuation: {month: "2026-09",
        window: {start: "2026-09-01", end: "2026-09-30"}, revision: "source-revision-19",
        source_campaigns: [{campaign_id: "native-campaign", origin: "imported", name: "原生九月活動"}],
        eligible_learning_refs: [{owner: "ad", ref: "current", campaign_id: "native-campaign"}],
        excluded: [{owner: "ad", ref: "excluded-ad", reason_code: "objective_family_mismatch"}]}};
    render(<StrategyEvidence basis={c.budget_basis_json.basis} decision={c.budget_basis_json.strategy!.decision} onBasis={vi.fn()} />);
    expect(screen.getByText("原生九月活動")).toBeTruthy();
    expect(screen.getAllByText("可沿用對照；未證明市場有效").length).toBeGreaterThan(0);
    expect(screen.queryByText("投放目標不同，僅保留歷史")).toBeNull();
    await user.click(screen.getByRole("button", {name: "下一期來源與限制"}));
    expect(screen.getByText("投放目標不同，僅保留歷史")).toBeTruthy();
    expect(screen.getByText("2026-09-01 至 2026-09-30")).toBeTruthy();
    expect(screen.getByText("source-revision-19")).toBeTruthy();
    expect(screen.queryByText("已證明成功")).toBeNull();
  });
  it.each(["missing", "empty", "known"] as const)("keeps %s references distinct without certifying availability", (kind) => {
    const decision = strategyFixture().budget_basis_json.strategy!.decision!;
    const slot = decision.slots[0];
    if (kind === "missing") Reflect.deleteProperty(slot, "evidence_refs");
    else if (kind === "empty") slot.evidence_refs = [];
    render(<StrategyCommitments decision={decision} role={slot.role} stale={false} details />);
    const commitment = document.querySelector("[data-slot=strategy-commitment]") as HTMLElement;
    if (kind === "missing") expect(commitment.textContent).toContain("引用依據尚未提供");
    else expect(commitment.textContent).not.toContain("引用依據尚未提供");
    if (kind === "empty") expect(commitment.textContent).toContain("本次安排未列引用依據");
    else expect(commitment.textContent).not.toContain("本次安排未列引用依據");
    expect(commitment.textContent).not.toContain("沒有可引用的投放紀錄");
  });
  it("keeps backend support labels and excludes history from the proposal card", async () => {
    const user = userEvent.setup();
    const basis = strategyFixture().budget_basis_json.basis!;
    const onBasis = vi.fn();
    render(<StrategyEvidence basis={basis} decision={strategyFixture().budget_basis_json.strategy!.decision} onBasis={onBasis} />);
    expect(screen.getByText("單次觀察 · 樣本少")).toBeTruthy();
    expect(screen.queryByText("重複觀察 · 未證明因果")).toBeNull();
    expect(screen.queryByText("會員優惠訊息在先前活動中表現較佳")).toBeNull();
    await user.click(screen.getByRole("button", {name: "未用於提案的資料"}));
    expect(screen.getByText("重複觀察 · 未證明因果")).toBeTruthy();
    expect(screen.getByText("需重新核對")).toBeTruthy();
    expect(screen.getByText("先前優惠已結束，這期不能沿用它的優惠承諾。")).toBeTruthy();
    await user.click(screen.getByRole("button", {name: "查看依據 →"}));
    expect(onBasis).toHaveBeenCalledOnce();
  });

  it("retains original citations without certifying an old accepted plan as current support", () => {
    const basis = strategyFixture().budget_basis_json.basis!;
    basis.learnings = [{...basis.learnings[0], evidence: evidenceFixture("current", {
      use_state: "history", allowed_uses: [], support_label: "來源尚未核實",
    })}];
    render(<StrategyEvidence basis={basis} onBasis={vi.fn()} />);
    expect(screen.getByText("尚未列出可用引用")).toBeTruthy();
    expect(screen.queryByText("可參考")).toBeNull();
    expect(screen.getByText("新提案仍待驗證，不代表已證明有效。")).toBeTruthy();
  });

  it.each([null, 0])("a null sample differs from a measured zero (%s)", (sample) => {
    const evidence = evidenceFixture("sample", {sample: {result_events: sample, sufficient: sample === null ? null : false},
      independent_count: 17, same_direction_count: 2, contrary_count: 5});
    render(<LearningEvidenceSource evidence={evidence} audienceLabel="下班後夜跑者" />);
    const dl = document.querySelector("[data-slot=learning-source] dl") as HTMLElement;
    expect(within(dl).getByText(sample === null ? "樣本尚未完整核實" : "0 筆")).toBeTruthy();
    expect(within(dl).getByText("17 次")).toBeTruthy();
    expect(within(dl).getByText("2 次")).toBeTruthy();
    expect(within(dl).getByText("5 次")).toBeTruthy();
    expect(screen.getByText("下班後夜跑者")).toBeTruthy();
    expect(dl.textContent).not.toContain("customer-group:");
    expect(within(dl).getByText("來源未提供，尚未核實")).toBeTruthy();
  });

  it("source disclosure preserves period and unknown labels without leaking machine IDs", async () => {
    const user = userEvent.setup();
    render(<LearningEvidenceSource evidence={evidenceFixture("source", {sources: [{kind: null, id: null, version: null,
      label: null, period: {start: null, end: null}}]})} />);
    await user.click(screen.getByRole("button", {name: "完整來源與限制"}));
    expect(screen.getAllByText("來源名稱尚未提供")).toHaveLength(2);
    expect(screen.getAllByText("起日未知 至 迄日未知")).toHaveLength(2);
  });

  it("does not present a missing context as a verified cold start", () => {
    render(<StrategyEvidence basis={undefined} onBasis={vi.fn()} />);
    expect(screen.getByText("歷史適用性尚未核實")).toBeTruthy();
    expect(screen.queryByText("以已確認商品事實和顧客群提出方向。")).toBeNull();
    expect(screen.getByRole("button", {name: "查看依據 →"})).toHaveProperty("disabled", true);
  });

  it.each([null, "none"])("full source shows retained scope and versions, distinguishing unknown offer from none (%s)", async (offer) => {
    const user = userEvent.setup();
    const evidence = evidenceFixture();
    evidence.conditions = {...evidence.conditions, offer_key: offer, valid_until: "2026-10-31"};
    evidence.limits = ["measurement_definition_unknown", "retained-custom-limit"];
    render(<LearningEvidenceSource evidence={evidence} />);
    await user.click(screen.getByRole("button", {name: "完整來源與限制"}));
    const field = (label: string) => screen.getByText(label).parentElement!.querySelector("dd")!;
    expect(field("優惠條件").textContent).toBe(offer === null ? "尚未核實" : "不使用優惠");
    expect(field("成果類型（來源值）").textContent).toBe("purchase");
    expect(field("幣別").textContent).toBe("TWD");
    expect(field("成果歸因方式（來源值）").textContent).toBe("7d_click");
    expect(field("來源識別").textContent).toBe("cmp_previous");
    expect(field("來源版本").textContent).toBe("source-1");
    expect(field("價格版本").textContent).toBe("price-1");
    expect(field("素材版本").textContent).toBe("material-1");
    expect(field("投放設定版本").textContent).toBe("target-1");
    expect(field("有效期限").textContent).toBe("2026/10/31");
    expect(screen.getByText(/成果量測與歸因定義尚未核實/)).toBeTruthy();
    expect(screen.getByText("(retained-custom-limit)")).toBeTruthy();
  });
});
