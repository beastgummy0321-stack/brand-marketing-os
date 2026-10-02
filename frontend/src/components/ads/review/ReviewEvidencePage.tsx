import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Image as ImageIcon } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { Input } from "@/components/layout/ui/input";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import {
  createReview, decideReview, getReview, retryReview,
  type ReviewRound,
} from "@/lib/adsReviewApi";
import { getQueue, type GradeMove } from "@/lib/adsTriageApi";
import { useApiRead } from "@/lib/useApiRead";
import { proposalAction } from "../home/status";
import {
  ActionBar, Chip, DecisionSheet, Disclosure, EvidenceRow, FlowHeader, GRADE_LABEL, GradeChip, Ladder, MoneyTag, ReadFailed, Segmented,
  Term, TodoRow,
} from "../patterns";
import { perSaleAmount } from "../patterns/csv";
import {
  adResultView, adSpend, commerceCoverageWarn, findReviewTriageItem, formatCostLabel,
  formatEntryDate, formatRevisitLabel, formatTargetAmount, formatWindowDate, HISTORY_KIND_LABEL,
  isSalesResultKind, RECOMMENDATION_TITLE, reviewPosition, reviewRoundPath,
} from "./reviewFlow";

const STEPS = [
  { label: "看證據" }, { label: "選方向" }, { label: "改文案" },
  { label: "確認變更" }, { label: "到平台完成" }, { label: "核對結果" },
];
const STEP_PURPOSE = "先看數字，再決定";

/** F29-I14 (v10 `stepEv()`): the headline names the grade move against the cap (Contract A `grade_move`, the only
 * thing that raises a 變貴 row); without one it stays neutral — no guess from the trend. The purpose names whose cap
 * the ad is measured against (the campaign's own, 「跟<活動>的上限比」). */
function worseHeadline(move: GradeMove | null | undefined): string {
  return move ? `這則從${GRADE_LABEL[move.from]}變${GRADE_LABEL[move.to]}` : "看看這則廣告的數字";
}
function worsePurpose(campaignName: string | null | undefined): string {
  const short = campaignName?.split("・")[0]?.trim();
  return short ? `跟${short}的上限比，${STEP_PURPOSE}` : STEP_PURPOSE;
}
const POLL_MS = 3000;
/** F47-I06: the crumb names the queue row this review came from by its own kind (a review opened from the performance
 * page, or for a row of another kind, was labelled 「變貴」 even on a good ad); no row → 「檢討」. */
const ROW_KIND_LABEL: Record<string, string> = {
  stop_loss: "停損", worse: "變貴", scale_budget: "加預算", refresh_creative: "補素材", insufficient_data: "資料不足", cleanup: "清理",
};

type SheetKind = "deferred" | "unjudgeable";

/** 小圖示佔位：跟 `flow/ConfirmPage.tsx` 的 `Tile` 同樣理由自己刻一份小工具，不是重刻 kit 零件
 * ——那支沒有 export，這頁只需要一顆中性佔位。 */
function AdTile({ url }: { url?: string | null }) {
  return (
    <div className="flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-muted" aria-hidden="true">
      {url ? (
        // eslint-disable-next-line @next/next/no-img-element -- 這裡不是 Next.js 專案。
        <img src={url} alt="" className="size-full object-cover" />
      ) : (
        <ImageIcon className="size-6 text-muted-foreground" />
      )}
    </div>
  );
}

/** 看證據頁（F23-I02，v7 原型 `review()`＋`sheet()`）：六步流程的第一步，`entityId`（entry route）
 * 還沒有檢討回合，第一次進來就沿用佇列列已有的 `proposal.review_id`，沒有才即時建立一輪
 * （feature Decisions「Agent choice — routes」）；`reviewId`（reviews route）已經有回合，是這頁
 * 的正典網址。非 confirm 步驟的選方向／改文案由 I03/I04 建頁，這裡只提供連結。 */
