import { useEffect, useState } from "react";
import { createCycle, fetchNewContext, OFFER_TYPE_LABELS, type NewContext, type OfferType } from "@/lib/warroomApi";
import {
  answerOpeningChannel,
  fetchOpeningSuggestion,
  updateChannelPlan,
  type OpeningSuggestionResponse,
} from "@/lib/proposalApi";
import { Skeleton } from "@/components/layout/Skeleton";
import { IntakeStep } from "@/components/warroom/steps/IntakeStep";

type LoadState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; opening: OpeningSuggestionResponse; context: NewContext };

const CHANNEL_OPTIONS = [
  { channel: "social", label: "Meta" },
  { channel: "google_search", label: "Google 搜尋" },
  { channel: "line_email", label: "LINE／電子報" },
  { channel: "kol_media", label: "合作媒體" },
  { channel: "website_landing", label: "官網購買頁" },
];

// 票 V1-01：跟 IntakeStep.tsx 同一份選項，字面重複而非抽共用（容器契約第 5 條：
// 兩個呼叫端各自留一份，第三個真的出現才抽）。
const OFFER_TYPE_OPTIONS = Object.entries(OFFER_TYPE_LABELS) as [OfferType, string][];

/**
 * 開檔建議卡（F1 畫面 1）。只有這個元件讀取／回答 opening-suggestion；建立檔期仍走既有
 * `createCycle`，所以建立後的狀態只由後端保存；有關掉的管道會在建立後立即寫回 channel-plan。
 */
