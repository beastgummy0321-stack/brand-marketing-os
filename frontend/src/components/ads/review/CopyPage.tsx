import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Image as ImageIcon, X } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { formatSyncTime } from "@/lib/format";
import { getReview, type ReviewRound } from "@/lib/adsReviewApi";
import { getQueue, type QueuePayload } from "@/lib/adsTriageApi";
import {
  ChangeRequestRejected, createChangeSet, getChangeControl, type ChangeDraft, type SettingValues,
} from "@/lib/adsChangeApi";
import { changeStepPath, truncate } from "../flow/changeFlow";
import { currentBudgetMonth } from "../MonthlyBudgetPanel";
import { ActionBar, Chip, CopyBlock, DecisionSheet, FlowHeader } from "../patterns";
import { findReviewTriageItem, reviewPosition, reviewRoundPath } from "./reviewFlow";

const STEPS = [
  { label: "看證據" }, { label: "選方向" }, { label: "改文案" },
  { label: "確認變更" }, { label: "到平台完成" }, { label: "核對結果" },
];
const STEP_PURPOSE = "圖片不變，只換文字";
const REASON_DEFAULT = "測試新的文案訴求";

/** 小圖示佔位：跟 `PreparePage.tsx`／`ReviewEvidencePage.tsx` 的 `AdTile` 同樣理由自己刻一份
 * 小工具，不是重刻 kit 零件——那兩支沒有 export，這頁只需要一顆中性佔位。 */
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

/** Contract B: `copy_fields` 的形狀跟著素材種類走——動態素材是 `{titles,bodies}` 陣列，其餘是
 * `{title,body}` 單一字串；`adsReviewApi.ts` 的型別還是舊的單一字串形狀（不在這張票的 touch
 * 內），這裡照真實回應（見 `.harness/scratch/F27/F27-I13/real-review.json`）就地放寬讀取。 */
type CopyFields = { title?: string | null; body?: string | null; titles?: string[]; bodies?: string[] };

function copyFieldsOf(review: ReviewRound): CopyFields {
  return (review.evidence_json.conditions.creative_snapshot.copy_fields ?? {}) as CopyFields;
}

/** 「目前」的舊文案：一律讀 `conditions.creative_snapshot.copy_fields`（既有改文案流程
 * `ChangeComposer.tsx` 用的同一組鍵）。 */
function oldCopy(review: ReviewRound): { title: string | null; body: string | null } {
  const fields = copyFieldsOf(review);
  return { title: fields.title ?? null, body: fields.body ?? null };
}

/** 動態素材「目前」的多版本文案：缺少（尚未讀到 Meta 的 `asset_feed_spec.titles/bodies`）一律是
 * 空陣列——contract B「Missing arrays … become empty lists, never an error」，這裡不猜也不補。 */
function oldVariants(review: ReviewRound): { titles: string[]; bodies: string[] } {
  const fields = copyFieldsOf(review);
  return { titles: fields.titles ?? [], bodies: fields.bodies ?? [] };
}

/** 這一輪的「建議直接改文案」：唯一標 `adjust` 的建議（不是永遠第一則）——只有它才有
 * `suggested_copy`，`createChangeSet` 才附 `review_id`/`recommendation_id`（feature Decisions
 * 「改文案」）。 */
function adjustRecommendation(review: ReviewRound) {
  return review.result_json.recommendations?.find((r) => r.recommendation === "adjust") ?? null;
}

/** 目前 → 新版的行差異：哪些「目前」的行（含標題）在新版裡消失了，畫成即時 `<mark>`
 * （prototype `diffOld`，逐行比對、忽略頭尾空白，標題只有真的改了才標）。 */