export function ReviewEvidencePage({ brandId, campaignId, entityId, reviewId }: {
  brandId: string; campaignId: string; entityId?: string; reviewId?: string;
}) {
  const navigate = useNavigate();
  const homeHref = `/brands/${brandId}/ads`;

  const [review, setReview] = useState<ReviewRound | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Entry mode: a failed queue read is not "no proposal" — its own state, with 重試.
  const [entryFailed, setEntryFailed] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  // Contract K — round mode: the queue is context (campaign chip, 第幾件, ladder, history, target); a failed read is
  // shown with 重試, never silently dropped. Entry mode reads the queue itself below.
  const queueRead = useApiRead(
    (signal) => (reviewId ? getQueue(brandId, signal) : Promise.resolve(null)),
    [brandId, campaignId, reviewId, reloadKey],
  );
  const queue = queueRead.data;

  const [busy, setBusy] = useState(false);
  const [sheetKind, setSheetKind] = useState<SheetKind | null>(null);
  const [reason, setReason] = useState("");
  const [quickPick, setQuickPick] = useState<"3" | "7" | "custom">("7");
  const [customDate, setCustomDate] = useState("");
  const [sheetError, setSheetError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  // Entry mode（`entityId`，還沒有 `reviewId`）：先看佇列列有沒有既有回合，沒有才建立一輪，
  // 完成後一律 `navigate(replace)` 到正典的 `reviews/:reviewId` 網址（feature Decisions）。
  useEffect(() => {
    if (!entityId) return;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setEntryFailed(null);
    (async () => {
      let q;
      try {
        q = await getQueue(brandId);
      } catch (err) {
        // The queue read failed: that is not "no proposal" (Contract K) — its own state with 重試.
        if (!cancelled) {
          setEntryFailed(err instanceof Error ? err.message : "發生未知錯誤，請稍後再試。");
          setLoading(false);
        }
        return;
      }
      try {
        if (cancelled) return;
        const item = q.items.find((i) => i.triage.entity_id === entityId) ?? null;
        const existingId = item?.proposal?.kind === "review" ? item.proposal.review_id : null;
        if (existingId) {
          navigate(reviewRoundPath(brandId, campaignId, existingId), { replace: true });
          return;
        }
        if (!item) {
          setLoadError("找不到這則廣告的檢討提議，可能已經處理過，或資料剛好還沒同步到投放中心。");
          setLoading(false);
          return;
        }
        const created = await createReview(brandId, campaignId, {
          entity_id: entityId, start: item.triage.window.start, end: item.triage.window.end,
        });
        if (cancelled) return;
        navigate(reviewRoundPath(brandId, campaignId, created.id), { replace: true });
      } catch (err) {
        // Creating the round was refused (e.g. the campaign closed): the backend's own words, unchanged.
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : "發生未知錯誤，請稍後再試。");
          setLoading(false);
        }
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `navigate` 是穩定的 router 函式。
  }, [brandId, campaignId, entityId, reloadKey]);

  // Round 模式（`reviewId`）：讀這回合＋佇列（供位置與 campChip）。
  useEffect(() => {
    if (!reviewId) return;
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setRetryError(null);
    getReview(brandId, campaignId, reviewId)
      .then((r) => { if (!cancelled) setReview(r); })
      .catch((err) => { if (!cancelled) setLoadError(err instanceof Error ? err.message : "發生未知錯誤，請稍後再試。"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [brandId, campaignId, reviewId, reloadKey]);

  // 每 3 秒輪詢一次，卸載時停止（issue Done #3）。
  const pollingId = review?.id, pollingStatus = review?.status;
  useEffect(() => {
    if (!pollingId || !pollingStatus || !["queued", "running"].includes(pollingStatus)) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await getReview(brandId, campaignId, pollingId!, controller.signal);
        if (controller.signal.aborted) return;
        setReview(result);
        if (["queued", "running"].includes(result.status)) timer = setTimeout(() => void poll(), POLL_MS);
      } catch {
        if (!controller.signal.aborted) timer = setTimeout(() => void poll(), POLL_MS);
      }
    }
    timer = setTimeout(() => void poll(), POLL_MS);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [brandId, campaignId, pollingId, pollingStatus]);

  function openSheet(kind: SheetKind) {
    setSheetKind(kind);
    setReason(kind === "deferred" ? "等資料更完整" : "資料缺漏，無法比較");
    setQuickPick("7");
    setCustomDate("");
    setSheetError(null);
  }
  function closeSheet() { setSheetKind(null); }

  function revisitAt(): Date | null {
    if (sheetKind !== "deferred") return null;
    if (quickPick === "custom") {
      if (!customDate) return null;
      const d = new Date(customDate);
      return Number.isNaN(d.getTime()) ? null : d;
    }
    const d = new Date();
    d.setDate(d.getDate() + (quickPick === "3" ? 3 : 7));
    return d;
  }
  const revisit = revisitAt();
  const revisitValid = sheetKind !== "deferred" || (revisit !== null && revisit.getTime() > Date.now());

  async function handleSaveDecision() {
    if (!review || !sheetKind || busy) return;
    const trimmed = reason.trim();
    if (!trimmed) { setSheetError("請填寫原因。"); return; }
    if (!revisitValid) { setSheetError("請選一個之後的時間。"); return; }
    setBusy(true);
    setSheetError(null);
    try {
      const updated = await decideReview(brandId, campaignId, review.id, {
        decision: sheetKind,
        reason: trimmed,
        ...(sheetKind === "deferred" ? { revisit_at: revisit!.toISOString() } : {}),
      });
      setReview(updated);
      closeSheet();
    } catch (err) {
      setSheetError(err instanceof Error ? err.message : "發生未知錯誤，請稍後再試。");
    } finally {
      setBusy(false);
    }
  }

  // Contract A (F30): re-run a failed or AI-rejected round on the same evidence. The new round replaces this one,
  // so the page moves to its canonical URL (running state); a refusal (409) keeps this page and says why.
  async function handleRetry() {
    if (!review || retrying) return;
    setRetrying(true);
    setRetryError(null);
    try {
      const { review: next } = await retryReview(brandId, campaignId, review.id);
      navigate(reviewRoundPath(brandId, campaignId, next.id));
    } catch (err) {
      setRetryError(err instanceof Error ? err.message : "發生未知錯誤，請稍後再試。");
    } finally {
      setRetrying(false);
    }
  }

  // Entry mode 畫面：轉導完成前只有讀取中或錯誤兩種狀態。
  if (entityId) {
    if (entryFailed) {
      return (
        <div className="flex flex-col gap-4">
          <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "看證據" }]} />
          <ReadFailed what={`這則廣告的檢討讀不到（${entryFailed}）；已保存的決定都還在`} onRetry={() => setReloadKey((k) => k + 1)} />
        </div>
      );
    }
    if (loadError) {
      return (
        <div className="flex flex-col gap-4">
          <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "看證據" }]} />
          <EmptyState
            title="沒有這回的檢討提議" description={loadError}
            actionHref={homeHref} actionLabel="回投放中心" actionInternal
          />
        </div>
      );
    }
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "看證據" }]} />
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (loading || (queueRead.status === "loading" && !queue)) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "看證據" }]} />
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (loadError) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "看證據" }]} />
        <EmptyState title="讀取失敗" description={loadError} onAction={() => setReloadKey((k) => k + 1)} actionLabel="重新讀取" />
      </div>
    );
  }
  if (!review) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "看證據" }]} />
        <EmptyState
          title="找不到這回檢討" description="網址可能過期，或這回已經被另一回取代。"
          actionHref={homeHref} actionLabel="回投放中心" actionInternal
        />
      </div>
    );
  }

  const triageItem = findReviewTriageItem(queue, review.entity_id);
  const position = reviewPosition(queue, triageItem);
  const evidence = review.evidence_json;
  const running = review.status === "queued" || review.status === "running";
  const waiting = review.status === "waiting";
  const failed = review.status === "failed" || review.status === "unknown";
  const closed = review.decision === "deferred" || review.decision === "unjudgeable";
  const completed = review.decision === "completed";
  const showEvidence = !running && !waiting && !failed;
  const showMenu = waiting || failed || closed || (!running && !waiting && !failed && !completed);
  // Contract A: the fact check rejected the model text — the numbers stand on their own, the AI card says so.
  const rejected = !!review.result_json.rejected;
  // Retry is allowed for an undecided round that failed (not `unknown`) or whose AI text was rejected.
  const canRetry = review.decision === null && (review.status === "failed" || rejected);

  const matchedProposal = triageItem?.proposal ?? null;
  const continueAction = completed
    ? (matchedProposal && matchedProposal.kind === "review" && matchedProposal.review_id === review.id
      ? proposalAction(brandId, campaignId, review.entity_id, matchedProposal, "review")
      : { label: "選擇處理方向", href: reviewRoundPath(brandId, campaignId, review.id, "prepare"), done: false })
    : null;

  const resultLabel = triageItem?.triage.target.result_label ?? "成果";
  const targetValue = triageItem?.triage.target.value ?? null;
  const recommendations = review.result_json.recommendations ?? [];
  const first = recommendations[0];
  const commerceCurrent = evidence.commerce?.current ?? null;
  const commercePrevious = evidence.commerce?.previous ?? null;
  // F27-I11 Contract A / Screens「Review page」: live ladder + 「這條素材的紀錄」 for non-sales
  // campaigns, replacing the always-on commerce card the placeholder ladder shipped with.
  const ladder = triageItem?.triage.ladder ?? null;
  const history = triageItem?.triage.history ?? [];
  const isSales = isSalesResultKind(triageItem?.triage.target.result_kind ?? null);

  const closedChip = review.decision === "deferred"
    ? `${review.revisit_at ? formatRevisitLabel(review.revisit_at) : "已暫緩"}・${review.reason ?? ""}`
    : review.decision === "unjudgeable"
      ? `無法判定・${review.reason ?? ""}`
      : null;

  return (
    <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: `${(triageItem && ROW_KIND_LABEL[triageItem.kind_key]) || "檢討"}・${evidence.target.name ?? "廣告"}` }]} />
      <FlowHeader
        steps={STEPS}
        current={0}
        title={worseHeadline(triageItem?.triage.grade_move)}
        purpose={worsePurpose(triageItem?.triage.campaign_name)}
        context={triageItem ? (
          <>
            <Badge variant="outline" className="max-w-[14rem] shrink" title={triageItem.triage.campaign_name}>
              <span className="block w-full min-w-0 truncate">{triageItem.triage.campaign_name}</span>
            </Badge>
            {position && <span>第 {position.pos} 件／共 {position.total} 件</span>}
          </>
        ) : undefined}
        aside={showEvidence ? (
          <div className="flex items-center gap-2">
            {ladder && <Ladder steps={["改文案", "換圖", "退役"]} current={ladder.step} />}
            {closedChip && <Chip tone="neutral">{closedChip}</Chip>}
          </div>
        ) : undefined}
      />

      {queueRead.status === "error" && (
        <ReadFailed what="待決定清單讀不到：活動名稱、「第幾件」、處理階梯與上限暫時看不到；下面的證據照舊" onRetry={queueRead.reload} />
      )}

      {waiting && (
        <div className="rounded-xl border border-warning/30 bg-warning/10 p-5">
          <h2 className="text-lg font-semibold">資料還不夠，這回先不判</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
            {evidence.waiting_reasons.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>
      )}

      {failed && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-lg font-semibold">本次未完成</h2>
              <p className="mt-2 text-sm text-muted-foreground">{review.error ?? "結果尚未確認，請稍後再試。"}</p>
            </div>
            {canRetry && (
              <Button variant="outline" disabled={retrying} onClick={() => void handleRetry()}>
                {retrying ? "送出中…" : "再請 AI 看一次"}
              </Button>
            )}
          </div>
          {retryError && <p role="alert" className="mt-2 text-xs text-destructive">{retryError}</p>}
        </div>
      )}

      {running && (
        <div className="rounded-xl border border-border bg-card py-16 text-center">
          <div className="text-2xl" aria-hidden="true">✦</div>
          <h2 className="mt-2 text-lg font-semibold">AI 正在整理證據</h2>
          <p className="mt-1 text-[15px] text-muted-foreground">可以先離開，好了會出現在投放中心</p>
        </div>
      )}

      {showEvidence && rejected && (
        // v10 ai-blocked `stepEv()` `adIdent()`: with no AI card the ad's identity is a full-width card on top.
        <div className="flex items-center gap-3.5 rounded-xl border border-border bg-card p-5">
          <AdTile url={triageItem?.triage.thumbnail_url} />
          <div className="min-w-0 flex-1">
            {triageItem && <GradeChip grade={triageItem.triage.grade} label={triageItem.triage.grade_label} />}
            <p className="mt-1 line-clamp-2 font-semibold">{evidence.target.name ?? "（未命名廣告）"}</p>
          </div>
        </div>
      )}

      {showEvidence && (
        <div className={rejected ? "grid items-start gap-4 xl:grid-cols-2" : "grid items-start gap-4 xl:grid-cols-[1.05fr_1fr_1fr]"}>
          {!rejected && (
          <div className="rounded-xl border border-primary/20 bg-accent p-5">
            <div className="mb-3.5 flex items-center gap-3">
              <AdTile url={triageItem?.triage.thumbnail_url} />
              <p className="line-clamp-2 min-w-0 flex-1 font-semibold">{evidence.target.name ?? "（未命名廣告）"}</p>
            </div>
            {first ? (
              <>
                <Chip tone="accent">✦ AI 建議</Chip>
                <p className="mt-2 text-xl font-semibold">{RECOMMENDATION_TITLE[first.recommendation]}</p>
                <p className="mt-1.5 text-sm text-muted-foreground">{first.hypothesis}</p>
                <Disclosure label="依據與風險">
                  <div className="space-y-1.5 text-sm text-muted-foreground">
                    {first.risks.map((r, i) => <p key={i}>・{r}</p>)}
                    <p>{first.next_step}</p>
                  </div>
                </Disclosure>
              </>
            ) : (
              <>
                <p className="font-semibold">AI 沒有給出建議</p>
                {(review.result_json.limitations ?? []).map((l, i) => (
                  <p key={i} className="mt-1 text-sm text-muted-foreground">{l}</p>
                ))}
              </>
            )}
          </div>
          )}

          <div className="rounded-xl border border-border bg-card p-5">
            <div className="mb-1.5 flex items-center justify-between">
              <h2 className="font-semibold">這則廣告</h2>
              <Chip>平台回報</Chip>
            </div>
            <EvidenceRow label="花費" previous={adSpend(evidence.previous)} current={adSpend(evidence.current)} />
            <EvidenceRow
              label={resultLabel}
              previous={adResultView(evidence.previous)?.result_count ?? null}
              current={adResultView(evidence.current)?.result_count ?? null}
            />
            <EvidenceRow
              label={`每次${resultLabel}成本`}
              previous={adResultView(evidence.previous)?.cost_per_result ?? null}
              current={adResultView(evidence.current)?.cost_per_result ?? null}
              format={perSaleAmount}
            />
            {/* v10 `mt(a)`: the cost against break-even, beside the grade's own ruler (the cap). */}
            <div className="numeric text-right">
              <MoneyTag cost={adResultView(evidence.current)?.cost_per_result ?? null} breakEven={triageItem?.triage.target.break_even ?? null} />
            </div>
            <div className="mt-2.5 flex flex-wrap gap-2">
              <Chip>{evidence.current.days_present}/{evidence.current.days_expected} 天有資料</Chip>
              {targetValue !== null && <Chip><Term k="cap">上限</Term> {formatTargetAmount(targetValue)}</Chip>}
            </div>
          </div>

          {queueRead.status === "error" ? (
            // The history and the sales/non-sales split both come from the queue row: unknown, not "no history".
            <div className="rounded-xl border border-border bg-card p-5">
              <h2 className="mb-1.5 font-semibold">這條素材的紀錄</h2>
              <p className="py-3 text-sm text-muted-foreground">讀取失敗，按上方重試後再看。</p>
            </div>
          ) : isSales ? (
            commerceCurrent && commercePrevious && (
              <div className="rounded-xl border border-border bg-card p-5">
                <div className="mb-1.5 flex items-center justify-between">
                  <h2 className="font-semibold">商城訂單</h2>
                  <Chip>品牌整體・分不到單則</Chip>
                </div>
                <EvidenceRow label="訂單數" previous={commercePrevious.order_summary.count} current={commerceCurrent.order_summary.count} />
                <EvidenceRow label="訂單淨額" previous={commercePrevious.order_summary.order_net_amount} current={commerceCurrent.order_summary.order_net_amount} />
                <EvidenceRow label="已付款淨額" previous={commercePrevious.order_summary.paid_net_amount} current={commerceCurrent.order_summary.paid_net_amount} />
                {commerceCoverageWarn(commerceCurrent.order_summary) && (
                  <div className="mt-2.5 flex items-center gap-2">
                    <Chip tone="warn">報表期間待確認</Chip>
                    <Button variant="link" asChild><Link to={`/brands/${brandId}/orders`}>補報表</Link></Button>
                  </div>
                )}
              </div>
            )
          ) : (
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="mb-1.5 flex items-center justify-between">
                <h2 className="font-semibold">這條素材的紀錄</h2>
                <Chip>已處理 {history.length} 次</Chip>
              </div>
              {history.length === 0 ? (
                <p className="py-3 text-sm text-muted-foreground">這則廣告還沒有處理紀錄。</p>
              ) : (
                history.map((h, i) => (
                  <TodoRow key={h.change_set_id} no={i + 1} done>
                    <b className="font-medium">{formatEntryDate(h.approved_at)} {HISTORY_KIND_LABEL[h.kind]}</b>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      之後 7 天・每次{resultLabel}成本 {formatCostLabel(h.cost_before)} → {formatCostLabel(h.cost_after)}
                    </div>
                  </TodoRow>
                ))
              )}
              <div className="mt-2.5"><Chip>這個活動看{resultLabel}，不看商城訂單</Chip></div>
            </div>
          )}

          <div className="col-span-full flex gap-3.5 text-xs text-muted-foreground">
            <span><i className="mr-1.5 inline-block h-1.5 w-3.5 rounded-sm bg-border" aria-hidden="true" />前期 {formatWindowDate(evidence.window.previous_start)}–{formatWindowDate(evidence.window.previous_end)}</span>
            <span><i className="mr-1.5 inline-block h-1.5 w-3.5 rounded-sm bg-primary" aria-hidden="true" />本期 {formatWindowDate(evidence.window.start)}–{formatWindowDate(evidence.window.end)}</span>
            {/* Contract A: the ▲▼ against the previous window is a trend note; the grade (against the cap) decides. */}
            <span>前後升降只當參考，分級看<Term k="cap">上限</Term></span>
          </div>

          {rejected && (
            // v10 ai-blocked `aiBlockedCard()`: the dashed card under the evidence, with the one way back to an AI text.
            <div className="col-span-full rounded-xl border border-dashed border-border bg-card p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <b className="font-semibold">✦ AI 這次的說明沒採用</b>
                  <p className="mt-1 text-sm text-muted-foreground">它的說明沒通過事實檢查，系統先擋下。上面的數字是平台直接給的，照樣可以判斷。</p>
                </div>
                {canRetry && (
                  <Button variant="outline" disabled={retrying} onClick={() => void handleRetry()}>
                    {retrying ? "送出中…" : "再請 AI 看一次"}
                  </Button>
                )}
              </div>
              {retryError && <p role="alert" className="mt-2 text-xs text-destructive">{retryError}</p>}
            </div>
          )}
        </div>
      )}

      <div className="flex-1" />
      <ActionBar
        back={{ label: "投放中心", to: homeHref }}
        exit={closed ? undefined : { label: "先不要，回投放中心", to: homeHref }}
        hint={closed ? "要改文案請等下一回證據" : undefined}
      >
        {/* 先不決定／改變決定（feature Decisions「Sheet」）：`@/components/layout/ui/dropdown-menu`
         * 的 Radix `Trigger asChild` 會讓外層自己的 `data-slot="dropdown-menu-trigger"` 蓋掉
         * `Button` 自己的 `data-slot="button"`，讓 `ui-evidence.cjs` 的零件辨識把觸發鈕誤判成
         * 「hand-rolled control」——那支不在這張票的 touch 範圍，改用 issue 本身允許的退路：
         * ActionBar 裡兩顆直接開 sheet 的按鈕，不做選單分組。 */}
        {showMenu && (
          <>
            <Button variant="outline" disabled={busy} onClick={() => openSheet("deferred")}>暫緩</Button>
            <Button variant="outline" disabled={busy} onClick={() => openSheet("unjudgeable")}>無法判定</Button>
          </>
        )}
        {!running && !waiting && !failed && !closed && !completed && (
          <Button asChild disabled={busy}>
            <Link to={reviewRoundPath(brandId, campaignId, review.id, "prepare")}>選擇處理方向 →</Link>
          </Button>
        )}
        {continueAction && (
          <Button asChild disabled={busy}>
            <Link to={continueAction.href}>{continueAction.label} →</Link>
          </Button>
        )}
      </ActionBar>

      {sheetKind && (
        <DecisionSheet
          title={sheetKind === "deferred" ? "暫緩" : "無法判定"}
          actions={<>
            <Button variant="outline" disabled={busy} onClick={closeSheet}>取消</Button>
            <Button disabled={busy} onClick={() => void handleSaveDecision()}>{busy ? "保存中…" : "保存"}</Button>
          </>}
        >
          <label className="flex min-w-[220px] flex-1 flex-col gap-1 text-sm">
            原因
            <Input value={reason} onChange={(e) => setReason(e.target.value)} disabled={busy} />
          </label>
          {sheetKind === "deferred" && (
            <label className="flex flex-col gap-1 text-sm">
              何時重看
              <div className="flex items-center gap-2">
                <Segmented
                  label="何時重看"
                  options={[{ value: "3", label: "3 天後" }, { value: "7", label: "7 天後" }, { value: "custom", label: "自訂" }]}
                  value={quickPick}
                  onChange={setQuickPick}
                />
                {quickPick === "custom" && (
                  <Input type="date" aria-label="重看日期" value={customDate} onChange={(e) => setCustomDate(e.target.value)} disabled={busy} />
                )}
              </div>
            </label>
          )}
          {sheetError && <p role="alert" className="w-full text-xs text-destructive">{sheetError}</p>}
        </DecisionSheet>
      )}
    </div>
  );
}
