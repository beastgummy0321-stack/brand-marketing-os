import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Calendar, HelpCircle, Image as ImageIcon, Lightbulb, PieChart, Radio, Sparkles, Target, Wallet } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { Badge } from "@/components/layout/ui/badge";
import { EmptyState } from "@/components/layout/EmptyState";
import { SidePanel } from "@/components/layout/SidePanel";
import { formatCurrency, formatCount, formatRoas } from "@/lib/format";
import {
  adoptStrategy,
  generateStrategy,
  patchCampaign,
  selectScenario,
  setAllocation,
  type CampaignDetail,
  type CampaignLabels,
  type StrategyRole,
  type SuccessMetric,
} from "@/lib/adsApi";
import { fetchChannels, type Channel } from "@/lib/adsLaunchApi";
import { Disclosure, JudgmentBand, KpiStrip, type KpiCell } from "./patterns";
import { nextStep, NextStepButton, StepButton, type StepTarget } from "./nextStep";

// F05-I12：後端一律回傳 `campaign.labels`；預設值只在舊測試 fixture 沒帶這個欄位時頂上
// （同 `OverviewTab.tsx`／`PerformanceTab.tsx` 的先例）。
const DEFAULT_LABELS: CampaignLabels = { conversion: "購買", count: "購買數", cpa: "每次購買成本" };

function metricLabel(metric: SuccessMetric, labels: CampaignLabels): string {
  if (metric === "cpa") return `${labels.cpa}（CPA）`;
  if (metric === "purchases") return labels.count;
  return "ROAS（廣告投報率）";
}

const SUCCESS_METRICS: SuccessMetric[] = ["cpa", "roas", "purchases"];

const ROLE_LABEL: Record<StrategyRole, string> = { new: "新客", retarget: "再行銷", explore: "探索" };

function formatTarget(metric: SuccessMetric, value: number): string {
  if (metric === "cpa") return formatCurrency(value);
  if (metric === "roas") return formatRoas(value);
  return formatCount(value);
}

