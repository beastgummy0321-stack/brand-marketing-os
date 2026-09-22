import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Image as ImageIcon } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { Input } from "@/components/layout/ui/input";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { decideReview, getReview, type ReviewRound } from "@/lib/adsReviewApi";
import { getQueue, type QueuePayload } from "@/lib/adsTriageApi";
import { proposePausePath } from "../flow/changeFlow";
import { ActionBar, DecisionSheet, FlowHeader, OptionCard, Segmented } from "../patterns";
import { findReviewTriageItem, reviewMaterialPath, reviewPosition, reviewRoundPath } from "./reviewFlow";

const STEPS = [
  { label: "看證據" }, { label: "選方向" }, { label: "改文案" },
  { label: "確認變更" }, { label: "到平台完成" }, { label: "核對結果" },
];
const STEP_PURPOSE = "依這條素材已處理過的次數給建議";

type Branch = "copy" | "image" | "existing" | "observe" | "retire";
// F27-I12: ladder step → branch, `["copy","image","retire"][ladder.step]` — mirrors the prototype
// `prepare()`'s own `rec=["copy","image","retire"][a.ladder]` exactly (Contract A `step: 0|1|2`).
const LADDER_BRANCH = ["copy", "image", "retire"] as const;

const OPTIONS: { key: Branch; icon: string; title: string; note: string }[] = [
  { key: "copy", icon: "📝", title: "只改文案", note: "圖片不變，換文字" },
  { key: "image", icon: "✚", title: "換一張圖", note: "訴求保留，做新圖再回來挑" },
  { key: "existing", icon: "🖼", title: "用現成素材", note: "上傳圖片或影片直接用" },
  { key: "observe", icon: "⏸", title: "先觀察", note: "不調整，到時間再看" },
  { key: "retire", icon: "■", title: "停掉這則", note: "記為無效，不再投" },
];
// 每個方向的預設「原因」（v7 原型 `prepare()` 的 `#pr` 預設值），換方向就照新方向重填，
// 不沿用使用者在上一個方向打的字（原型同樣行為：`branch()` 換值後整支重繪）。
const REASON_DEFAULT: Record<Branch, string> = {
  copy: "採用建議：保留圖片，測試新文案",
  image: "文案改過仍未改善，換圖",
  existing: "改用現成素材",
  observe: "資料量還不夠，先觀察",
  retire: "多次調整仍未改善",
};
const PRIMARY_LABEL: Record<Branch, string> = {
  copy: "開始改文案", image: "準備新圖", existing: "上傳素材",
  observe: "保存，先觀察", retire: "建立暫停提議",
};

/** 小圖示佔位：跟 `ReviewEvidencePage.tsx` 的 `AdTile` 同樣理由自己刻一份小工具，不是重刻 kit
 * 零件——那支沒有 export，這頁只需要一顆中性佔位。 */
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

/** 選方向頁（F23-I03／F27-I12，v7 原型 `prepare()`）：六步流程第 2 步。`reviewId` 一定已經有一輪
 * 檢討——不是 `ready`（還沒判讀完）也不是 `completed`（已經決定過，回頭看這頁）就轉導回看證據頁
 * （feature Decisions「Wrong step」，`completed` 只能從 `ready` 轉，所以合法狀態只有這兩種）。
 * 五個方向 copy/image/existing/observe/retire 都可選，各自對到一次 `decideReview` 呼叫與下一步
 * （F27 Screens「Prepare page」：換一張圖／用現成素材不再是階梯佔位，decide completed 後導去
 * I14 的素材頁，帶對應 `mode`）。建議依這則廣告的階梯 `ladder.step`（Contract A）決定，除非這一輪
 * 的第一個 AI 建議是 `observe`；只改文案在 `copy_editable.ok === false`（Contract B／correction 7，
 * 例如商品目錄素材沒有可改的文字）時停用，原本被建議挪去換一張圖。 */
