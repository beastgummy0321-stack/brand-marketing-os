import { useState } from "react";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { EmptyState } from "@/components/layout/EmptyState";
import { SidePanel } from "@/components/layout/SidePanel";
import { formatCurrency } from "@/lib/format";
import {
  adoptStrategy,
  generateStrategy,
  patchCampaign,
  selectScenario,
  setAllocation,
  type CampaignDetail,
  type StrategyRole,
} from "@/lib/adsApi";
import { ActionBar, AllocationBar, Disclosure, formatAmount } from "./patterns";
import { nextStep, type StepTarget } from "./nextStep";
import { CapBlock } from "./strategy/CapBlock";
import { BudgetScenarios, scenarioRow, type OverCapPending } from "./strategy/BudgetScenarios";

const ROLE_LABEL: Record<StrategyRole, string> = { new: "新客", retarget: "再行銷", explore: "探索" };
const errorText = (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback);

/** 策略 tab（F28-I09，prototype v9 `tabStrategy()`）：一個上限（`CapBlock`）→ 這一期的總預算（`BudgetScenarios`，
 * internal only）→ 預算怎麼分 → 兩個收合（為什麼這樣建議／進階設定），底部一條動作列。The page decides nothing
 * about money itself: scenarios, over-cap amounts and the cap all come from the API; the only local state is what the
 * user has picked and not saved yet. */