/** ISO 日期（`YYYY-MM-DD`）→ `MM/DD`，只給這個分頁的日期 KPI 格用。 */
function mmdd(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${m}/${d}`;
}

function campaignDays(start: string | null, end: string | null): number | null {
  if (!start || !end) return null;
  const days = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 86_400_000) + 1;
  return days > 0 ? days : null;
}

/** 策略 tab（F04-I14）：一張建議卡＋一顆主要按鈕，其餘全部收在三個 `Disclosure` 裡（R9）。
 * 判斷句、金額、推估購買一律讀後端算好的欄位，這裡不重拼、不重算。 */
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
  const [goal, setGoal] = useState(c.goal_text);
  const [goalSaving, setGoalSaving] = useState(false);
  const [goalError, setGoalError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [scenarioError, setScenarioError] = useState<string | null>(null);
  const [applyingKey, setApplyingKey] = useState<string | null>(null);
  const [customOpen, setCustomOpen] = useState(false);
  const [customValue, setCustomValue] = useState("");
  const [basisOpen, setBasisOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [allocationPct, setAllocationPct] = useState<Record<string, string> | null>(null);
  const [allocationSaving, setAllocationSaving] = useState(false);
  const [allocationError, setAllocationError] = useState<string | null>(null);
  const [primaryBusy, setPrimaryBusy] = useState(false);
  const [primaryError, setPrimaryError] = useState<string | null>(null);
  const [budgetHelpOpen, setBudgetHelpOpen] = useState(false);
  const [channels, setChannels] = useState<Channel[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchChannels(brandId)
      .then((rows) => {
        if (!cancelled) setChannels(rows);
      })
      .catch(() => {
        /* 靜默：讀失敗就顯示 platform key 原樣，不是整頁壞掉 */
      });
    return () => {
      cancelled = true;
    };
  }, [brandId]);

  const strategy = imported ? undefined : c.budget_basis_json.strategy;
  const scenarios = c.budget_basis_json.scenarios;
  const basis = c.budget_basis_json.basis;
  const labels = c.labels ?? DEFAULT_LABELS;
  const amountsUnknown = !!scenarios && scenarios.scenarios.every((s) => s.total === null);

  async function handleGenerate() {
    setGenerating(true);
    setGenerateError(null);
    try {
      onCampaignChange(await generateStrategy(brandId, c.id));
    } catch (err) {
      setGenerateError(err instanceof Error ? err.message : "產生策略失敗，請稍後再試。");
    } finally {
      setGenerating(false);
    }
  }

  async function applyScenario(scenarioKey: string, customTotal?: number) {
    setApplyingKey(scenarioKey);
    setScenarioError(null);
    try {
      onCampaignChange(
        await selectScenario(brandId, c.id, { scenario_key: scenarioKey, custom_total: customTotal ?? null }),
      );
      if (scenarioKey === "custom") setCustomOpen(false);
    } catch (err) {
      setScenarioError(err instanceof Error ? err.message : "選擇預算情境失敗，請稍後再試。");
    } finally {
      setApplyingKey(null);
    }
  }

  const selectedKey = c.budget_scenario ?? scenarios?.recommended ?? null;
  const selectedRow = scenarios?.scenarios.find((s) => s.key === selectedKey);
  const total = c.budget_planned ?? selectedRow?.total ?? null;
  const step = nextStep(c);
  const days = campaignDays(c.start_date, c.end_date);
  const constraintBudget = typeof c.constraints_json.budget === "number" ? c.constraints_json.budget : null;

  async function handlePrimary() {
    if (c.budget_scenario === null && amountsUnknown) {
      setBudgetHelpOpen(true);
      setCustomOpen(true);
      if (!customValue && constraintBudget !== null) setCustomValue(String(constraintBudget));
      return;
    }
    setPrimaryBusy(true);
    setPrimaryError(null);
    try {
      let next = c;
      if (next.budget_scenario === null && scenarios) {
        next = await selectScenario(brandId, c.id, { scenario_key: scenarios.recommended, custom_total: null });
        onCampaignChange(next);
      }
      next = await adoptStrategy(brandId, c.id);
      onCampaignChange(next);
      onChangeTab("structure");
    } catch (err) {
      setPrimaryError(err instanceof Error ? err.message : "展開投放結構失敗，請稍後再試。");
    } finally {
      setPrimaryBusy(false);
    }
  }

  function startAllocationEdit() {
    if (!strategy) return;
    const initial: Record<string, string> = {};
    for (const item of strategy.allocation) initial[item.role] = String(item.pct);
    setAllocationPct(initial);
    setAllocationError(null);
  }

  const allocationSum = allocationPct
    ? Object.values(allocationPct).reduce((sum, v) => sum + (Number(v) || 0), 0)
    : 0;

  async function handleAllocationApply() {
    if (!allocationPct) return;
    setAllocationSaving(true);
    setAllocationError(null);
    try {
      const payload = Object.entries(allocationPct).map(([role, pct]) => ({ role, pct: Number(pct) }));
      onCampaignChange(await setAllocation(brandId, c.id, payload));
      setAllocationPct(null);
    } catch (err) {
      setAllocationError(err instanceof Error ? err.message : "調整預算分配失敗，請稍後再試。");
    } finally {
      setAllocationSaving(false);
    }
  }

  if (!strategy && !imported) {
    return (
      <div className="flex flex-col gap-4">
        <EmptyState
          title="這個 Campaign 還沒有策略建議"
          description={generateError ?? "讓行銷駕駛艙依商品與品牌資料規劃第一版策略。"}
          actionLabel={generating ? "產生中…" : "產生策略"}
          onAction={handleGenerate}
          actionDisabled={generating}
        />
      </div>
    );
  }

  const platformKey = imported ? c.external_view?.entities[0]?.platform ?? null : typeof c.constraints_json.platform === "string" ? c.constraints_json.platform : null;
  const allocationSummary = (strategy?.allocation ?? []).map((item) => `${item.label} ${item.pct}%`).join(" / ");
  const readyCount = c.asset_readiness.total > 0 ? `${c.asset_readiness.ready_count}／${c.asset_readiness.total} 已準備` : "採用策略後才知道";

  const kpiCells: KpiCell[] = [
    {
      icon: Radio,
      label: "平台",
      value: platformKey ? channels.find((ch) => ch.key === platformKey)?.label ?? platformKey : "尚未指定",
      caption: imported ? "平台讀回來源" : "採用後會建立對應的投放組",
    },
    {
      icon: Wallet,
      label: "預算",
      value: imported ? "見投放結構" : total !== null ? formatCurrency(total) : "尚未設定",
      caption: imported ? "平台原始預算" : c.budget_planned !== null ? "你採用的情境金額" : "推薦情境（可調整）",
    },
    {
      icon: PieChart,
      label: "配置",
      value: imported ? "未提供策略配置" : allocationSummary,
      caption: imported ? "保留平台結構" : "按角色分配預算",
    },
    {
      icon: Calendar,
      label: "時間",
      value: imported ? `${c.external_view?.entities.find((row) => row.native_kind === "campaign")?.start_date ?? "開始未知"} – ${c.external_view?.entities.find((row) => row.native_kind === "campaign")?.end_date ?? "結束未知"}` : c.start_date && c.end_date ? `${mmdd(c.start_date)} – ${mmdd(c.end_date)}` : "未設定",
      caption: imported ? "平台讀回日期" : days !== null ? `共 ${days} 天` : "未設定",
    },
    {
      icon: ImageIcon,
      label: "需要素材",
      value: imported ? "前往素材查看" : readyCount,
      caption: "每則廣告需要文案與圖片",
    },
  ];

  const productIds = Array.isArray(c.context_json.product_ids)
    ? c.context_json.product_ids.filter((id): id is string => typeof id === "string")
    : [];
  const productId = productIds[0] ?? null;
  const productEconomicsHref = productId
    ? `/brands/${brandId}/products/${productId}?tab=economics-view`
    : `/brands/${brandId}/products`;
  const missingHandoff = c.manual_handoff?.groups.filter((group) => group.missing.length > 0) ?? [];

  const estimatedPurchases =
    c.success_metric === "cpa" && c.success_target !== null && c.success_target > 0 && total !== null
      ? Math.floor(total / c.success_target)
      : null;

  return (
    <div className="flex flex-col gap-4">
      <JudgmentBand
        icon={Sparkles}
        sentence={imported ? "這個 Campaign 尚無內部策略建議" : "行銷駕駛艙建議這樣投"}
        facts={imported ? readonlyReason : strategy?.why[0] ?? allocationSummary}
      />

      <div className="surface">
        <div className="surface-header">
          <h2>目標：{c.objective}</h2>
          <span className="text-sm text-muted-foreground">
            {imported ? "平台投放目標與內部管理目標分開保留。" : "這是根據你的資料整理的建議，可以直接使用，也可以調整。"}
          </span>
        </div>
        <div className="surface-body flex flex-col gap-4">
          <KpiStrip cells={kpiCells} />
          <p className="text-sm text-muted-foreground">
            {imported ? "平台資料未包含原始策略建議，不推估配置與購買數。" : estimatedPurchases !== null ? (
              <>
                預估{labels.conversion} {estimatedPurchases} 筆
                <span className="ml-1">推估（CPA 不變的算術）</span>
              </>
            ) : (
              "目標不是 CPA，或還沒有總預算，算不出推估購買。"
            )}
          </p>
          <div>
              <div className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
                <HelpCircle size={14} /> 目前最大的未知
              </div>
              {(strategy?.unknowns ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">{imported ? "原始策略與配置未提供。" : "沒有列出未知"}</p>
              ) : (
                <ul className="list-disc space-y-1 pl-5 text-sm">
                  {(strategy?.unknowns ?? []).map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              )}
          </div>
        </div>
      </div>

      {missingHandoff.length > 0 && <div className="surface p-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium">人工上架設定仍有必填資料待補</p>
          {missingHandoff.map((group) => <p key={group.id} className="text-xs text-muted-foreground">
            {group.name}：{group.missing.join("、")}
          </p>)}
        </div>
        <Button variant="outline" onClick={() => onChangeTab("structure")}>前往投放結構補齊</Button>
      </div>}

      <div className="flex flex-col gap-1.5">
        {step.id === "strategy_adopt" ? (
          <StepButton onClick={() => void handlePrimary()} disabled={primaryBusy}>
            {primaryBusy
              ? "處理中…"
              : c.budget_scenario === null && amountsUnknown
                ? "先設定預算 →"
                : "照這個方式進行 →"}
          </StepButton>
        ) : (
          <NextStepButton step={step} onChangeTab={onChangeTab} />
        )}
        {primaryError && <p className="text-sm text-danger">{primaryError}</p>}
      </div>

      <div className="grid grid-cols-1 items-start gap-3 xl:grid-cols-3">
      {imported ? <Disclosure label="調整建議"><p className="text-sm text-muted-foreground">{readonlyReason}</p><Button className="mt-3" disabled>產生策略</Button></Disclosure> : step.id !== "strategy_adopt" ? (
        <p className="text-sm text-muted-foreground xl:col-span-3">
          投放結構已經建立，預算改在投放結構分頁的每個投放組日預算。
        </p>
      ) : (
        // `Disclosure` 是 uncontrolled（只有 `defaultOpen`），用 `key` remount 展開它，
        // 不改 `patterns/Disclosure`（do_not_touch）——換 key 整塊會重新掛載，
        // 所以不把任何狀態搬進這個子樹（ponytail: allocationPct／customOpen／customValue
        // 仍在 StrategyTab 自己身上才成立）。
        <Disclosure key={budgetHelpOpen ? "open" : "closed"} label="調整建議" defaultOpen={budgetHelpOpen}>
          <div className="flex flex-col gap-5">
            <div>
              <h3 className="mb-2 text-sm font-medium">預算分配</h3>
              {allocationPct === null ? (
                <Button variant="outline" size="sm" onClick={startAllocationEdit}>
                  調整分配
                </Button>
              ) : (
                <div className="flex flex-col gap-2">
                  {(strategy?.allocation ?? []).map((item) => (
                    <div key={item.role} className="flex items-center gap-3 text-sm">
                      <span className="w-16">{ROLE_LABEL[item.role]}</span>
                      <Input
                        type="number"
                        className="max-w-24"
                        value={allocationPct[item.role] ?? ""}
                        onChange={(e) => setAllocationPct({ ...allocationPct, [item.role]: e.target.value })}
                      />
                      <span className="text-muted-foreground">%</span>
                    </div>
                  ))}
                  <p className="text-sm">合計 {allocationSum}%</p>
                  {allocationSum !== 100 && (
                    <p className="text-sm text-muted-foreground">三個角色加起來要剛好 100%</p>
                  )}
                  {allocationError && <p className="text-sm text-danger">{allocationError}</p>}
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      disabled={allocationSum !== 100 || allocationSaving}
                      onClick={() => void handleAllocationApply()}
                    >
                      {allocationSaving ? "套用中…" : "套用"}
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setAllocationPct(null)} disabled={allocationSaving}>
                      取消
                    </Button>
                  </div>
                </div>
              )}
            </div>

            {scenarios && scenarios.scenarios.length > 0 && (
              <div>
                <h3 className="mb-2 text-sm font-medium">預算情境選擇</h3>
                <p className="mb-2 text-sm text-muted-foreground">依你的目標與資源，選擇最適合的預算規模。</p>
                <p className="mb-2 text-sm text-muted-foreground">
                  {scenarios.mode === "cold_start"
                    ? `計算依據：目前 CPA ${c.success_metric === "cpa" && c.success_target !== null && c.success_target > 0 ? formatCurrency(c.success_target) : "未設定"} × 每天 2／5／10 筆 × ${days ?? "未設定"} 天。`
                    : `計算依據：各情境所列歷史日預算 × ${days ?? "未設定"} 天。`}
                  {constraintBudget !== null && ` 預算上限 ${formatCurrency(constraintBudget)}。`}
                </p>
                {c.budget_planned !== null && (
                  <p className="mb-2 text-sm">已選預算 {formatCurrency(c.budget_planned)}；更新目標不會自動改動。</p>
                )}
                {scenarioError && <p className="mb-2 text-sm text-danger">{scenarioError}</p>}
                <div className="grid grid-cols-3 gap-3">
                  {scenarios.scenarios.map((s) => {
                    const active = selectedKey === s.key && (c.budget_planned === null || c.budget_planned === s.total);
                    return (
                      <button
                        type="button"
                        key={s.key}
                        onClick={() => void applyScenario(s.key)}
                        disabled={applyingKey !== null || s.total === null}
                        className={`rounded-lg border p-3 text-left ${
                          active ? "border-primary ring-1 ring-primary" : "border-border"
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-medium">{s.label}</span>
                          {s.key === scenarios.recommended && <Badge variant="secondary">推薦</Badge>}
                        </div>
                        <div className="numeric my-1.5 text-base font-semibold">{formatCurrency(s.total)}</div>
                        <div className="text-xs text-muted-foreground">{s.caption}</div>
                        {constraintBudget !== null && s.total !== null && s.total > constraintBudget && (
                          <p className="mt-1 text-xs text-warning">超過預算上限 {formatCurrency(constraintBudget)}</p>
                        )}
                      </button>
                    );
                  })}
                </div>
                {amountsUnknown && (
                  <p className="mt-3 text-sm text-muted-foreground">
                    要估金額需要有效的 CPA 成功條件與活動期間。商品數字可作為設定依據。{" "}
                    <Link to={productEconomicsHref} className="text-primary hover:underline">
                      去補商品數字
                    </Link>
                  </p>
                )}
                {customOpen ? (
                  <div className="mt-3 flex items-center gap-2">
                    <Input
                      type="number"
                      step={1000}
                      placeholder="輸入自訂預算"
                      value={customValue}
                      onChange={(e) => setCustomValue(e.target.value)}
                      className="max-w-56"
                      autoFocus
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={applyingKey !== null || !customValue}
                      onClick={() => void applyScenario("custom", Number(customValue))}
                    >
                      套用
                    </Button>
                  </div>
                ) : (
                  <button
                    type="button"
                    className="mt-2 w-fit text-sm text-primary hover:underline"
                    onClick={() => setCustomOpen(true)}
                  >
                    自訂預算
                  </button>
                )}
              </div>
            )}

            <div>
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-sm font-medium">成功條件</h3>
                <Button variant="ghost" size="sm" onClick={() => setEditOpen(true)}>
                  編輯
                </Button>
              </div>
              {c.success_target === null ? (
                <div>
                  <p className="text-sm font-medium">尚未設定成功條件</p>
                  <p className="mt-1 text-sm text-muted-foreground">{c.success_basis ?? "AI 沒有足夠依據推出一個數字。"}</p>
                </div>
              ) : (
                <div>
                  <p className="text-base font-semibold">
                    {metricLabel(c.success_metric, labels)} 目標 {formatTarget(c.success_metric, c.success_target)}
                  </p>
                  {c.success_basis && <p className="mt-1 text-sm text-muted-foreground">{c.success_basis}</p>}
                </div>
              )}
            </div>
          </div>
        </Disclosure>
      )}

      <Disclosure label="查看完整判斷">
        <div className="flex flex-col gap-4">
          <div>
            <div className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
              <Lightbulb size={14} /> 主要原因
            </div>
            {(strategy?.why ?? []).length === 0 ? <p className="text-sm text-muted-foreground">這一輪沒有列出</p> : (
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {(strategy?.why ?? []).map((line, i) => <li key={i}>{line}</li>)}
              </ul>
            )}
          </div>
          <div>
            <div className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
              <Target size={14} /> 這輪想學到什麼
            </div>
            {(strategy?.learning_goals ?? []).length === 0 ? (
              <p className="text-sm text-muted-foreground">這一輪沒有設定學習目標</p>
            ) : (
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {(strategy?.learning_goals ?? []).map((line, i) => <li key={i}>{line}</li>)}
              </ul>
            )}
          </div>
          <p className="text-sm text-muted-foreground">品牌事實、商品價格、用到的學習</p>
          <Button variant="outline" size="sm" className="w-fit" onClick={() => setBasisOpen(true)}>
            查看策略依據 <ArrowRight size={12} className="ml-1 inline" />
          </Button>
        </div>
      </Disclosure>

      <Disclosure label="進階設定">
        {imported ? <div className="flex flex-col gap-3">
          <label htmlFor="campaign-goal" className="text-sm font-medium">內部活動目標</label>
          <Textarea id="campaign-goal" value={goal} onChange={(event) => setGoal(event.target.value)} />
          <p className="text-xs text-muted-foreground">供工作區管理使用，不會更改平台投放目標。</p>
          <Button disabled={goalSaving || !goal.trim() || goal === c.goal_text} onClick={async () => {
            setGoalSaving(true); setGoalError(null);
            try { onCampaignChange(await patchCampaign(brandId, c.id, { goal_text: goal.trim(), objective: goal.trim() })); }
            catch (error) { setGoalError(error instanceof Error ? error.message : "儲存目標失敗。"); }
            finally { setGoalSaving(false); }
          }}>{goalSaving ? "儲存中…" : "儲存目標"}</Button>
          {goalError && <p role="alert" className="text-sm text-danger">{goalError}</p>}
          <p className="text-sm">成功條件：{c.success_target === null ? "尚未設定" : `${metricLabel(c.success_metric, labels)} ${formatTarget(c.success_metric, c.success_target)}`}</p>
          <Button variant="outline" onClick={() => setEditOpen(true)}>編輯成功條件</Button>
        </div> : <>
          <p className="mb-2 text-sm text-muted-foreground">人工上架可在投放結構保存受眾、版位、出價、追蹤與平台 ID 對應。</p>
          <Button variant="outline" onClick={() => onChangeTab("structure")}>前往人工上架設定</Button>
        </>}
      </Disclosure>
      </div>

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
              {basis.assumption_note && (
                <p className="mt-2 text-sm text-warning">{basis.assumption_note}</p>
              )}
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
                      <p className="text-xs text-muted-foreground">
                        {l.level}
                        {l.needs_revalidation ? "・需要重新驗證" : ""}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </SidePanel>
      )}

      {editOpen && (
        <SuccessCriterionEditor
          brandId={brandId}
          campaign={c}
          onClose={() => setEditOpen(false)}
          onSaved={(updated) => {
            onCampaignChange(updated);
            setEditOpen(false);
          }}
        />
      )}
    </div>
  );
}

