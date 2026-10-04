import { useEffect, useState } from "react";
import { Image as ImageIcon } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { Input } from "@/components/layout/ui/input";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { getCampaign, type CampaignDetail } from "@/lib/adsApi";
import { getReview, type ReviewRound } from "@/lib/adsReviewApi";
import { getQueue } from "@/lib/adsTriageApi";
import { useApiRead } from "@/lib/useApiRead";
import type { MaterialMode } from "@/lib/adsMaterialApi";
import {
  createNewAdHandoff, getHandoff, HandoffRequestRejected,
  type HandoffPlacement, type HandoffWorkspace, type NewAdHandoffRequest,
} from "@/lib/adsHandoffApi";
import { MaterialTasksPanel } from "../MaterialTasksPanel";
import { materialModes } from "../MaterialTaskEditor";
import { UserAssetPlacements } from "../UserAssetPlacements";
import { changeStepPath, truncate } from "../flow/changeFlow";
import { currentBudgetMonth } from "../MonthlyBudgetPanel";
import { useOrgClock } from "@/lib/orgClock";
import { ActionBar, FlowHeader, ReadFailed } from "../patterns";
import { findReviewTriageItem, reviewPosition, reviewRoundPath } from "./reviewFlow";

const STEPS = [
  { label: "看證據" }, { label: "選方向" }, { label: "準備素材" },
  { label: "確認變更" }, { label: "到平台完成" }, { label: "核對結果" },
];

/** 小圖示佔位：跟 `PreparePage.tsx`／`CopyPage.tsx` 的 `AdTile` 同樣理由自己刻一份，那兩支
 * 沒有 export，這頁只需要一顆中性佔位。 */
function AdTile({ url }: { url?: string | null }) {
  return (
    <div className="flex size-7 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-muted" aria-hidden="true">
      {url ? (
        // eslint-disable-next-line @next/next/no-img-element -- 這裡不是 Next.js 專案。
        <img src={url} alt="" className="size-full object-cover" />
      ) : (
        <ImageIcon className="size-4 text-muted-foreground" />
      )}
    </div>
  );
}

/** 這一輪唯一標 `new_test` 的建議（同 `CopyPage.tsx::adjustRecommendation` 的理由，不是永遠
 * 第一則）——只有它才讓素材任務與新廣告交接帶回這輪檢討的連結（correction 5）；其餘情況（換圖／
 * 用現成素材只是接續原本的建議、沒有另一則 new_test 建議）交接只帶 `replaces_entity_id`，不附
 * `review_id`／`recommendation_id`（`app/ads/handoff_new_ad.py::_review` 對不是 new_test 的建議
 * 會直接拒絕）。 */
function newTestRecommendation(review: ReviewRound) {
  return review.result_json.recommendations?.find((r) => r.recommendation === "new_test") ?? null;
}

/** 這則廣告所屬的投放組（F49-I14，Contract D）：交接讀取的 `destination_by_ad`（廣告 → 它的上層投放組），
 * 不分活動來源——系統建立的活動也一樣讀得到，不再只看匯入活動才有的 `external_view`。找不到就是誠實的
 * 未知，不畫一個假的目的地。 */
function adSetOf(handoff: HandoffWorkspace | null, entityId: string | undefined): string | null {
  return (entityId && handoff?.destination_by_ad?.[entityId]) || null;
}

/** 準備素材頁（F27-I14，無原型畫面）：六步流程第 3 步。組裝既有的素材任務／自帶素材安排元件，
 * 範圍限定在這一輪檢討；有成品確認安排後，「建立新廣告提議」直接送出人工交接（目的地＝這則廣告
 * 所屬投放組，`replaces_entity_id`＝這則廣告，Screens「Material step」）。`reviewId` 一定已經有
 * 一輪檢討——跟 `PreparePage`／`CopyPage` 用同一組合法狀態（`ready`／`completed`），其餘狀態轉回
 * 看證據頁。 */
