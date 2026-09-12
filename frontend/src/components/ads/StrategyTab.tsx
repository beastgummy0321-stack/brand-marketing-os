import { useState } from "react";
import { ArrowRight, Sparkles } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { Badge } from "@/components/layout/ui/badge";
import { EmptyState } from "@/components/layout/EmptyState";
import { SidePanel } from "@/components/layout/SidePanel";
import { formatCurrency, formatCount, formatRoas } from "@/lib/format";
import {
  generateStrategy,
  patchCampaign,
  selectScenario,
  type CampaignDetail,
  type SuccessMetric,
} from "@/lib/adsApi";

const METRIC_LABEL: Record<SuccessMetric, string> = {
  cpa: "CPA（每筆訂單成本）",
  roas: "ROAS（廣告投報率）",
  purchases: "購買數",
};

function formatTarget(metric: SuccessMetric, value: number): string {
  if (metric === "cpa") return formatCurrency(value);
  if (metric === "roas") return formatRoas(value);
  return formatCount(value);
}

/** 策略 tab（F03-I14）：推薦策略卡＋三情境選擇＋為什麼／哪些是推估＋成功條件卡＋查看策略依據。
 * 金額一律照後端回傳（`budget.split()` 算好的），這裡不重算——只有「哪個情境現在被選中」
 * 這種畫面狀態留在本地。 */
export function StrategyTab({
  brandId,
  campaign: c,
  onCampaignChange,
}: {
  brandId: string;
  campaign: CampaignDetail;
  onCampaignChange: (campaign: CampaignDetail) => void;
}) {
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [scenarioError, setScenarioError] = useState<string | null>(null);
  const [applyingKey, setApplyingKey] = useState<string | null>(null);
  const [customOpen, setCustomOpen] = useState(false);
  const [customValue, setCustomValue] = useState("");
  const [basisOpen, setBasisOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);

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

  const adoptDisabledReason = !strategy
    ? "尚未產生策略，無法採用"
    : "採用流程將在下一步開放";

  return (
    <div className="flex flex-col gap-4">
      {!strategy ? (
        <EmptyState
          title="這個 Campaign 還沒有策略建議"
          description={generateError ?? "讓行銷駕駛艙依商品與品牌資料規劃第一版策略。"}
          actionLabel={generating ? "產生中…" : "產生策略"}
          onAction={handleGenerate}
          actionDisabled={generating}
        />
      ) : (
        <>
          <div className="grid grid-cols-3 gap-4">
            <article className="surface p-5">
              <div className="mb-2 text-xs text-muted-foreground">投放期間</div>
              <p className="text-base font-semibold">
                {c.start_date && c.end_date ? `${c.start_date} ~ ${c.end_date}` : "尚未設定"}
              </p>
            </article>
            <article className="surface p-5">
              <div className="mb-2 text-xs text-muted-foreground">建議總預算</div>
              <p className="metric-number">{formatCurrency(total)}</p>
              {selectedRow && <p className="mt-1 text-xs text-muted-foreground">{selectedRow.caption}</p>}
            </article>
            <article className="surface p-5">
              <div className="mb-2 text-xs text-muted-foreground">投放平台</div>
              <p className="text-base font-semibold">Meta</p>
            </article>
          </div>

          <div className="surface">
            <div className="surface-header">
              <h2 className="flex items-center gap-1.5">
                <Sparkles size={15} /> 行銷駕駛艙推薦策略
              </h2>
              <button
                type="button"
                className="text-sm text-primary hover:underline"
                onClick={() => setBasisOpen(true)}
              >
                查看策略依據 <ArrowRight size={12} className="inline" />
              </button>
            </div>
            <div className="surface-body flex flex-col gap-3">
              {strategy.allocation.map((item) => (
                <div key={item.role} className="flex items-center justify-between gap-3 text-sm">
                  <span>{item.label}</span>
                  <span className="text-muted-foreground">{item.pct}%</span>
                  <span className="numeric font-medium">
                    {item.amount !== null ? formatCurrency(item.amount) : "累積中"}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {scenarios && scenarios.scenarios.length > 0 && (
            <div className="surface">
              <div className="surface-header">
                <h2>預算情境選擇</h2>
                <span className="text-sm text-muted-foreground">依你的目標與資源，選擇最適合的預算規模。</span>
              </div>
              <div className="surface-body flex flex-col gap-3">
                {scenarioError && <p className="text-sm text-danger">{scenarioError}</p>}
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
                  <div className="flex items-center gap-2">
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
                  <button type="button" className="w-fit text-sm text-primary hover:underline" onClick={() => setCustomOpen(true)}>
                    自訂預算
                  </button>
                )}
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div className="surface">
              <div className="surface-header">
                <h2>為什麼</h2>
              </div>
              <div className="surface-body">
                <ul className="list-disc space-y-1.5 pl-5 text-sm">
                  {strategy.why.map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              </div>
            </div>
            <div className="surface">
              <div className="surface-header">
                <h2>哪些是推估</h2>
              </div>
              <div className="surface-body">
                {basis?.estimated_fields.length ? (
                  <ul className="list-disc space-y-1.5 pl-5 text-sm">
                    {basis.estimated_fields.map((field, i) => (
                      <li key={i}>{field}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    {basis ? "這個策略沒有標記推估欄位。" : "資料不完整（缺策略依據），請重新產生策略。"}
                  </p>
                )}
              </div>
            </div>
          </div>

          <div>
            <Button variant="outline" disabled title={adoptDisabledReason}>
              採用策略（建立投放結構）
            </Button>
            <p className="mt-1 text-xs text-muted-foreground">{adoptDisabledReason}</p>
          </div>
        </>
      )}

      <div className="surface">
        <div className="surface-header">
          <h2>成功條件</h2>
          <Button variant="ghost" size="sm" onClick={() => setEditOpen(true)}>
            編輯
          </Button>
        </div>
        <div className="surface-body">
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