export function PreparePage({ brandId, campaignId, reviewId }: {
  brandId: string; campaignId: string; reviewId: string;
}) {
  const navigate = useNavigate();
  const homeHref = `/brands/${brandId}/ads`;

  const [queue, setQueue] = useState<QueuePayload | null>(null);
  const [review, setReview] = useState<ReviewRound | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const [selected, setSelected] = useState<Branch | null>(null);
  const [reason, setReason] = useState("");
  const [quickPick, setQuickPick] = useState<"3" | "7" | "custom">("7");
  const [customDate, setCustomDate] = useState("");
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

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

  // 錯的步驟（還沒判讀完、已暫緩、無法判定…）沒有選方向可畫，轉去看證據頁——那裡才有正確的
  // 卡片與先不決定選單（feature Decisions「Wrong step」）。
  useEffect(() => {
    if (review && !validStep) {
      navigate(reviewRoundPath(brandId, campaignId, review.id), { replace: true });
    }
  }, [brandId, campaignId, review, validStep, navigate]);

  // `triageItem`（連帶 `ladder`）來自 `queue`，跟 `review` 各自一支 fetch——用 `!loading` 而不是
  // `review` 當 effect 的依據，避免兩支 fetch 誰先回來的競態讓自動預選讀到還沒到位的 `queue`。
  const triageItem = findReviewTriageItem(queue, review?.entity_id);
  const ladder = triageItem?.triage.ladder;
  const first = review?.result_json.recommendations?.[0];
  // F27 Screens「Prepare page」：建議 = 階梯步驟，除非這一輪第一個建議是 observe。
  const ladderRecommended: Branch | null = ladder ? LADDER_BRANCH[ladder.step] : null;
  const recommended: Branch | null = first?.recommendation === "observe" ? "observe" : ladderRecommended;
  const copyEditable = review?.evidence_json.conditions.copy_editable;
  const copyDisabled = copyEditable?.ok === false;
  // 建議指到只改文案，但那張卡停用時，挪去下一步（換一張圖）——不把建議標籤放在不能點的卡上。
  const effectiveRecommended: Branch | null = recommended === "copy" && copyDisabled ? "image" : recommended;

  // 進頁預選建議方向（沒有建議時預設「只改文案」，安全、可逆的預設）；只在資料剛讀完、
  // 還沒選過方向時跑一次。
  useEffect(() => {
    if (!loading && review && validStep && !selected) pick(effectiveRecommended ?? "copy");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 只在資料剛讀完時跑一次，選過方向後不再跟著 effectiveRecommended 重算。
  }, [loading, review, validStep]);

  function pick(key: Branch) {
    setSelected(key);
    setReason(REASON_DEFAULT[key]);
    setQuickPick("7");
    setCustomDate("");
    setSaveError(null);
  }

  function revisitAt(): Date | null {
    if (selected !== "observe") return null;
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
  const revisitValid = selected !== "observe" || (revisit !== null && revisit.getTime() > Date.now());

  async function handleSave() {
    if (!review || !selected || busy) return;
    const trimmed = reason.trim();
    if (!trimmed) { setSaveError("請填寫原因。"); return; }
    if (!revisitValid) { setSaveError("請選一個之後的時間。"); return; }
    setBusy(true);
    setSaveError(null);
    try {
      if (selected === "observe") {
        await decideReview(brandId, campaignId, review.id, {
          decision: "deferred", reason: trimmed, revisit_at: revisit!.toISOString(),
        });
        navigate(reviewRoundPath(brandId, campaignId, review.id));
        return;
      }
      // `completed` 只能從 `ready` 轉一次；已經是 completed 的一輪（回頭改方向）跳過這次呼叫
      // （feature Decisions「a round already completed skips the decide call」）。
      if (review.decision !== "completed") {
        await decideReview(brandId, campaignId, review.id, { decision: "completed", reason: trimmed });
      }
      // F27 Screens「Prepare page」：copy → 改文案頁；retire → F22 停損提議頁；image/existing →
      // I14 的素材頁，帶對應 `mode`（decide completed 一定先跑，跟 copy/retire 同一套順序）。
      if (selected === "copy") navigate(reviewRoundPath(brandId, campaignId, review.id, "copy"));
      else if (selected === "retire") navigate(proposePausePath(brandId, campaignId, review.entity_id));
      else navigate(reviewMaterialPath(brandId, campaignId, review.id, selected === "image" ? "workbench_image" : "existing"));
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "發生未知錯誤，請稍後再試。");
    } finally {
      setBusy(false);
    }
  }

  if (loading || (review && !validStep)) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "選方向" }]} />
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (loadError) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "選方向" }]} />
        <EmptyState title="讀取失敗" description={loadError} onAction={() => setReloadKey((k) => k + 1)} actionLabel="重新讀取" />
      </div>
    );
  }
  if (!review) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "選方向" }]} />
        <EmptyState
          title="找不到這回檢討" description="網址可能過期，或這回已經被另一回取代。"
          actionHref={homeHref} actionLabel="回投放中心" actionInternal
        />
      </div>
    );
  }

  const position = reviewPosition(queue, triageItem);

  return (
    <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "選方向" }]} />
      <FlowHeader
        steps={STEPS}
        current={1}
        title="這次要做什麼"
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
          </div>
        )}
      />

      <div className="grid grid-cols-2 gap-3.5 xl:grid-cols-5">
        {OPTIONS.map((o) => {
          // 只有「只改文案」會停用（Contract B `copy_editable.ok === false`）；image/existing/
          // observe/retire 一律可選（F27 Screens「Prepare page」，不再有原型的階梯佔位卡）。
          const disabled = o.key === "copy" && copyDisabled;
          return (
            <OptionCard
              key={o.key}
              icon={o.icon}
              title={o.title}
              note={o.note}
              recommended={o.key === effectiveRecommended}
              picked={o.key === selected}
              disabled={disabled}
              disabledNote={disabled ? (copyEditable?.reason ?? "這則廣告的文字目前不能單獨修改。") : undefined}
              onClick={disabled ? undefined : () => pick(o.key)}
            />
          );
        })}
      </div>

      {selected && (
        <DecisionSheet actions={null}>
          <label className="flex min-w-[260px] flex-1 flex-col gap-1 text-sm">
            原因
            <Input value={reason} onChange={(e) => setReason(e.target.value)} disabled={busy} />
          </label>
          {selected === "observe" && (
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
          {saveError && <p role="alert" className="w-full text-xs text-destructive">{saveError}</p>}
        </DecisionSheet>
      )}

      <div className="flex-1" />
      <ActionBar back={<Button variant="ghost" asChild><Link to={reviewRoundPath(brandId, campaignId, review.id)}>← 看證據</Link></Button>}>
        {selected && (
          <Button disabled={busy} onClick={() => void handleSave()}>
            {busy ? "保存中…" : `${PRIMARY_LABEL[selected]} →`}
          </Button>
        )}
      </ActionBar>
    </div>
  );
}