export function OpeningSuggestionCard({ brandId, initialBackground, onCreated, fromCycle }: { brandId: string; initialBackground: string; onCreated: (cycleId: string) => void; fromCycle?: string | null }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [adjusting, setAdjusting] = useState(false);
  const [answering, setAnswering] = useState(false);
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [productId, setProductId] = useState("");
  const [budget, setBudget] = useState(0);
  const [durationDays, setDurationDays] = useState(14);
  const [enabledChannels, setEnabledChannels] = useState<Record<string, boolean>>(
    () => Object.fromEntries(CHANNEL_OPTIONS.map(({ channel }) => [channel, true])),
  );
  const [pendingCycleId, setPendingCycleId] = useState<string | null>(null);
  // 票 V1-01：只有「我要調整」面板才問優惠——「就這樣做」一路預設 hasOffer=false，
  // offer 鍵整個省略，維持原本一鍵到底的行為（票面決策 3）。
  const [hasOffer, setHasOffer] = useState(false);
  const [offerName, setOfferName] = useState("");
  const [offerType, setOfferType] = useState<OfferType>("discount");
  const [offerTerms, setOfferTerms] = useState("");

  function load() {
    setState({ status: "loading" });
    Promise.all([fetchOpeningSuggestion(brandId, fromCycle), fetchNewContext(brandId)])
      .then(([opening, context]) => {
        setState({ status: "ready", opening, context });
        if (opening.available) {
          setProductId(opening.suggestion.product_id);
          setBudget(opening.suggestion.budget);
          setDurationDays(opening.suggestion.duration_days);
        }
      })
      .catch(() => setState({ status: "error" }));
  }

  useEffect(load, [brandId, fromCycle]);

  async function answerChannel(answer: string) {
    setAnswering(true);
    setActionError(null);
    try {
      await answerOpeningChannel(brandId, answer, fromCycle);
      load();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "送出失敗，請稍後再試。");
    } finally {
      setAnswering(false);
    }
  }

  async function createFromSuggestion() {
    if (state.status !== "ready" || !state.opening.available) return;
    setSaving(true);
    setActionError(null);
    try {
      let cycleId = pendingCycleId;
      if (!cycleId) {
        cycleId = (await createCycle(brandId, {
          simulate: state.context.offer_simulation,
          product_ids: [productId],
          budget,
          duration_days: durationDays,
          background: initialBackground || null,
          objective: state.context.recommended_objective,
          offer: hasOffer ? { name: offerName, offer_type: offerType, terms: offerTerms } : undefined,
        })).cycle_id;
        setPendingCycleId(cycleId);
      }
      const channels = CHANNEL_OPTIONS.map(({ channel }) => ({ channel, enabled: enabledChannels[channel] }));
      if (channels.some(({ enabled }) => !enabled)) {
        await updateChannelPlan(brandId, cycleId, channels);
      }
      onCreated(cycleId);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "建立失敗，請稍後再試。");
    } finally {
      setSaving(false);
    }
  }

  if (state.status === "loading") {
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
        <Skeleton className="h-6 w-36" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-10 w-52" />
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex flex-col gap-4">
        <div className="rounded-lg border border-warning/40 bg-warning/10 p-4 text-sm text-warning">
          建議產生失敗；可以直接手動開檔，不擋路。
        </div>
        <IntakeStep brandId={brandId} initialBackground={initialBackground} onCreated={onCreated} />
      </div>
    );
  }

  if (!state.opening.available) {
    if (!state.opening.channel_ask) {
      return (
        <div className="flex flex-col gap-4">
          <div className="rounded-lg border border-warning/40 bg-warning/10 p-4 text-sm text-warning">
            {state.opening.reason}
          </div>
          <IntakeStep brandId={brandId} initialBackground={initialBackground} onCreated={onCreated} />
        </div>
      );
    }
    return (
      <section className="rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
        <h2 className="font-display text-lg text-foreground">先問一題</h2>
        <p className="mt-2 text-sm text-muted-foreground">{state.opening.reason}</p>
        <p className="mt-2 text-sm text-foreground">{state.opening.channel_ask.question}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          {state.opening.channel_ask.options.map((option) => (
            <button
              key={option}
              type="button"
              disabled={answering}
              onClick={() => void answerChannel(option)}
              className="rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              {answering ? "送出中…" : option}
            </button>
          ))}
        </div>
        {actionError && <p className="mt-3 text-sm text-danger">{actionError}</p>}
      </section>
    );
  }

  const { suggestion, summary } = state.opening;
  return (
    <section className="flex flex-col gap-4 rounded-lg border border-border bg-card p-6 shadow-[var(--shadow-card)]">
      <div>
        <h2 className="font-display text-lg text-foreground">這期的打法</h2>
        <p className="mt-2 text-sm leading-6 text-foreground">{summary}</p>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
        <div><dt className="text-xs text-muted-foreground">平台</dt><dd className="text-foreground">{suggestion.platform}</dd></div>
        <div><dt className="text-xs text-muted-foreground">主打商品</dt><dd className="text-foreground">{suggestion.product_name}</dd></div>
        <div><dt className="text-xs text-muted-foreground">預算</dt><dd className="text-foreground">NT$ {budget}</dd></div>
        <div><dt className="text-xs text-muted-foreground">天數</dt><dd className="text-foreground">{durationDays} 天</dd></div>
      </dl>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={saving}
          onClick={() => void createFromSuggestion()}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? "送出中…" : adjusting ? "確定調整" : "就這樣做"}
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => setAdjusting((value) => !value)}
          className="rounded-md border border-border px-4 py-2 text-sm font-medium text-foreground hover:border-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          我要調整
        </button>
      </div>
      {adjusting && (
        <div className="grid gap-4 rounded-md border border-border bg-muted/30 p-4 text-sm">
          <fieldset className="flex flex-col gap-2">
            <legend className="font-medium text-foreground">主打商品</legend>
            {state.context.products.map((product) => (
              <label key={product.id} className="flex items-center gap-2 text-foreground">
                <input type="radio" checked={productId === product.id} onChange={() => setProductId(product.id)} />
                {product.name}
              </label>
            ))}
          </fieldset>
          <div className="flex flex-wrap gap-4">
            <label className="flex flex-col gap-1 text-foreground">預算
              <input type="number" min={0} value={budget} onChange={(event) => setBudget(Number(event.target.value))} className="w-32 rounded-md border border-border bg-card px-3 py-1.5" />
            </label>
            <label className="flex flex-col gap-1 text-foreground">天數
              <input type="number" min={state.context.duration_config.min} max={state.context.duration_config.max} value={durationDays} onChange={(event) => setDurationDays(Number(event.target.value))} className="w-24 rounded-md border border-border bg-card px-3 py-1.5" />
            </label>
          </div>
          <fieldset className="flex flex-col gap-2">
            <legend className="font-medium text-foreground">這期要用哪些管道</legend>
            {CHANNEL_OPTIONS.map(({ channel, label }) => (
              <label key={channel} className="flex items-center gap-2 text-foreground">
                <input
                  type="checkbox"
                  checked={enabledChannels[channel]}
                  onChange={() => setEnabledChannels((current) => ({ ...current, [channel]: !current[channel] }))}
                />
                {label}（{enabledChannels[channel] ? "用" : "不用"}）
              </label>
            ))}
          </fieldset>
          <fieldset className="flex flex-col gap-2">
            <legend className="font-medium text-foreground">這期有優惠嗎（選填）</legend>
            <label className="flex items-center gap-2 text-foreground">
              <input type="checkbox" checked={hasOffer} onChange={(event) => setHasOffer(event.target.checked)} /> 這期有折扣、組合或贈品
            </label>
            {hasOffer && (
              <div className="flex flex-col gap-2 rounded-md border border-border p-3">
                <label className="flex flex-col gap-1 text-sm">
                  <span className="text-xs text-muted-foreground">優惠名稱</span>
                  <input
                    value={offerName}
                    onChange={(event) => setOfferName(event.target.value)}
                    maxLength={60}
                    placeholder="例如「全館 8 折」"
                    className="rounded-md border border-border bg-card px-3 py-1.5 text-sm text-foreground"
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
                    onChange={(event) => setOfferTerms(event.target.value)}
                    maxLength={500}
                    rows={2}
                    placeholder="例如「滿 2000 折 300，不含特價品」"
                    className="rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground"
                  />
                </label>
              </div>
            )}
          </fieldset>
        </div>
      )}
      {actionError && <p className="text-sm text-danger">{actionError}</p>}
    </section>
  );
}
