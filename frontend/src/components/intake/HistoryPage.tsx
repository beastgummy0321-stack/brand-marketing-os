import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";
import { Textarea } from "@/components/layout/ui/textarea";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { COORDINATE_DIMENSIONS, type Coordinate } from "@/lib/coordinatesApi";
import { formatMetaRoas, formatMoney, formatPercent, formatSyncTime } from "@/lib/format";
import { fetchMetaBackfillStatus, startMetaBackfill } from "@/lib/metaApi";
import {
  fetchHistory,
  refetchHistoryCreatives,
  tagHistoryAd,
  type History,
  type HistoryCard,
  type HistoryCoordinateKeys,
  type HistoryVerdict,
  type TagHistoryAdResult,
} from "@/lib/scheduleApi";
import { useFormSubmit } from "@/lib/useFormSubmit";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: History };

const WHY_LABELS: Record<string, string> = {
  top_spend: "花最多",
  top_roas: "賺最多",
  bottom_roas: "賠最多",
};

const VERDICT_LABELS: Record<HistoryVerdict, string> = {
  win: "贏",
  lose: "輸",
  unclear: "看不出",
};

const VERDICT_CLASS: Record<HistoryVerdict, string> = {
  win: "bg-success/10 text-success",
  lose: "bg-danger/10 text-danger",
  unclear: "bg-muted text-muted-foreground",
};

/** 票 past-ads/04（ADR 0067）：把過去的廣告帶進來——投放史卡片清單可能不只一屏，這不違反
 * §10.1「不過一屏」：那條管的是總覽頁（overview），本頁是任務流（跟 §5.1 檔期規劃的階段式
 * 工作區同一類——使用者是來做一件事「逐則標座標」，不是來看一眼儀表板），清單本身仍是
 * 同一份、沒有另外分頁籤，符合 §5「nothing scrolls past one screen of overview」只框住
 * 總覽頁那條界線。 */