export function MaterialStepPage({ brandId, campaignId, reviewId }: {
  brandId: string; campaignId: string; reviewId: string;
}) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const homeHref = `/brands/${brandId}/ads`;

  const [review, setReview] = useState<ReviewRound | null>(null);
  const [campaign, setCampaign] = useState<CampaignDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Contract K: the queue is context (campaign chip, 第幾件, thumbnail) and the handoff workspace feeds 「建立新廣告提議」;
  // each is its own read, and a failure is said out loud with 重試 — never an empty list of ready materials.
  const queueRead = useApiRead((signal) => getQueue(brandId, signal), [brandId, campaignId, reviewId, reloadKey]);
  const queue = queueRead.data;
  const handoffRead = useApiRead<HandoffWorkspace>(() => getHandoff(brandId, campaignId), [brandId, campaignId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    Promise.all([
      getReview(brandId, campaignId, reviewId).then((r) => { if (!cancelled) setReview(r); }),
      getCampaign(brandId, campaignId).then((c) => { if (!cancelled) setCampaign(c); }),
    ])
      .catch((err) => { if (!cancelled) setLoadError(err instanceof Error ? err.message : "發生未知錯誤，請稍後再試。"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [brandId, campaignId, reviewId, reloadKey]);

  const validStep = review !== null && (review.status === "ready" || review.status === "completed");

  // 錯的步驟沒有素材可準備，轉去看證據頁（同 `PreparePage`／`CopyPage` 的「Wrong step」處理）。
  useEffect(() => {
    if (review && !validStep) {
      navigate(reviewRoundPath(brandId, campaignId, review.id), { replace: true });
    }
  }, [brandId, campaignId, review, validStep, navigate]);

  const newTestRec = review ? newTestRecommendation(review) : null;

  // 把這一輪檢討的來源連回素材任務（`MaterialTasksPanel` 自己讀 URL 的 `review`／`recommendation`
  // 參數）——只有這一輪帶著 new_test 建議才附，否則新增素材需求時就不會送 `review_id`（correction
  // 5）。`material_new` 一律附上，顯示「承接上次檢討」的提示。只在資料剛讀完、還沒補上時跑一次。
  useEffect(() => {
    // 走錯步驟時上面那顆 effect 已經在轉導離開這頁，這裡不再搶著改同一個網址的查詢字串
    // （兩顆 effect 同時呼叫 navigate 會互相蓋掉，讓轉導卡住）。
    if (!review || !validStep) return;
    const next = new URLSearchParams(searchParams);
    let changed = false;
    if (next.get("material_new") !== "1") { next.set("material_new", "1"); changed = true; }
    if (newTestRec) {
      if (next.get("review") !== review.id) { next.set("review", review.id); changed = true; }
      if (next.get("recommendation") !== newTestRec.id) { next.set("recommendation", newTestRec.id); changed = true; }
    }
    if (changed) setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 只在 review／newTestRec／validStep 剛讀完時補一次，不跟著 searchParams 自己的每次變化重算。
  }, [review, newTestRec, validStep]);

  const modeParam = searchParams.get("mode") as MaterialMode | null;
  const stepMode: MaterialMode = modeParam === "existing" ? "existing" : "workbench_image";
  const modeInfo = materialModes[stepMode];

  const destinationEntityId = review ? adSetOf(handoffRead.data, review.entity_id) : null;
  const readyPlacements = handoffRead.data?.ready_placements ?? [];

  if (loading || (queueRead.status === "loading" && !queue) || (review && !validStep)) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "準備素材" }]} />
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (loadError) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "準備素材" }]} />
        <EmptyState title="讀取失敗" description={loadError} onAction={() => setReloadKey((k) => k + 1)} actionLabel="重新讀取" />
      </div>
    );
  }
  if (!review) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "準備素材" }]} />
        <EmptyState
          title="找不到這回檢討" description="網址可能過期，或這回已經被另一回取代。"
          actionHref={homeHref} actionLabel="回投放中心" actionInternal
        />
      </div>
    );
  }

  const triageItem = findReviewTriageItem(queue, review.entity_id);
  const position = reviewPosition(queue, triageItem);

  return (
    <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "準備素材" }]} />
      <FlowHeader
        steps={[
          { ...STEPS[0], to: reviewRoundPath(brandId, campaignId, review.id) },
          { ...STEPS[1], to: reviewRoundPath(brandId, campaignId, review.id, "prepare") },
          ...STEPS.slice(2),
        ]}
        current={2}
        title={modeInfo.title}
        purpose={modeInfo.description}
        context={triageItem ? (
          <>
            <Badge variant="outline" className="max-w-[14rem] shrink" title={triageItem.triage.campaign_name}>
              <span className="block w-full min-w-0 truncate">{triageItem.triage.campaign_name}</span>
            </Badge>
            {position && <span>第 {position.pos} 件／共 {position.total} 件</span>}
          </>
        ) : undefined}
        aside={(
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <AdTile url={triageItem?.triage.thumbnail_url} />
            <span className="max-w-[14rem] truncate">{review.evidence_json.target.name ?? "（未命名廣告）"}</span>
          </div>
        )}
      />

      {queueRead.status === "error" && (
        <ReadFailed what="待決定清單讀不到：活動名稱與「第幾件」暫時看不到；這一步照舊可以做" onRetry={queueRead.reload} />
      )}

      <MaterialTasksPanel brandId={brandId} campaignId={campaignId} onSaved={handoffRead.reload} />

      {campaign && <UserAssetPlacements brandId={brandId} campaign={campaign} onChanged={handoffRead.reload} />}

      {handoffRead.status === "error" ? (
        <section className="surface" aria-label="建立新廣告提議">
          <div className="surface-header"><h2>建立新廣告提議</h2></div>
          <div className="surface-body">
            <ReadFailed what="已就緒的成品讀不到；上面準備好的素材都還在" onRetry={handoffRead.reload} />
          </div>
        </section>
      ) : (
        <NewAdSection
          brandId={brandId} campaignId={campaignId} review={review}
          newTestRecommendationId={newTestRec?.id ?? null}
          destinationEntityId={destinationEntityId}
          destinationsNote={handoffRead.data?.destinations_note ?? null}
          readyPlacements={readyPlacements}
          placementsLoading={handoffRead.status === "loading" && !handoffRead.data}
        />
      )}

      <div className="flex-1" />
      <ActionBar back={{ label: "選方向", to: reviewRoundPath(brandId, campaignId, review.id, "prepare") }} exit={{ label: "先不要，回投放中心", to: homeHref }} />
    </div>
  );
}