function diffMarks(oldTitle: string | null, oldBody: string | null, newTitle: string, newBody: string): Set<string> {
  const marks = new Set<string>();
  if (oldTitle !== null && oldTitle.trim() !== newTitle.trim()) marks.add(oldTitle);
  const newLines = new Set(newBody.split("\n").map((l) => l.trim()));
  for (const line of (oldBody ?? "").split("\n")) {
    const trimmed = line.trim();
    if (trimmed && !newLines.has(trimmed)) marks.add(trimmed);
  }
  return marks;
}

/** variants 模式的差異：contract B point 3 把每一則變體當整段字串比對（trim、忽略順序），不逐行
 * 比——一則被換掉時，整段的每一行都標記（`CopyBlock` 本身仍是逐行比對 `marks`，這裡只是把「整段
 * 被換掉」攤成「每一行都在 marks 裡」，不需要改 `CopyBlock` 本身）。 */
function variantMarks(value: string, keptValues: string[]): Set<string> {
  const trimmed = value.trim();
  if (keptValues.some((v) => v.trim() === trimmed)) return new Set();
  return new Set(value.split("\n").map((l) => l.trim()).filter(Boolean));
}

/** 改文案頁（F23-I04，v7 原型 `copy()`）：六步流程第 3 步。`reviewId` 一定已經有一輪檢討——跟
 * `PreparePage` 用同一組合法狀態（`ready`／`completed`，feature Decisions「Review step from a
 * round」把兩者都列為可以往下走的狀態），其餘狀態轉回看證據頁。「新版」預設承接唯一標 `adjust`
 * 的建議附帶的 `suggested_copy`；沒有這則建議時新版留白，也不會替 `createChangeSet` 附上
 * `review_id`/`recommendation_id`（畫面上用一行字說明，不是靜靜省略）。保存失敗分兩種：
 * 4xx（`ChangeRequestRejected`，premise 變了／單則超過 30 天／建議不是 adjust）顯示後端訊息、
 * 保留草稿；其餘（沒收到回應）顯示「上次保存沒收到回應」banner，之後只能用 banner 自己的按鈕
 * 沿用同一份草稿（同一個 `operation_id`）重試——主動作列的「加入變更清單」在這段期間停用，
 * 不讓使用者從另一個入口重複建立（同原型 `setBar` 的第三個參數）。 */