export function HistoryPage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [running, setRunning] = useState(false);
  const [runningSince, setRunningSince] = useState<string | null>(null);
  // 略過只影響這次造訪：不打任何 API，純前端隱藏，重新整理就會回來（票面矛盾檢查段）。
  const [skipped, setSkipped] = useState<Set<string>>(new Set());

  const load = useCallback(() => {
    setState({ status: "loading" });
    fetchHistory(brandId)
      .then((data) => {
        setState({ status: "ready", data });
        if (data.backfill?.running) {
          setRunning(true);
          setRunningSince(data.backfill.earliest_spend_date);
        } else {
          setRunning(false);
        }
      })
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }, [brandId]);

  useEffect(load, [load]);

  // ADR 0067 §1.8：補拉是背景工作，跑起來的時候（不管是自己按的還是這一輪其他人已經
  // 啟動過）每 5 秒問一次進度，轉成 false 就重讀一次整包（卡片這時候才會出現）。
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => {
      fetchMetaBackfillStatus(brandId).then((status) => {
        setRunningSince(status.earliest_spend_date);
        if (!status.running) {
          setRunning(false);
          load();
        }
      });
    }, 5000);
    return () => clearInterval(id);
  }, [running, brandId, load]);

  const startForm = useFormSubmit(async () => {
    const res = await startMetaBackfill(brandId);
    setRunning(res.running);
  });

  // 票 past-ads/09（ADR 0067 §1.9 amendment）：owner 按「重新抓素材」——只送目前畫面上
  // （沒被「略過」隱藏）素材是 null 的那些 id；後端不限制只能送這些（票面矛盾檢查段），
  // 這裡送窄的那份是前端自己的選擇，不是後端逼的。
  const refetchForm = useFormSubmit(async () => {
    if (state.status !== "ready") return;
    const nullCreativeIds = state.data.currencies
      .flatMap((currency) => currency.cards)
      .filter((card) => !skipped.has(card.external_id) && card.creative === null)
      .map((card) => card.external_id);
    if (nullCreativeIds.length === 0) return;
    await refetchHistoryCreatives(brandId, nullCreativeIds);
    load();
  });

  if (state.status === "loading") {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />
    );
  }

  const { data } = state;

  if (!data.connected) {
    return (
      <EmptyState
        title="還沒接上 Meta 廣告帳戶"
        description="這一輪只能從 Meta 帶進來；接上以後隨時可以回來。"
        actionHref="/settings"
        actionLabel="前往設定"
        actionInternal
      />
    );
  }

  if (data.backfill && data.backfill.ad_rows === 0) {
    return (
      <div className="surface">
        <div className="surface-body flex flex-col items-start gap-3 pt-5">
          {running ? (
            <p className="text-sm text-foreground">
              正在從 Meta 拉數字{runningSince ? `，目前拉到 ${runningSince}` : "…"}
            </p>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">
                還沒有任何一天的數字，先拉 37 個月的歷史資料。
              </p>
              {startForm.error && <p className="text-sm text-danger">{startForm.error}</p>}
              <Button type="button" disabled={startForm.saving} onClick={() => void startForm.submit()}>
                {startForm.saving ? "啟動中…" : "開始拉 37 個月的數字"}
              </Button>
            </>
          )}
        </div>
      </div>
    );
  }

  const visibleCards = data.currencies
    .flatMap((currency) => currency.cards)
    .filter((card) => !skipped.has(card.external_id));
  const hasNullCreative = visibleCards.some((card) => card.creative === null);

  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm text-muted-foreground">
        這些是 Meta 現在還回得出的廣告，不一定是你投過的全部。
      </p>
      {hasNullCreative && (
        <div className="flex flex-col items-start gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={refetchForm.saving}
            onClick={() => void refetchForm.submit()}
          >
            {refetchForm.saving ? "重新抓取中…" : "重新抓素材"}
          </Button>
          {refetchForm.error && <p className="text-sm text-danger">{refetchForm.error}</p>}
        </div>
      )}
      {data.breakeven && data.breakeven.roas === null && (
        <p className="text-sm text-muted-foreground">
          算不出打平線（{data.breakeven.source}），所以只排序、不判贏輸。
        </p>
      )}
      {data.currencies.map((currency) => (
        <section key={currency.currency} className="flex flex-col gap-4">
          <h2 className="text-base font-medium text-foreground">{currency.currency}</h2>
          <div className="flex flex-col gap-4">
            {currency.cards
              .filter((card) => !skipped.has(card.external_id))
              .map((card) => (
                <HistoryCardItem
                  key={card.external_id}
                  brandId={brandId}
                  card={card}
                  currency={currency.currency}
                  coordinates={data.coordinates}
                  onSkip={() =>
                    setSkipped((prev) => {
                      const next = new Set(prev);
                      next.add(card.external_id);
                      return next;
                    })
                  }
                />
              ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function HistoryCardItem({
  brandId,
  card,
  currency,
  coordinates,
  onSkip,
}: {
  brandId: string;
  card: HistoryCard;
  currency: string;
  coordinates: Coordinate[];
  onSkip: () => void;
}) {
  const [values, setValues] = useState<HistoryCoordinateKeys>(card.coordinates);
  const [note, setNote] = useState(card.owner_note ?? "");
  const [saved, setSaved] = useState<TagHistoryAdResult | null>(null);

  const { saving, error, submit } = useFormSubmit(async () => {
    const result = await tagHistoryAd(brandId, card.external_id, {
      coordinates: values,
      owner_note: note.trim() ? note.trim() : null,
    });
    setSaved(result);
  });

  return (
    <div className="surface">
      <div className="surface-body grid grid-cols-1 gap-6 pt-5 lg:grid-cols-2">
        <div className="flex flex-col gap-3">
          {card.creative?.image_url ? (
            <img
              src={card.creative.image_url}
              alt={card.name}
              className="h-40 w-full rounded-md border border-border object-cover"
            />
          ) : (
            <div className="flex h-40 w-full items-center justify-center rounded-md border border-dashed border-border bg-muted p-3 text-center text-xs text-muted-foreground">
              {card.creative_error ?? "Meta 現在回不出這則的素材"}
            </div>
          )}
          <div>
            <h3 className="text-sm font-medium text-foreground">{card.name}</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              投放期間 {card.first_seen_date}–{card.last_seen_date}
            </p>
          </div>
          {card.why.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {card.why.map((why) => (
                <Badge key={why} variant="secondary">
                  {WHY_LABELS[why] ?? why}
                </Badge>
              ))}
            </div>
          )}
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
            <div>
              <dt className="text-xs text-muted-foreground">花費</dt>
              <dd className="numeric text-foreground">{formatMoney(card.spend, currency)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">CPA</dt>
              <dd className="numeric text-foreground">{formatMoney(card.cpa, currency)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">ROAS（保守）</dt>
              <dd className="numeric text-foreground">{formatMetaRoas(card.roas_conservative)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">ROAS（樂觀）</dt>
              <dd className="numeric text-foreground">{formatMetaRoas(card.roas)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">追蹤覆蓋</dt>
              <dd className="numeric text-foreground">{formatPercent(card.roas_coverage)}</dd>
            </div>
          </dl>
          <Badge className={VERDICT_CLASS[card.verdict]}>{VERDICT_LABELS[card.verdict]}</Badge>
        </div>

        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {COORDINATE_DIMENSIONS.map(([dimension, label]) => (
              <label key={dimension} className="flex flex-col gap-1 text-sm">
                <span className="font-medium text-foreground">{label}</span>
                <select
                  value={values[dimension] ?? ""}
                  onChange={(e) =>
                    setValues((prev) => ({ ...prev, [dimension]: e.target.value || null }))
                  }
                  className="rounded-md border border-border px-3 py-2 text-sm text-foreground"
                >
                  <option value="">不填</option>
                  {coordinates
                    .filter((c) => c.dimension === dimension)
                    .map((c) => (
                      <option key={c.id} value={c.key}>
                        {c.label}
                      </option>
                    ))}
                </select>
              </label>
            ))}
          </div>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-foreground">這則為什麼贏／輸？</span>
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} />
          </label>
          {error && <p className="text-sm text-danger">{error}</p>}
          {saved && (
            <p className="text-sm text-success">已記錄・{formatSyncTime(saved.tagged_at)}</p>
          )}
          <div className="flex gap-2">
            <Button type="button" disabled={saving} onClick={() => void submit()}>
              {saving ? "儲存中…" : "儲存"}
            </Button>
            <Button type="button" variant="outline" onClick={onSkip}>
              略過
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