export function StrategyTab({
  brandId,
  campaign: c,
  onCampaignChange,
  onChangeTab,
}: {
  brandId: string;
  campaign: CampaignDetail;
  onCampaignChange: (campaign: CampaignDetail) => void;
  onChangeTab: (target: StepTarget) => void;
}) {
  const imported = c.origin === "imported";
  const readonlyReason = c.capabilities?.unavailable.strategy ?? "既有活動保留平台設定，不使用內部策略與預算操作。";
  const [goal, setGoal] = useState(c.goal_text ?? "");
  const [goalSaving, setGoalSaving] = useState(false);
  const [goalError, setGoalError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [pending, setPending] = useState<OverCapPending | null>(null);
  const [basisOpen, setBasisOpen] = useState(false);
  const [allocationPct, setAllocationPct] = useState<Record<string, string> | null>(null);
  const [allocationSaving, setAllocationSaving] = useState(false);
  const [allocationError, setAllocationError] = useState<string | null>(null);
  const [primaryBusy, setPrimaryBusy] = useState(false);
  const [primaryError, setPrimaryError] = useState<string | null>(null);

  const strategy = imported ? undefined : c.budget_basis_json.strategy;
  const basis = c.budget_basis_json.basis;
  const step = nextStep(c);
  const pickedRow = scenarioRow(c, picked);

  async function handleGenerate() {
    setGenerating(true);
    setGenerateError(null);
    try {
      onCampaignChange(await generateStrategy(brandId, c.id));
    } catch (err) {
      setGenerateError(errorText(err, "產生策略失敗，請稍後再試。"));
    } finally {
      setGenerating(false);
    }
  }

  async function run(action: () => Promise<void>, fallback: string) {
    setPrimaryBusy(true);
    setPrimaryError(null);
    try {
      await action();
    } catch (err) {
      setPrimaryError(errorText(err, fallback));
    } finally {
      setPrimaryBusy(false);
    }
  }

  const saveBudget = () => run(async () => {
    if (!picked) return;
    onCampaignChange(await selectScenario(brandId, c.id, { scenario_key: picked, custom_total: null }));
    setPicked(null);
  }, "儲存預算失敗，請稍後再試。");

  const adopt = () => run(async () => {
    onCampaignChange(await adoptStrategy(brandId, c.id));
    onChangeTab("structure");
  }, "展開投放結構失敗，請稍後再試。");

  function startAllocationEdit() {
    if (!strategy) return;
    const initial: Record<string, string> = {};
    for (const item of strategy.allocation) initial[item.role] = String(item.pct);
    setAllocationPct(initial);
    setAllocationError(null);
  }

  const allocationSum = allocationPct ? Object.values(allocationPct).reduce((sum, v) => sum + (Number(v) || 0), 0) : 0;

  async function handleAllocationApply() {
    if (!allocationPct) return;
    setAllocationSaving(true);
    setAllocationError(null);
    try {
      const payload = Object.entries(allocationPct).map(([role, pct]) => ({ role, pct: Number(pct) }));
      onCampaignChange(await setAllocation(brandId, c.id, payload));
      setAllocationPct(null);
    } catch (err) {
      setAllocationError(errorText(err, "調整預算分配失敗，請稍後再試。"));
    } finally {
      setAllocationSaving(false);
    }
  }

  // Bottom bar (prototype `setBar` in `tabStrategy()`): an open over-cap sheet blocks saving; an unsaved in-cap pick
  // is saved here; otherwise the workspace's one next step. Adopting needs a cap and a budget the user chose.
  let primary: { label: string; onClick?: () => void; disabled?: boolean } | null = null;
  let hint = "";
  if (pending) {
    primary = { label: "儲存預算", disabled: true };
    hint = "先在上方確認要不要超出預算上限";
  } else if (pickedRow && pickedRow.total !== null) {
    primary = { label: `儲存預算 ${formatAmount(pickedRow.total)}`, onClick: () => void saveBudget() };
  } else if (step.id === "strategy_adopt") {
    const blocker = c.cap.value === null ? "先設上限" : c.budget_planned === null ? "先選一個預算" : "";
    primary = { label: "照這個方式進行 →", onClick: () => void adopt(), disabled: blocker !== "" };
    hint = blocker;
  } else if (step.id !== "strategy_generate") {
    primary = { label: step.label, onClick: () => onChangeTab(step.target) };
  }

  const allocationTotal = pickedRow?.total ?? c.budget_planned;
  const missingHandoff = c.manual_handoff?.groups.filter((group) => group.missing.length > 0) ?? [];
  const beforeAdoption = step.id === "strategy_adopt";

  return (
    <div className="flex flex-col">
      <div className="flex max-w-[1260px] flex-col gap-4">
        <CapBlock brandId={brandId} campaign={c} onCampaignChange={onCampaignChange} />

        {!imported && !strategy && (
          <EmptyState
            title="這個活動還沒有策略建議"
            description={generateError ?? "讓行銷駕駛艙依商品與品牌資料規劃第一版策略。"}
            actionLabel={generating ? "產生中…" : "產生策略"}
            onAction={handleGenerate}
            actionDisabled={generating}
          />
        )}

        {strategy && (
          <>
            <BudgetScenarios
              brandId={brandId}
              campaign={c}
              picked={picked}
              onPick={setPicked}
              pending={pending}
              onPending={setPending}
              onCampaignChange={onCampaignChange}
            />

            <section className="surface px-[22px] py-5" aria-labelledby="allocation-title">
              <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
                <h2 id="allocation-title" className="text-[15px] font-semibold">預算怎麼分</h2>
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-sm text-muted-foreground">{allocationTotal !== null ? `以 ${formatAmount(allocationTotal)} 計` : "選好預算後算金額"}</span>
                  {beforeAdoption && allocationPct === null && (
                    <Button variant="link" size="sm" className="h-auto px-0" onClick={startAllocationEdit}>調整比例</Button>
                  )}
                </div>
              </div>
              {allocationPct === null ? (
                <AllocationBar parts={strategy.allocation.map((item) => ({ key: item.role, label: item.label, pct: item.pct }))} total={allocationTotal} />
              ) : (
                <div className="flex flex-col gap-2">
                  {strategy.allocation.map((item) => (
                    <label key={item.role} className="flex items-center gap-3 text-sm">
                      <span className="w-16">{ROLE_LABEL[item.role]}</span>
                      <Input
                        type="number"
                        className="max-w-24"
                        value={allocationPct[item.role] ?? ""}
                        onChange={(e) => setAllocationPct({ ...allocationPct, [item.role]: e.target.value })}
                      />
                      <span className="text-muted-foreground">%</span>
                    </label>
                  ))}
                  <p className="text-sm">合計 {allocationSum}%{allocationSum !== 100 && <span className="ml-2 text-muted-foreground">三個角色加起來要剛好 100%</span>}</p>
                  {allocationError && <p role="alert" className="text-sm text-danger">{allocationError}</p>}
                  <div className="flex gap-2">
                    <Button size="sm" variant="outline" disabled={allocationSum !== 100 || allocationSaving} onClick={() => void handleAllocationApply()}>
                      {allocationSaving ? "套用中…" : "套用"}
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setAllocationPct(null)} disabled={allocationSaving}>取消</Button>
                  </div>
                </div>
              )}
            </section>
          </>
        )}

        {missingHandoff.length > 0 && (
          <div className="surface flex flex-wrap items-start justify-between gap-3 p-4">
            <div>
              <p className="text-sm font-medium">人工上架設定仍有必填資料待補</p>
              {missingHandoff.map((group) => (
                <p key={group.id} className="text-xs text-muted-foreground">{group.name}：{group.missing.join("、")}</p>
              ))}
            </div>
            <Button variant="outline" onClick={() => onChangeTab("structure")}>前往投放結構補齊</Button>
          </div>
        )}

        {strategy && (
          <Disclosure label="為什麼這樣建議">
            <div className="flex flex-col gap-3 text-sm">
              {strategy.why.length > 0 && <ul className="list-disc space-y-1 pl-5">{strategy.why.map((line, i) => <li key={i}>{line}</li>)}</ul>}
              {(strategy.learning_goals ?? []).length > 0 && (
                <div>
                  <div className="mb-1 font-medium">這輪想學到什麼</div>
                  <ul className="list-disc space-y-1 pl-5">{(strategy.learning_goals ?? []).map((line, i) => <li key={i}>{line}</li>)}</ul>
                </div>
              )}
              {strategy.unknowns.length > 0 && (
                <div>
                  <div className="mb-1 font-medium">目前最大的未知</div>
                  <ul className="list-disc space-y-1 pl-5">{strategy.unknowns.map((line, i) => <li key={i}>{line}</li>)}</ul>
                </div>
              )}
              {strategy.why.length === 0 && strategy.unknowns.length === 0 && (strategy.learning_goals ?? []).length === 0 && (
                <p className="text-muted-foreground">這一輪沒有列出原因</p>
              )}
              {basis && (
                <Button variant="outline" size="sm" className="w-fit" onClick={() => setBasisOpen(true)}>
                  查看策略依據 <ArrowRight size={12} className="ml-1 inline" />
                </Button>
              )}
            </div>
          </Disclosure>
        )}

        <Disclosure label="進階設定">
          {imported ? (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-muted-foreground">{readonlyReason}</p>
              <label htmlFor="campaign-goal" className="text-sm font-medium">內部活動目標</label>
              <Textarea id="campaign-goal" value={goal} onChange={(event) => setGoal(event.target.value)} />
              <p className="text-xs text-muted-foreground">供工作區管理使用，不會更改平台投放目標。</p>
              <Button className="w-fit" disabled={goalSaving || !goal.trim() || goal === c.goal_text} onClick={async () => {
                setGoalSaving(true); setGoalError(null);
                try { onCampaignChange(await patchCampaign(brandId, c.id, { goal_text: goal.trim(), objective: goal.trim() })); }
                catch (error) { setGoalError(errorText(error, "儲存目標失敗。")); }
                finally { setGoalSaving(false); }
              }}>{goalSaving ? "儲存中…" : "儲存目標"}</Button>
              {goalError && <p role="alert" className="text-sm text-danger">{goalError}</p>}
            </div>
          ) : (
            <>
              <p className="mb-2 text-sm text-muted-foreground">人工上架可在投放結構保存受眾、版位、出價、追蹤與平台 ID 對應。</p>
              <Button variant="outline" onClick={() => onChangeTab("structure")}>前往人工上架設定</Button>
            </>
          )}
        </Disclosure>
      </div>

      <ActionBar
        back={<Button variant="ghost" onClick={() => onChangeTab("overview")}>← 總覽</Button>}
        hint={primaryError ?? hint}
      >
        {primary && (
          <Button disabled={primaryBusy || primary.disabled} onClick={primary.onClick}>
            {primaryBusy ? "處理中…" : primary.label}
          </Button>
        )}
      </ActionBar>

      {basisOpen && basis && (
        <SidePanel ariaLabel="策略依據" onClose={() => setBasisOpen(false)}>
          <div className="flex flex-col gap-5">
            <h3 className="text-lg font-semibold">策略依據</h3>
            <section>
              <h4 className="mb-2 text-sm font-medium">品牌事實</h4>
              {basis.brand_facts.length === 0 ? (
                <p className="text-sm text-muted-foreground">沒有用到品牌事實。</p>
              ) : (
                <ul className="space-y-1 text-sm">
                  {basis.brand_facts.map((f) => (
                    <li key={f.id} className="flex justify-between gap-3">
                      <span>{f.label}</span>
                      <span className="text-xs text-muted-foreground">更新於 {f.updated_at}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section>
              <h4 className="mb-2 text-sm font-medium">商品價格</h4>
              {basis.prices.length === 0 ? (
                <p className="text-sm text-muted-foreground">沒有用到商品價格。</p>
              ) : (
                <ul className="space-y-1 text-sm">
                  {basis.prices.map((p) => (
                    <li key={p.product_id} className="flex justify-between gap-3">
                      <span>
                        {p.price !== null ? formatCurrency(p.price) : "尚未設定"}
                        {p.stale && <span className="ml-1 text-warning">價格可能過期</span>}
                      </span>
                      <span className="text-xs text-muted-foreground">{p.effective_from ?? "－"}</span>
                    </li>
                  ))}
                </ul>
              )}
              {basis.assumption_note && <p className="mt-2 text-sm text-warning">{basis.assumption_note}</p>}
            </section>
            <section>
              <h4 className="mb-2 text-sm font-medium">用到的學習</h4>
              {basis.learnings.length === 0 ? (
                <p className="text-sm text-muted-foreground">沒有可用的學習紀錄。</p>
              ) : (
                <ul className="space-y-2 text-sm">
                  {basis.learnings.map((l) => (
                    <li key={l.id}>
                      <p>{l.text}</p>
                      <p className="text-xs text-muted-foreground">{l.level}{l.needs_revalidation ? "・需要重新驗證" : ""}</p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </SidePanel>
      )}
    </div>
  );
}