function SuccessCriterionEditor({
  brandId,
  campaign: c,
  onClose,
  onSaved,
}: {
  brandId: string;
  campaign: CampaignDetail;
  onClose: () => void;
  onSaved: (campaign: CampaignDetail) => void;
}) {
  const labels = c.labels ?? DEFAULT_LABELS;
  const [metric, setMetric] = useState<SuccessMetric>(c.success_metric);
  const [target, setTarget] = useState(c.success_target === null ? "" : String(c.success_target));
  const [basisText, setBasisText] = useState(c.success_basis ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const updated = await patchCampaign(brandId, c.id, {
        success_metric: metric,
        success_target: target === "" ? null : Number(target),
        success_basis: basisText === "" ? null : basisText,
      });
      onSaved(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新成功條件失敗，請稍後再試。");
    } finally {
      setSaving(false);
    }
  }

  return (
    <SidePanel ariaLabel="編輯成功條件" onClose={onClose}>
      <div className="flex flex-col gap-4">
        <h3 className="text-lg font-semibold">編輯成功條件</h3>
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium" htmlFor="success-metric">
            指標
          </label>
          <select
            id="success-metric"
            className="h-9 rounded-md border border-input bg-transparent px-3 text-sm"
            value={metric}
            onChange={(e) => setMetric(e.target.value as SuccessMetric)}
          >
            {SUCCESS_METRICS.map((key) => (
              <option key={key} value={key}>
                {metricLabel(key, labels)}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium" htmlFor="success-target">
            目標值（留空＝尚未設定）
          </label>
          <Input id="success-target" type="number" value={target} onChange={(e) => setTarget(e.target.value)} />
        </div>
        <div className="flex flex-col gap-1.5">
          <label className="text-sm font-medium" htmlFor="success-basis">
            依據
          </label>
          <Textarea id="success-basis" value={basisText} onChange={(e) => setBasisText(e.target.value)} rows={3} />
        </div>
        {error && <p className="text-sm text-danger">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={saving}>
            取消
          </Button>
          <Button onClick={() => void handleSave()} disabled={saving}>
            {saving ? "儲存中…" : "儲存"}
          </Button>
        </div>
      </div>
    </SidePanel>
  );
}
