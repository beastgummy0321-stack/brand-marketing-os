import { useEffect, useState } from "react";
import {
  clearCycleOffer,
  fetchNewContext,
  OFFER_TYPE_LABELS,
  saveCycleOffer,
  saveGuidedTargetCpa,
  type Cycle,
  type NewContext,
  type OfferType,
} from "@/lib/warroomApi";
import { createCycle } from "@/lib/warroomApi";
import { formatCurrency } from "@/lib/format";
import { useFormSubmit } from "@/lib/useFormSubmit";
import { AiBadge } from "../shared/AiBadge";
import { Badge } from "../shared/Badge";

const OFFER_TYPE_OPTIONS = Object.entries(OFFER_TYPE_LABELS) as [OfferType, string][];

const OBJECTIVE_TO_FUNNEL: Record<string, "exposure" | "consideration" | "conversion"> = {
  awareness: "exposure",
  traffic: "consideration",
  engagement: "consideration",
  leads: "conversion",
  sales: "conversion",
};

// R3-carry-forward-winners：使用者在 NewCycleDirectionChoice.tsx 按「沿用有效方向」時，
// `initialBackground` 會是這個前綴開頭（跟 app/ads/opening_suggestion.py 的
// CARRY_FORWARD_DIRECTION 逐字同步）——後端只認這個前綴決定要不要把上期贏家／避開清單
// 塞進企劃 prompt。掉進這支表單（建議卡讀取失敗／沒有可主打商品）代表這個前綴會被塞進
// 一個可編輯的 <textarea>，使用者一改就可能連前綴一起洗掉，沿用信號悄悄消失、退回 R3 前
// 的行為（安全失敗，不會反過來汙染「換方向」那支，但也不該讓它默默發生）——把這段固定
// 顯示成不可編輯的一行，textarea 只收額外補充文字，送出時原樣接在後面。
const CARRY_FORWARD_PREFIX = "沿用有效方向：";

