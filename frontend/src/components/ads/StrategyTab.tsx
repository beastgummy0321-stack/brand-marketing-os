import { useState } from "react";
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
  type StrategyRole,
  type SuccessMetric,
} from "@/lib/adsApi";
import { Disclosure, JudgmentBand, KpiStrip, ReservedSlotCard, type KpiCell } from "./patterns";

// F04-I15：`OverviewTab.tsx` 有同一份 `WorkspaceTab`／`METRIC_LABEL`／`formatTarget`——兩邊都在
// `do_not_touch`，抽共用要動 `index.ts` 與邊界，貴過幾行重複（ARCHITECTURE.md 決策 11b）。
type WorkspaceTab = "overview" | "strategy" | "structure" | "assets" | "performance";

const METRIC_LABEL: Record<SuccessMetric, string> = {
  cpa: "CPA（每筆訂單成本）",
  roas: "ROAS（廣告投報率）",
  purchases: "購買數",
};

// 通路字典跟 `app/ads/channels.py::CHANNELS` 是同一份中文對照——不寫死平台邏輯，只是把
// key 換成使用者看得懂的字（跟 `DeliveryTab.tsx` 的 `CHANNEL_LABEL` 同一份，一樣的
// do_not_touch 重複理由）。
const PLATFORM_LABEL: Record<string, string> = {
  meta: "Meta",
  google_ads: "Google Ads",
  tiktok: "TikTok",
  shopee: "蝦皮",
  momo: "momo",
};

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
  /** F04-I14：`CampaignWorkspace.tsx` 在 `do_not_touch` 裡，還沒把這個 prop 接給這個分頁——
   * 選填＋早退，等它有票要動再一起補上必填（跟 `adsApi.ts` 的 `judgment?`／`action_lines?`
   * 同一個理由，ARCHITECTURE.md 決策 11）。 */
  onChangeTab?: (tab: WorkspaceTab) => void;
}) {
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

  const strategy = c.budget_basis_json.strategy;
  const scenarios = c.budget_basis_json.scenarios;
  const basis = c.budget_basis_json.basis;

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
  const hasGroups = c.groups.length > 0;
  const days = campaignDays(c.start_date, c.end_date);

  async function handlePrimary() {
    setPrimaryBusy(true);
    setPrimaryError(null);
    try {
      if (hasGroups) {
        onChangeTab?.("structure");
        return;
      }
      let next = c;
      if (next.budget_scenario === null && scenarios) {
        next = await selectScenario(brandId, c.id, { scenario_key: scenarios.recommended, custom_total: null });
        onCampaignChange(next);
      }
      next = await adoptStrategy(brandId, c.id);
      onCampaignChange(next);
      onChangeTab?.("structure");
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

  if (!strategy) {
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

  const platformKey = typeof c.constraints_json.platform === "string" ? c.constraints_json.platform : null;
  const allocationSummary = strategy.allocation.map((item) => `${item.label} ${item.pct}%`).join(" / ");
  const readyCount = c.asset_readiness.total > 0 ? `${c.asset_readiness.ready_count}／${c.asset_readiness.total} 已準備` : "採用策略後才知道";

  const kpiCells: KpiCell[] = [
    {
      icon: Radio,
      label: "平台",
      value: platformKey ? PLATFORM_LABEL[platformKey] ?? platformKey : "尚未指定",
      caption: "採用後會建立對應的投放組",
    },
    {
      icon: Wallet,
      label: "預算",
      value: formatCurrency(total),
      caption: c.budget_planned !== null ? "你採用的情境金額" : "推薦情境（可調整）",
    },
    {
      icon: PieChart,
      label: "配置",
      value: allocationSummary,
      caption: "按角色分配預算",
    },
    {
      icon: Calendar,
      label: "時間",
      value: c.start_date && c.end_date ? `${mmdd(c.start_date)} – ${mmdd(c.end_date)}` : "未設定",
      caption: days !== null ? `共 ${days} 天` : "未設定",
    },
    {
      icon: ImageIcon,
      label: "需要素材",
      value: readyCount,
      caption: "每則廣告需要文案與圖片",
    },
  ];

  const estimatedPurchases =
    c.success_metric === "cpa" && c.success_target !== null && c.success_target > 0 && total !== null
      ? Math.floor(total / c.success_target)
      : null;

  return (
    <div className="flex flex-col gap-4">
      <JudgmentBand
        icon={Sparkles}
        sentence="行銷駕駛艙建議這樣投"
        facts={strategy.why[0] ?? allocationSummary}
      />

      <div className="surface">
        <div className="surface-header">
          <h2>目標：{c.objective}</h2>
          <span className="text-sm text-muted-foreground">
            這是根據你的資料整理的建議，可以直接使用，也可以調整。
          </span>
        </div>
        <div className="surface-body flex flex-col gap-4">
          <KpiStrip cells={kpiCells} />
          <p className="text-sm text-muted-foreground">
            {estimatedPurchases !== null ? (
              <>
                預估購買 {estimatedPurchases} 筆
                <span className="ml-1">推估（CPA 不變的算術）</span>
              </>
            ) : (
              "目標不是 CPA，或還沒有總預算，算不出推估購買。"
            )}
          </p>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div>
              <div className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
                <Lightbulb size={14} /> 主要原因
              </div>
              {strategy.why.length === 0 ? (
                <p className="text-sm text-muted-foreground">這一輪沒有列出</p>
              ) : (
                <ul className="list-disc space-y-1 pl-5 text-sm">
                  {strategy.why.map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <div className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
                <HelpCircle size={14} /> 目前最大的未知
              </div>
              {strategy.unknowns.length === 0 ? (
                <p className="text-sm text-muted-foreground">沒有列出未知</p>
              ) : (
                <ul className="list-disc space-y-1 pl-5 text-sm">
                  {strategy.unknowns.map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <div className="mb-1.5 flex items-center gap-1.5 text-sm font-medium">
                <Target size={14} /> 這輪想學到什麼
              </div>
              {(strategy.learning_goals ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">這一輪沒有設定學習目標</p>
              ) : (
                <ul className="list-disc space-y-1 pl-5 text-sm">
                  {(strategy.learning_goals ?? []).map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <Button className="w-full" variant={hasGroups ? "outline" : "default"} onClick={() => void handlePrimary()} disabled={primaryBusy}>
          {primaryBusy ? "處理中…" : hasGroups ? "前往投放結構" : "照這個方式進行 →"}
        </Button>
        {primaryError && <p className="text-sm text-danger">{primaryError}</p>}
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {hasGroups ? (
        <p className="text-sm text-muted-foreground sm:col-span-3">
          投放結構已經建立，預算改在投放結構分頁的每個投放組日預算。{" "}
          <Button variant="link" className="h-auto p-0" onClick={() => onChangeTab?.("structure")}>
            前往投放結構
          </Button>
        </p>
      ) : (
        <Disclosure label="調整建議">
          <div className="flex flex-col gap-5">
            <div>
              <h3 className="mb-2 text-sm font-medium">預算分配</h3>
              {allocationPct === null ? (
                <Button variant="outline" size="sm" onClick={startAllocationEdit}>
                  調整分配
                </Button>
              ) : (
                <div className="flex flex-col gap-2">
                  {strategy.allocation.map((item) => (
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
                {scenarioError && <p className="mb-2 text-sm text-danger">{scenarioError}</p>}
                <div className="grid grid-cols-3 gap-3">
                  {scenarios.scenarios.map((s) => {
                    const active = selectedKey === s.key;
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
                      </button>
                    );
                  })}
                </div>
                {customOpen ? (
                  <div className="mt-3 flex items-center gap-2">
                    <Input
                      type="number"
                      step={1000}
                      placeholder="輸入自訂預算"
                      value={customValue}
                      onChange={(e) => setCustomValue(e.target.value)}
                      className="max-w-56"
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
                    {METRIC_LABEL[c.success_metric]} 目標 {formatTarget(c.success_metric, c.success_target)}
                  </p>
                  {c.success_basis && <p className="mt-1 text-sm text-muted-foreground">{c.success_basis}</p>}
                </div>
              )}
            </div>
          </div>
        </Disclosure>
      )}

      <Disclosure label="查看完整判斷">
        <div className="flex flex-col gap-2">
          <p className="text-sm text-muted-foreground">品牌事實、商品價格、用到的學習</p>
          <Button variant="outline" size="sm" className="w-fit" onClick={() => setBasisOpen(true)}>
            查看策略依據 <ArrowRight size={12} className="ml-1 inline" />
          </Button>
        </div>
      </Disclosure>

      <Disclosure label="進階設定">
        <ReservedSlotCard
          title="進階投放設定"
          description="這些設定會在自動發布接上之後開放，屆時可以在這裡微調；現在的投放結構仍然可以手動調整。"
          tag="自動發布接上後開放"
          bullets={["平台結構", "受眾設定", "版位設定", "出價策略", "優化事件", "歸因設定", "追蹤設定", "UTM 參數"]}
        />
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
            {(Object.keys(METRIC_LABEL) as SuccessMetric[]).map((key) => (
              <option key={key} value={key}>
                {METRIC_LABEL[key]}
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