/** 「建立新廣告提議」（Screens「Material step」）：有已確認、就緒的成品才能送出——目的地自動取
 * 這則廣告目前所屬的投放組，`replaces_entity_id` 固定是這則廣告，不讓使用者手動另選（跟既有
 * `ManualHandoffPanel` 的「新增獨立廣告」不同，那支是通用交接、目的地要使用者自己選；這裡是這輪
 * 檢討專用的捷徑，兩者不是同一個流程，不重疊）。 */
function NewAdSection({ brandId, campaignId, review, newTestRecommendationId, destinationEntityId, destinationsNote, readyPlacements, placementsLoading }: {
  brandId: string; campaignId: string; review: ReviewRound;
  newTestRecommendationId: string | null; destinationEntityId: string | null;
  /** The handoff read's `destinations_note` (why the campaign has no ad set to offer yet); null when it has some. */
  destinationsNote: string | null;
  readyPlacements: HandoffPlacement[]; placementsLoading: boolean;
}) {
  const navigate = useNavigate();
  const { timezone } = useOrgClock();
  const [operationId] = useState(() => `review-material-handoff:${review.id}:${crypto.randomUUID()}`);
  const [placementId, setPlacementId] = useState("");
  const [title, setTitle] = useState("");
  const [reason, setReason] = useState("承接這次檢討，測試新素材");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<NewAdHandoffRequest | null>(null);

  useEffect(() => {
    if (!title) setTitle(`新廣告「${truncate(review.evidence_json.target.name ?? "廣告", 40)}」`);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 只在還沒填過名稱時補一次預設值，不覆蓋使用者已編輯的內容。
  }, [review]);

  if (readyPlacements.length === 0) {
    return (
      <section className="surface" aria-label="建立新廣告提議">
        <div className="surface-header"><h2>建立新廣告提議</h2></div>
        <div className="surface-body"><p className="text-sm text-muted-foreground">{placementsLoading ? "正在讀取已就緒的成品…" : "還沒有已確認、就緒的成品；請先在上方準備素材並確認安排。"}</p></div>
      </section>
    );
  }

  const selected = readyPlacements.find((p) => p.id === placementId) ?? null;
  const canSubmit = Boolean(selected && destinationEntityId && title.trim() && reason.trim() && !busy);

  async function submit() {
    if (busy) return;
    if (!selected || !destinationEntityId) { setError("請選擇已就緒的成品。"); return; }
    const trimmedTitle = title.trim(), trimmedReason = reason.trim();
    if (!trimmedTitle || !trimmedReason) { setError("請填寫新廣告名稱與理由。"); return; }
    const request: NewAdHandoffRequest = pending ?? {
      operation_id: operationId, title: trimmedTitle, month: currentBudgetMonth(timezone),
      placement_id: selected.id, revision: selected.revision, destination_entity_id: destinationEntityId,
      reason: trimmedReason, replaces_entity_id: review.entity_id,
      ...(newTestRecommendationId ? { review_id: review.id, recommendation_id: newTestRecommendationId } : {}),
    };
    setBusy(true);
    setError(null);
    try {
      const result = await createNewAdHandoff(brandId, campaignId, request);
      setPending(null);
      navigate(changeStepPath(brandId, campaignId, result.id, "confirm"));
    } catch (err) {
      if (err instanceof HandoffRequestRejected) {
        setPending(null);
        setError(err.message);
      } else {
        // 沒收到回應：請求已有效，保留同一份請求，讓使用者用同一個 `operation_id` 重試
        // （同 `CopyPage.tsx::attemptCommit` 的「Lost response」處理）。
        setPending(request);
        setError(err instanceof Error ? err.message : "尚未收到保存結果，請沿用同一次操作重試。");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="surface" aria-label="建立新廣告提議">
      <div className="surface-header"><h2>建立新廣告提議</h2><p className="mt-1 text-sm text-muted-foreground">核准後才由你到平台新增這則廣告；原廣告會在新廣告讀回核對後才提議暫停。</p></div>
      <div className="surface-body space-y-3">
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">選擇要使用的成品</legend>
          {readyPlacements.map((p) => (
            <label key={`${p.id}:${p.revision}`} className="flex items-center gap-2 text-sm">
              <input
                type="radio" name="material-step-placement" disabled={busy}
                checked={placementId === p.id} onChange={() => setPlacementId(p.id)}
              />
              {p.filename} · 第 {p.revision} 版{p.purpose ? ` · ${p.purpose}` : ""}
            </label>
          ))}
        </fieldset>
        <label className="block text-sm">新廣告名稱<Input value={title} maxLength={200} disabled={busy} onChange={(e) => setTitle(e.target.value)} /></label>
        <label className="block text-sm">理由<Input value={reason} disabled={busy} onChange={(e) => setReason(e.target.value)} /></label>
        {!destinationEntityId && <p data-slot="destination-missing" className="text-sm text-warning">{destinationsNote ?? "還沒讀到這則廣告目前所屬的投放組；到投放結構按重新讀取後再試，仍可先確認素材安排。"}</p>}
        {pending && <div className="rounded-md bg-warning/10 p-3 text-sm space-y-2"><p>上一次建立沒收到回應，結果尚未確認。請沿用同一次操作重試，不會重複建立。</p><Button variant="outline" disabled={busy} onClick={() => void submit()}>重試建立</Button></div>}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <Button disabled={!canSubmit || Boolean(pending)} onClick={() => void submit()}>{busy ? "建立中…" : "建立新廣告提議 →"}</Button>
      </div>
    </section>
  );
}