export function CopyPage({ brandId, campaignId, reviewId }: {
  brandId: string; campaignId: string; reviewId: string;
}) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const homeHref = `/brands/${brandId}/ads`;

  const [queue, setQueue] = useState<QueuePayload | null>(null);
  const [review, setReview] = useState<ReviewRound | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [operationId] = useState(() => `review-copy:${reviewId}:${crypto.randomUUID()}`);
  const [initialized, setInitialized] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [variantTitles, setVariantTitles] = useState<string[]>([""]);
  const [variantBodies, setVariantBodies] = useState<string[]>([""]);
  const [reason, setReason] = useState(REASON_DEFAULT);
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [pendingDraft, setPendingDraft] = useState<ChangeDraft | null>(null);

  // `?prefill=observed&set=<id>`（screens「Copy page」）：只在有這兩個參數時才多打一次
  // `getChangeControl`，一般進頁（承接 adjust 建議或留白）不受影響。
  const prefillSetId = searchParams.get("prefill") === "observed" ? searchParams.get("set") : null;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    Promise.all([
      getQueue(brandId).then((q) => { if (!cancelled) setQueue(q); }).catch(() => {}),
      getReview(brandId, campaignId, reviewId).then((r) => { if (!cancelled) setReview(r); }),
    ])
      .catch((err) => { if (!cancelled) setLoadError(err instanceof Error ? err.message : "發生未知錯誤，請稍後再試。"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [brandId, campaignId, reviewId, reloadKey]);

  const validStep = review !== null && (review.status === "ready" || review.status === "completed");

  // 錯的步驟（還沒判讀完、已暫緩、無法判定…）沒有改文案可畫，轉去看證據頁（同 `PreparePage`
  // 的「Wrong step」處理）。
  useEffect(() => {
    if (review && !validStep) {
      navigate(reviewRoundPath(brandId, campaignId, review.id), { replace: true });
    }
  }, [brandId, campaignId, review, validStep, navigate]);

  // 進頁預填新版：有 `?prefill=observed&set=` 就先讀那份清單裡偏離項目的 `evidence_json.observed`
  // （single／variants 都適用，screens「Copy page」）；沒有就照舊承接 adjust 建議的
  // `suggested_copy`（只有單一模式才有這個建議形狀）留白 variants。只在剛讀到這一輪時跑一次。
  useEffect(() => {
    if (!review || !validStep || initialized) return;
    const mode = review.evidence_json.conditions.copy_editable?.mode;
    let cancelled = false;
    async function init() {
      let observed: CopyFields | null = null;
      if (prefillSetId) {
        try {
          const data = await getChangeControl(brandId, campaignId);
          const set = data.change_sets.find((s) => s.id === prefillSetId);
          const item = set?.items.find((it) => it.target_id === review!.entity_id);
          observed = (item?.evidence_json.observed as CopyFields | undefined) ?? null;
        } catch {
          observed = null;
        }
      }
      if (cancelled) return;
      if (mode === "variants") {
        setVariantTitles(observed?.titles?.length ? observed.titles : [""]);
        setVariantBodies(observed?.bodies?.length ? observed.bodies : [""]);
      } else {
        const rec = adjustRecommendation(review!);
        setTitle(observed?.title ?? rec?.suggested_copy?.title ?? "");
        setBody(observed?.body ?? rec?.suggested_copy?.body ?? "");
      }
      setInitialized(true);
    }
    void init();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 只在資料剛讀完時跑一次，不跟著草稿內容重算。
  }, [review, validStep, initialized]);

  async function attemptCommit(draft: ChangeDraft) {
    if (busy) return;
    setBusy(true);
    setSaveError(null);
    try {
      const created = await createChangeSet(brandId, campaignId, draft);
      setPendingDraft(null);
      navigate(changeStepPath(brandId, campaignId, created.id, "confirm"));
    } catch (err) {
      if (err instanceof ChangeRequestRejected) {
        setPendingDraft(null);
        setSaveError(err.message);
      } else {
        // 沒收到回應：草稿已經有效（欄位驗證已通過），保留同一份草稿，讓 banner 的按鈕沿用同一個
        // `operation_id` 重試（feature Decisions「Lost response」）。
        setPendingDraft(draft);
      }
    } finally {
      setBusy(false);
    }
  }

  function handleSave() {
    if (!review || busy) return;
    const isVariants = review.evidence_json.conditions.copy_editable?.mode === "variants";
    const trimmedReason = reason.trim();
    let after: SettingValues;
    if (isVariants) {
      const cleanTitles = variantTitles.map((t) => t.trim()).filter(Boolean);
      const cleanBodies = variantBodies.map((b) => b.trim()).filter(Boolean);
      if (cleanTitles.length === 0 && cleanBodies.length === 0) {
        setSaveError("請至少填寫一則標題或內文。"); return;
      }
      after = { titles: cleanTitles, bodies: cleanBodies };
    } else {
      const trimmedBody = body.trim();
      if (!trimmedBody) { setSaveError("請填寫新內文。"); return; }
      const trimmedTitle = title.trim();
      after = { body: trimmedBody, ...(trimmedTitle ? { title: trimmedTitle } : {}) };
    }
    if (!trimmedReason) { setSaveError("請填寫原因。"); return; }
    const rec = adjustRecommendation(review);
    const draft: ChangeDraft = {
      operation_id: operationId,
      title: `改文案「${truncate(review.evidence_json.target.name ?? "未命名廣告", 60)}」`,
      month: currentBudgetMonth(),
      items: [{ kind: "copy", target_id: review.entity_id, after, reason: trimmedReason }],
      ...(rec ? { review_id: review.id, recommendation_id: rec.id } : {}),
    };
    void attemptCommit(draft);
  }

  if (loading || (review && !validStep)) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "改文案" }]} />
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (loadError) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "改文案" }]} />
        <EmptyState title="讀取失敗" description={loadError} onAction={() => setReloadKey((k) => k + 1)} actionLabel="重新讀取" />
      </div>
    );
  }
  if (!review) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "改文案" }]} />
        <EmptyState
          title="找不到這回檢討" description="網址可能過期，或這回已經被另一回取代。"
          actionHref={homeHref} actionLabel="回投放中心" actionInternal
        />
      </div>
    );
  }

  const triageItem = findReviewTriageItem(queue, review.entity_id);
  const position = reviewPosition(queue, triageItem);
  const isVariants = review.evidence_json.conditions.copy_editable?.mode === "variants";
  const { title: oldTitle, body: oldBody } = oldCopy(review);
  const marks = diffMarks(oldTitle, oldBody, title, body);
  const { titles: oldTitles, bodies: oldBodies } = oldVariants(review);
  const rec = adjustRecommendation(review);
  const moreVersionsHref = `/brands/${brandId}/ads/campaigns/${campaignId}`
    + `?tab=assets&material_new=1&review=${encodeURIComponent(review.id)}`
    + (rec ? `&recommendation=${encodeURIComponent(rec.id)}` : "");

  function updateVariant(list: "titles" | "bodies", index: number, value: string) {
    (list === "titles" ? setVariantTitles : setVariantBodies)((v) => v.map((x, i) => (i === index ? value : x)));
  }
  function addVariant(list: "titles" | "bodies") {
    (list === "titles" ? setVariantTitles : setVariantBodies)((v) => (v.length >= 5 ? v : [...v, ""]));
  }
  function removeVariant(list: "titles" | "bodies", index: number) {
    (list === "titles" ? setVariantTitles : setVariantBodies)((v) => v.filter((_, i) => i !== index));
  }

  return (
    <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "改文案" }]} />
      <FlowHeader
        steps={[
          { ...STEPS[0], to: reviewRoundPath(brandId, campaignId, review.id) },
          { ...STEPS[1], to: reviewRoundPath(brandId, campaignId, review.id, "prepare") },
          ...STEPS.slice(2),
        ]}
        current={2}
        title="改文案"
        purpose={STEP_PURPOSE}
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
            <Chip>圖片不變</Chip>
          </div>
        )}
      />

      {pendingDraft && (
        <div className="flex items-center gap-4 rounded-xl border border-warning/30 bg-warning/10 p-4">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-warning text-base font-semibold text-white" aria-hidden="true">?</div>
          <b className="flex-1">上次保存沒收到回應</b>
          <Button disabled={busy} onClick={() => void attemptCommit(pendingDraft)}>
            {busy ? "核對中…" : "再核對一次（不會重複建立）"}
          </Button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="mb-2.5 flex items-center justify-between">
            <h2 className="font-semibold">目前</h2>
            <Chip>讀取於 {formatSyncTime(review.created_at)}</Chip>
          </div>
          {isVariants ? (
            <div className="flex flex-col gap-4">
              <div>
                <h3 className="mb-1.5 text-xs font-medium text-muted-foreground">標題（{oldTitles.length} 則）</h3>
                {oldTitles.length === 0
                  ? <p className="text-xs text-muted-foreground">目前沒有讀到標題。</p>
                  : (
                    <div className="flex flex-col gap-2">
                      {oldTitles.map((t, i) => (
                        <CopyBlock key={i} tone="old" title={null} body={t} marks={variantMarks(t, variantTitles)} />
                      ))}
                    </div>
                  )}
              </div>
              <div>
                <h3 className="mb-1.5 text-xs font-medium text-muted-foreground">內文（{oldBodies.length} 則）</h3>
                {oldBodies.length === 0
                  ? <p className="text-xs text-muted-foreground">目前沒有讀到內文。</p>
                  : (
                    <div className="flex flex-col gap-2">
                      {oldBodies.map((b, i) => (
                        <CopyBlock key={i} tone="old" title={null} body={b} marks={variantMarks(b, variantBodies)} />
                      ))}
                    </div>
                  )}
              </div>
            </div>
          ) : (
            <CopyBlock tone="old" title={oldTitle} body={oldBody} marks={marks} />
          )}
        </div>

        <div className="rounded-xl border border-border bg-card p-5">
          <div className="mb-2.5 flex items-center justify-between">
            <h2 className="font-semibold">新版</h2>
            <Button variant="link" asChild><Link to={moreVersionsHref}>要更多版本 →</Link></Button>
          </div>
          {isVariants ? (
            <div className="flex flex-col gap-4">
              {(["titles", "bodies"] as const).map((list) => {
                const values = list === "titles" ? variantTitles : variantBodies;
                const label = list === "titles" ? "標題" : "內文";
                return (
                  <div key={list}>
                    <div className="mb-1.5 flex items-center justify-between">
                      <h3 className="text-xs font-medium text-muted-foreground">{label}（最多 5 則）</h3>
                      <Button
                        type="button" variant="outline" size="sm" disabled={busy || values.length >= 5}
                        onClick={() => addVariant(list)}
                      >
                        + 新增{label}
                      </Button>
                    </div>
                    <div className="flex flex-col gap-2">
                      {values.map((v, i) => (
                        <div key={i} className="flex items-start gap-2">
                          {list === "titles"
                            ? <Input aria-label={`新標題 ${i + 1}`} className="font-semibold" value={v} disabled={busy} onChange={(e) => updateVariant(list, i, e.target.value)} />
                            : <Textarea aria-label={`新內文 ${i + 1}`} rows={3} value={v} disabled={busy} onChange={(e) => updateVariant(list, i, e.target.value)} />}
                          <Button
                            type="button" variant="ghost" size="icon-sm" aria-label={`刪除${label} ${i + 1}`}
                            disabled={busy} onClick={() => removeVariant(list, i)}
                          >
                            <X className="size-4" />
                          </Button>
                        </div>
                      ))}
                      {values.length === 0 && <p className="text-xs text-muted-foreground">沒有{label}，至少要在標題或內文留一則。</p>}
                    </div>
                  </div>
                );
              })}
              {!rec && (
                <p className="text-xs text-muted-foreground">沒有可承接的建議，這份清單不會連回這輪檢討。</p>
              )}
            </div>
          ) : (
            <>
              <Input
                aria-label="新標題" className="mb-2 font-semibold" value={title} disabled={busy}
                onChange={(e) => setTitle(e.target.value)}
              />
              <Textarea aria-label="新內文" rows={8} value={body} disabled={busy} onChange={(e) => setBody(e.target.value)} />
              {!rec && (
                <p className="mt-2 text-xs text-muted-foreground">沒有可承接的建議，這份清單不會連回這輪檢討。</p>
              )}
            </>
          )}
        </div>
      </div>

      <DecisionSheet actions={null}>
        <label className="flex min-w-[260px] flex-1 flex-col gap-1 text-sm">
          原因
          <Input value={reason} onChange={(e) => setReason(e.target.value)} disabled={busy} />
        </label>
        <span className="self-center text-xs text-muted-foreground"><mark className="rounded-sm bg-warning/30">{"　"}</mark> 會被換掉的內容</span>
        {saveError && <p role="alert" className="w-full text-xs text-destructive">{saveError}</p>}
      </DecisionSheet>

      <div className="flex-1" />
      <ActionBar back={<Button variant="ghost" asChild><Link to={reviewRoundPath(brandId, campaignId, review.id, "prepare")}>← 選方向</Link></Button>}>
        <Button disabled={busy || pendingDraft !== null} onClick={handleSave}>
          {busy ? "保存中…" : "加入變更清單 →"}
        </Button>
      </ActionBar>
    </div>
  );
}
