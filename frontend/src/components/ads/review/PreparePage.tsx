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
import { findReviewTriageItem, reviewPosition, reviewRoundPath } from "./reviewFlow";

const STEPS = [
  { label: "看證據" }, { label: "選方向" }, { label: "改文案" },
  { label: "確認變更" }, { label: "到平台完成" }, { label: "核對結果" },
];
const STEP_PURPOSE = "依這條素材已處理過的次數給建議";

type Branch = "copy" | "image" | "existing" | "observe" | "retire";
type PickableBranch = "copy" | "observe" | "retire";

const OPTIONS: { key: Branch; icon: string; title: string; note: string; reserved?: boolean }[] = [
  { key: "copy", icon: "📝", title: "只改文案", note: "圖片不變，換文字" },
  { key: "image", icon: "✚", title: "換一張圖", note: "訴求保留，做新圖再回來挑", reserved: true },
  { key: "existing", icon: "🖼", title: "用現成素材", note: "上傳圖片或影片直接用", reserved: true },
  { key: "observe", icon: "⏸", title: "先觀察", note: "不調整，到時間再看" },
  { key: "retire", icon: "■", title: "停掉這則", note: "記為無效，不再投" },
];
// 每個方向的預設「原因」（v7 原型 `prepare()` 的 `#pr` 預設值），換方向就照新方向重填，
// 不沿用使用者在上一個方向打的字（原型同樣行為：`branch()` 換值後整支重繪）。
const REASON_DEFAULT: Record<PickableBranch, string> = {
  copy: "採用建議：保留圖片，測試新文案",
  observe: "資料量還不夠，先觀察",
  retire: "多次調整仍未改善",
};
const PRIMARY_LABEL: Record<PickableBranch, string> = {
  copy: "開始改文案", observe: "保存，先觀察", retire: "建立暫停提議",
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

/** 選方向頁（F23-I03，v7 原型 `prepare()`）：六步流程第 2 步。`reviewId` 一定已經有一輪檢討——
 * 不是 `ready`（還沒判讀完）也不是 `completed`（已經決定過，回頭看這頁）就轉導回看證據頁
 * （feature Decisions「Wrong step」，`completed` 只能從 `ready` 轉，所以合法狀態只有這兩種）。
 * 三個可選方向 copy/observe/retire 各自對到一次 `decideReview` 呼叫與下一步；image/existing
 * 是保留卡（F23 決策 A：階梯佔位），不可選，卡片本身標「接上後開放」而不是拒絕。 */
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

  const [selected, setSelected] = useState<PickableBranch | null>(null);
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

  const first = review?.result_json.recommendations?.[0];
  const recommended: PickableBranch | null =
    first?.recommendation === "adjust" ? "copy" : first?.recommendation === "observe" ? "observe" : null;

  // 進頁預選建議方向（沒有建議時預設「只改文案」，安全、可逆的預設）；只在剛讀到這一輪、
  // 還沒選過方向時跑一次。
  useEffect(() => {
    if (review && validStep && !selected) pick(recommended ?? "copy");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 只在 review 剛讀到時跑一次，選過方向後不再跟著 recommended 重算。
  }, [review, validStep]);

  function pick(key: PickableBranch) {
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
      navigate(selected === "copy"
        ? reviewRoundPath(brandId, campaignId, review.id, "copy")
        : proposePausePath(brandId, campaignId, review.entity_id));
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

  const triageItem = findReviewTriageItem(queue, review.entity_id);
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
        {OPTIONS.map((o) => (
          <OptionCard
            key={o.key}
            icon={o.icon}
            title={o.title}
            note={o.note}
            recommended={!o.reserved && o.key === recommended}
            picked={!o.reserved && o.key === selected}
            disabled={o.reserved}
            onClick={o.reserved ? undefined : () => pick(o.key as PickableBranch)}
          />
        ))}
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