/** 開檔（S8.1-11，吸收 `ads_new.html`）：新檔期唯一入口，沒有 `cycle_id` 時顯示。 */
export function IntakeStep({
  brandId,
  initialBackground = "",
  onCreated,
}: {
  brandId: string;
  initialBackground?: string;
  onCreated: (cycleId: string) => void;
}) {
  const [ctx, setCtx] = useState<NewContext | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [simulate, setSimulate] = useState(true);
  const [productIds, setProductIds] = useState<Set<string>>(new Set());
  // S8R.4 修復票：虧損卡預設收合＝AI 建議檔（recommended），不再是滑桿。
  const [tierKey, setTierKey] = useState<"conservative" | "recommended" | "aggressive">("recommended");
  const [tierExpanded, setTierExpanded] = useState(false);
  const [durationDays, setDurationDays] = useState(14);
  const carryForwardPinned = initialBackground.startsWith(CARRY_FORWARD_PREFIX) ? initialBackground : "";
  const [background, setBackground] = useState(carryForwardPinned ? "" : initialBackground);
  const [objective, setObjective] = useState("");
  const [guidedEvents, setGuidedEvents] = useState("");
  const [guidedMargin, setGuidedMargin] = useState("");
  const [guidedResult, setGuidedResult] = useState<number | null>(null);
  // 票 V1-01：這期有沒有優惠，開檔當下就能順便填（3 格：名稱／類型／條件），不勾就是
  // 「這期沒有優惠」，跟今天的行為一樣。
  const [hasOffer, setHasOffer] = useState(false);
  const [offerName, setOfferName] = useState("");
  const [offerType, setOfferType] = useState<OfferType>("discount");
  const [offerTerms, setOfferTerms] = useState("");

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
      background: (carryForwardPinned
        ? carryForwardPinned + (background.trim() ? "\n" + background.trim() : "")
        : background) || null,
      objective,
      offer: hasOffer ? { name: offerName, offer_type: offerType, terms: offerTerms } : undefined,
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

      {ctx.readiness_notes.map((note) => (
        <div key={note.code} className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
          {note.message}{" "}
          <a href={note.action_url} className="font-medium underline underline-offset-4">
            {note.action_label}
          </a>
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
        {carryForwardPinned && (
          <p className="rounded-md border border-primary/40 bg-primary/5 px-3 py-2 text-sm text-foreground">{carryForwardPinned}</p>
        )}
        <textarea
          value={background}
          onChange={(e) => setBackground(e.target.value)}
          rows={3}
          placeholder={carryForwardPinned ? "要再補充的話寫在這裡（不會動到上面沿用的方向）" : undefined}
          className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
        />
      </label>

      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-medium text-foreground">這期有優惠嗎（選填）</legend>
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={hasOffer} onChange={(e) => setHasOffer(e.target.checked)} /> 這期有折扣、組合或贈品
        </label>
        {hasOffer && (
          <div className="flex flex-col gap-2 rounded-md border border-border p-3">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs text-muted-foreground">優惠名稱</span>
              <input
                value={offerName}
                onChange={(e) => setOfferName(e.target.value)}
                maxLength={60}
                placeholder="例如「全館 8 折」"
                className="rounded-md border border-border px-3 py-1.5 text-sm text-foreground"
              />
            </label>
            <fieldset className="flex gap-4">
              {OFFER_TYPE_OPTIONS.map(([value, label]) => (
                <label key={value} className="flex items-center gap-1 text-xs text-foreground">
                  <input type="radio" checked={offerType === value} onChange={() => setOfferType(value)} /> {label}
                </label>
              ))}
            </fieldset>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs text-muted-foreground">使用條件</span>
              <textarea
                value={offerTerms}
                onChange={(e) => setOfferTerms(e.target.value)}
                maxLength={500}
                rows={2}
                placeholder="例如「滿 2000 折 300，不含特價品」"
                className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
              />
            </label>
          </div>
        )}
      </fieldset>

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
 * 顯示送出當下的欄位快照，資料全部沿用 `Cycle` 既有欄位，不另外呼叫 API）。優惠區塊是
 * 例外（票 V1-01）：填／改／清都是這期開檔之後才會做的事，走 PUT／DELETE，`onOfferChanged`
 * 讓外層 `WarroomPage.refresh()` 重新讀一次 `Cycle`（跟 `PlanStep` 等其他區塊同一套
 * 「改完呼叫外層 refresh」慣例，不在這裡自己維護第二份 cycle 狀態）。 */
export function IntakeSummary({ brandId, cycle, onOfferChanged }: { brandId: string; cycle: Cycle; onOfferChanged: () => void }) {
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
      <div>
        <p className="text-xs text-muted-foreground">優惠</p>
        <OfferBlock brandId={brandId} cycle={cycle} onChanged={onOfferChanged} />
      </div>
    </div>
  );
}

/** 這期的優惠（票 V1-01）：沒有 → 空狀態＋「加上這期的優惠」；有 → 顯示內容＋編輯／清除。
 * 編輯共用同一個表單（有優惠時預填現有內容）。後補或編輯不會動已經算好的日預算——這裡
 * 直接把這句話印在表單上，不讓使用者猜（票面決策：PUT／DELETE 都不重算 derived_plan_json）。 */
function OfferBlock({ brandId, cycle, onChanged }: { brandId: string; cycle: Cycle; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(cycle.offer?.name ?? "");
  const [offerType, setOfferType] = useState<OfferType>(cycle.offer?.offer_type ?? "discount");
  const [terms, setTerms] = useState(cycle.offer?.terms ?? "");

  const saveForm = useFormSubmit(async () => {
    await saveCycleOffer(brandId, cycle.id, { name, offer_type: offerType, terms });
    setEditing(false);
    onChanged();
  });
  const clearForm = useFormSubmit(async () => {
    await clearCycleOffer(brandId, cycle.id);
    onChanged();
  });

  function startEdit() {
    setName(cycle.offer?.name ?? "");
    setOfferType(cycle.offer?.offer_type ?? "discount");
    setTerms(cycle.offer?.terms ?? "");
    setEditing(true);
  }

  if (!editing) {
    if (!cycle.offer) {
      return (
        <div className="mt-1 rounded-md border border-dashed border-border p-3 text-sm">
          <p className="text-muted-foreground">這期還沒有設定優惠。</p>
          <button type="button" onClick={startEdit} className="mt-1 text-xs font-medium text-primary hover:underline">
            加上這期的優惠
          </button>
        </div>
      );
    }
    return (
      <div className="mt-1 rounded-md border border-border p-3 text-sm">
        <p className="font-medium text-foreground">
          {cycle.offer.name} <Badge>{cycle.offer.offer_type_label}</Badge>
        </p>
        <p className="mt-1 text-muted-foreground">{cycle.offer.terms}</p>
        <div className="mt-2 flex gap-3">
          <button type="button" onClick={startEdit} className="text-xs font-medium text-primary hover:underline">
            編輯
          </button>
          <button
            type="button"
            disabled={clearForm.saving}
            onClick={() => void clearForm.submit()}
            className="text-xs font-medium text-danger hover:underline disabled:opacity-50"
          >
            {clearForm.saving ? "清除中…" : "清除"}
          </button>
        </div>
        {clearForm.error && <p className="mt-1 text-xs text-danger">{clearForm.error}</p>}
      </div>
    );
  }

  return (
    <form
      className="mt-1 flex flex-col gap-2 rounded-md border border-border p-3 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        void saveForm.submit();
      }}
    >
      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">優惠名稱</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={60}
          placeholder="例如「全館 8 折」"
          className="rounded-md border border-border px-2 py-1 text-sm text-foreground"
        />
      </label>
      <fieldset className="flex gap-4">
        {OFFER_TYPE_OPTIONS.map(([value, label]) => (
          <label key={value} className="flex items-center gap-1 text-xs text-foreground">
            <input type="radio" checked={offerType === value} onChange={() => setOfferType(value)} /> {label}
          </label>
        ))}
      </fieldset>
      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">使用條件</span>
        <textarea
          value={terms}
          onChange={(e) => setTerms(e.target.value)}
          maxLength={500}
          rows={2}
          placeholder="例如「滿 2000 折 300，不含特價品」"
          className="rounded-md border border-border px-2 py-1 text-sm text-foreground"
        />
      </label>
      <p className="text-xs text-muted-foreground">後補或改這裡，不會動已經算好的每日預算。</p>
      {saveForm.error && <p className="text-xs text-danger">{saveForm.error}</p>}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saveForm.saving}
          className="self-start rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saveForm.saving ? "儲存中…" : "儲存優惠"}
        </button>
        <button type="button" onClick={() => setEditing(false)} className="self-start text-xs font-medium text-muted-foreground hover:underline">
          取消
        </button>
      </div>
    </form>
  );
}
