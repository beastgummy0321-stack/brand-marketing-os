import { useEffect, useState } from "react";
import { fetchNewContext, saveGuidedTargetCpa, type Cycle, type NewContext } from "@/lib/warroomApi";
import { createCycle } from "@/lib/warroomApi";
import { formatCurrency } from "@/lib/format";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { AiBadge } from "../shared/AiBadge";
import { Badge } from "../shared/Badge";

const OBJECTIVE_TO_FUNNEL: Record<string, "exposure" | "consideration" | "conversion"> = {
  awareness: "exposure",
  traffic: "consideration",
  engagement: "consideration",
  leads: "conversion",
  sales: "conversion",
};

/** 開檔（S8.1-11，吸收 `ads_new.html`）：新檔期唯一入口，沒有 `cycle_id` 時顯示。 */
export function IntakeStep({ brandId, onCreated }: { brandId: string; onCreated: (cycleId: string) => void }) {
  const [ctx, setCtx] = useState<NewContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [simulate, setSimulate] = useState(true);
  const [productIds, setProductIds] = useState<Set<string>>(new Set());
  // S8R.4 修復票：虧損卡預設收合＝AI 建議檔（recommended），不再是滑桿。
  const [tierKey, setTierKey] = useState<"conservative" | "recommended" | "aggressive">("recommended");
  const [tierExpanded, setTierExpanded] = useState(false);
  const [durationDays, setDurationDays] = useState(14);
  const [background, setBackground] = useState("");
  const [objective, setObjective] = useState("");
  const [guidedEvents, setGuidedEvents] = useState("");
  const [guidedMargin, setGuidedMargin] = useState("");
  const [guidedResult, setGuidedResult] = useState<number | null>(null);

  useEffect(() => {
    fetchNewContext(brandId)
      .then((data) => {
        setCtx(data);
        setProductIds(new Set(data.products.map((p) => p.id)));
        setObjective(data.recommended_objective);
        setDurationDays(data.duration_suggestion.value);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "讀取失敗，請稍後再試。"));
  }, [brandId]);

  const form = useFormSubmit(async () => {
    const selectedTier = ctx?.budget_tiers.find((t) => t.key === tierKey);
    const res = await createCycle(brandId, {
      simulate: ctx?.offer_simulation ? simulate : false,
      product_ids: [...productIds],
      budget: selectedTier?.amount ?? 0,
      duration_days: durationDays,
      background: background || null,
      objective,
    });
    onCreated(res.cycle_id);
  });

  const guidedForm = useFormSubmit(async () => {
    const res = await saveGuidedTargetCpa(brandId, { events_per_sale: Number(guidedEvents) || 1, margin_per_sale: Number(guidedMargin) || 0 });
    setGuidedResult(res.value);
  });

  if (error) return <div className="rounded-lg border border-border bg-card p-6 text-sm text-danger">{error}</div>;
  if (!ctx) return <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">讀取中…</div>;

  const funnelStage = objective ? OBJECTIVE_TO_FUNNEL[objective] : null;
  const selectedTier = ctx.budget_tiers.find((t) => t.key === tierKey) ?? ctx.budget_tiers[0];

  return (
    <form
      className="flex flex-col gap-6 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]"
      onSubmit={(e) => {
        e.preventDefault();
        void form.submit();
      }}
    >
      <div>
        <h2 className="font-display text-lg text-foreground">開一期新檔期</h2>
        <p className="mt-1 text-sm text-muted-foreground">系統會讀取品牌智庫的資料，準備好計畫、素材與投放設定，貼到 Meta 即可。</p>
      </div>

      {ctx.readiness_notes.map((note, i) => (
        <div key={i} className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
          {note}
        </div>
      ))}

      {ctx.offer_simulation && (
        <fieldset className="flex flex-col gap-2">
          <legend className="text-sm font-medium text-foreground">這個品牌還沒跑過廣告，要先跑一次模擬嗎？</legend>
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input type="radio" checked={simulate} onChange={() => setSimulate(true)} /> 先跑一次模擬（推薦）
          </label>
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input type="radio" checked={!simulate} onChange={() => setSimulate(false)} /> 我不用，直接開真的
          </label>
        </fieldset>
      )}

      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-medium text-foreground">這期要推廣哪些產品</legend>
        {ctx.products.length === 0 ? (
          <p className="text-sm text-muted-foreground">這個品牌目前沒有產品，這期以整個品牌為範圍。</p>
        ) : (
          ctx.products.map((p) => (
            <label key={p.id} className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={productIds.has(p.id)}
                onChange={() =>
                  setProductIds((prev) => {
                    const next = new Set(prev);
                    if (next.has(p.id)) next.delete(p.id);
                    else next.add(p.id);
                    return next;
                  })
                }
              />
              {p.name}
            </label>
          ))
        )}
      </fieldset>

      {/* S8R.4 修復票：拉桿廢除。收合態＝AI 建議上限大字＋理由，零操作；「自己調」才展開三檔預算卡。 */}
      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-medium text-foreground">你能承受的最大虧損金額</legend>
        <div className="rounded-md border border-border bg-muted/30 p-3">
          <p className="font-display text-2xl text-foreground">NT$ {selectedTier.amount_label}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            約 {selectedTier.duration_days} 天、日預算約 NT$ {selectedTier.daily_budget_label}
          </p>
          {tierKey === "recommended" ? (
            <AiBadge isAiSuggested={ctx.pain_suggestion.is_ai_suggested} reason={ctx.pain_suggestion.basis_label} />
          ) : (
            <p className="mt-1 text-xs text-muted-foreground">已自己調整為「{selectedTier.label}」檔。</p>
          )}
        </div>
        <button type="button" onClick={() => setTierExpanded((v) => !v)} className="self-start text-xs font-medium text-primary hover:underline">
          {tierExpanded ? "收合" : "自己調"}
        </button>
        {tierExpanded && (
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {ctx.budget_tiers.map((tier) => (
              <button
                key={tier.key}
                type="button"
                onClick={() => setTierKey(tier.key)}
                className={`rounded-md border p-3 text-left text-sm ${tier.key === tierKey ? "border-primary bg-primary/5" : "border-border"}`}
              >
                <p className="font-medium text-foreground">
                  {tier.label}
                  {tier.key === "recommended" && (
                    <span className="ml-2">
                      <Badge tone="success">AI 建議</Badge>
                    </span>
                  )}
                </p>
                <p className="mt-1 text-foreground">NT$ {tier.amount_label}</p>
                <p className="mt-1 text-xs text-muted-foreground">約 {tier.duration_days} 天、日預算約 NT$ {tier.daily_budget_label}</p>
                <p className="mt-1 text-xs text-muted-foreground">{tier.note}</p>
              </button>
            ))}
          </div>
        )}
      </fieldset>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-foreground">檔期長度（天）</span>
        <input
          type="number"
          min={ctx.duration_config.min}
          max={ctx.duration_config.max}
          value={durationDays}
          onChange={(e) => setDurationDays(Number(e.target.value))}
          className="w-24 rounded-md border border-border px-3 py-1.5 text-sm text-foreground"
        />
        <AiBadge reason={ctx.duration_suggestion.basis_label} />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-foreground">這期背景（選填）</span>
        <textarea value={background} onChange={(e) => setBackground(e.target.value)} rows={3} className="rounded-md border border-border px-3 py-2 text-sm text-foreground" />
      </label>

      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-medium text-foreground">本期目標</legend>
        {ctx.objectives.map((o) => (
          <label key={o.value} className="flex items-start gap-2 text-sm text-foreground">
            <input type="radio" checked={objective === o.value} onChange={() => setObjective(o.value)} className="mt-0.5" />
            <span className="flex-1">
              {o.label}
              {o.value === ctx.recommended_objective ? <AiBadge reason={o.hint} /> : <span className="block text-xs text-muted-foreground">{o.hint}</span>}
            </span>
          </label>
        ))}
        <p className="text-xs text-muted-foreground">Meta 另有「應用程式推廣」，本系統不涉 App 故未列入。</p>
      </fieldset>

      {funnelStage === "conversion" ? (
        <div className="rounded-md border border-border p-3 text-sm">
          <p className="font-medium text-foreground">
            KPI 對齊漏斗：<Badge>轉換層</Badge>
          </p>
          <p className="mt-1 text-muted-foreground">目標 CPA 尚無依據時，可以先推算一個參考值：</p>
          <div className="mt-2 flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              平均幾個轉換事件成交一單
              <input type="text" inputMode="decimal" value={guidedEvents} onChange={(e) => setGuidedEvents(e.target.value)} className="w-24 rounded-md border border-border px-2 py-1 text-sm text-foreground" />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              毛利
              <input type="text" inputMode="decimal" value={guidedMargin} onChange={(e) => setGuidedMargin(e.target.value)} className="w-24 rounded-md border border-border px-2 py-1 text-sm text-foreground" />
            </label>
            <button
              type="button"
              disabled={guidedForm.saving}
              onClick={() => void guidedForm.submit()}
              className="rounded-md border border-primary px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10"
            >
              {guidedForm.saving ? "計算中…" : "存這個推算值"}
            </button>
          </div>
          {guidedResult !== null && <p className="mt-1 text-xs text-success">推算目標 CPA 約 NT$ {guidedResult}</p>}
        </div>
      ) : funnelStage ? (
        <div className="rounded-md border border-border p-3 text-sm text-muted-foreground">
          KPI 對齊漏斗：<Badge>{funnelStage === "exposure" ? "曝光層" : "考慮層"}</Badge> 這個目標不算目標 CPA，改看建議花費區間，避免做白工計算。
        </div>
      ) : null}

      {form.error && <p className="text-sm text-danger">{form.error}</p>}
      <button
        type="submit"
        disabled={form.saving || !objective}
        className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {form.saving ? "送出中…" : "下一步：看這期的計畫"}
      </button>
    </form>
  );
}

/** 開檔區塊收合後再點開的唯讀回顧（R1-2 五區自適應單頁：這期已經開檔，不重新跑一次表單，
 * 顯示送出當下的欄位快照，資料全部沿用 `Cycle` 既有欄位，不另外呼叫 API）。 */
export function IntakeSummary({ cycle }: { cycle: Cycle }) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
      <div>
        <h2 className="font-display text-lg text-foreground">這期的開檔設定</h2>
        <p className="mt-1 text-sm text-muted-foreground">已經送出，這裡是唯讀回顧。</p>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-muted-foreground">預算</dt>
          <dd className="text-foreground">{formatCurrency(cycle.budget)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">檔期天數</dt>
          <dd className="text-foreground">{cycle.duration_days} 天</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">日預算</dt>
          <dd className="text-foreground">{formatCurrency(cycle.daily_budget)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">起訖</dt>
          <dd className="text-foreground">{cycle.start_date} ～ {cycle.end_date}</dd>
        </div>
      </dl>
      {cycle.background && <p className="text-sm text-muted-foreground">背景：{cycle.background}</p>}
    </div>
  );
}
