import { ExistingCampaignDialog } from "./ExistingCampaignDialog";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/layout/ui/button";
import { refreshQueue } from "@/lib/adsTriageApi";
import { getRecovery, type AdsRecovery } from "@/lib/adsStatusApi";
import { ChangeAttention } from "./ChangeAttention";
import { DecisionQueue, type QueueState } from "./home/DecisionQueue";
import { CampaignCards } from "./home/CampaignCards";
import { BudgetCard } from "./home/BudgetCard";
import { Chip, RecoverSteps } from "./patterns";
import { getOrgId } from "@/lib/auth";
import { isQueueItemDone } from "./home/status";

export { STATUS_LABEL, STATUS_TONE } from "./home/status";

type RecoveryState = { status: "loading" } | { status: "error" } | { status: "ready"; recovery: AdsRecovery };

/** 瀏覽器本地時區的 HH:MM——`gap.start`／`gap.end` 一律是帶時區的 ISO instant（同
 * `home/status.ts::formatRevisitLabel` 的先例），這裡只印時分，不印日期（同一次缺口通常同一
 * 天，`title` 講的是「幾點到幾點」，不是「哪天」）。 */
function formatHM(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** F27-I17（feature Decisions "recovery banner on a > 2 h worker gap"）：`getRecovery` 的卡片，
 * 只在 `recovering` 為真時出現；`steps` 原樣轉給 `RecoverSteps`（`patterns/LoopPieces.tsx`），
 * 文案／順序都是後端算好的（`app/ads/recovery.py`），這裡不重新推導。 */
function RecoveryBanner({ recovery }: { recovery: AdsRecovery }) {
  if (!recovery.recovering || !recovery.gap) return null;
  const hours = Math.floor(recovery.gap.minutes / 60);
  const minutes = recovery.gap.minutes % 60;
  return (
    <div className="rounded-xl border border-primary/20 bg-accent p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-base font-semibold">系統暫停了 {hours} 小時 {minutes} 分，正在補資料</p>
          <p className="mt-0.5 text-[13px] text-muted-foreground">
            {formatHM(recovery.gap.start)} – {formatHM(recovery.gap.end)} 沒有檢查・下面的數字補完後會更新
          </p>
        </div>
        <Chip tone="warn">這段時間平台可能照常花費</Chip>
      </div>
      <RecoverSteps steps={recovery.steps.map((s) => ({ label: s.label, state: s.state }))} />
    </div>
  );
}

/** 投放中心首頁（F19-I02）：v7 版面——今天需要你決定的事（品牌層決定佇列＋月預算）在上，
 * 活動卡在下。照 `docs/design/ads/prototype-v7-ads-center.html` 的 `home()`，不沿用舊版
 * 判斷帶／時間軸／建檔檢查表那一套（那些留給各自的元件檔，首頁不再引用）。
 *
 * Review repair (b)：佇列／月預算／活動卡三塊各自獨立讀取，一塊失敗不拖累另外兩塊——這支
 * 只管佇列（header 的件數也來自它）跟其餘兩塊各自的元件檔自己打自己的 API。
 *
 * F27-I17：頁首原本的「最近同步・N 項待處理」晶片搬到頂欄（F27-I20 的 `layout/Topbar.tsx`，
 * 這張票只負責移除），這支不再打 `listCampaigns` 湊那份同步摘要。改自己獨立打一次
 * `getRecovery`（同樣的「一塊失敗不拖累其他塊」規則——讀不到就不畫這張卡，不擋頁面其他部
 * 分），把 `recovering` 往下傳給 `DecisionQueue`，讓每一列在系統剛恢復期間換成同一顆佔位。 */
function AdsHome({ brandId }: { brandId: string }) {
  const [queueState, setQueueState] = useState<QueueState>({ status: "loading" });
  const [reload, setReload] = useState(0);
  const [recoveryState, setRecoveryState] = useState<RecoveryState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setQueueState({ status: "loading" });
    refreshQueue(brandId, controller.signal)
      .then((queue) => { if (!controller.signal.aborted) setQueueState({ status: "ready", queue }); })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setQueueState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        });
      });
    return () => controller.abort();
  }, [brandId, reload]);

  useEffect(() => {
    const controller = new AbortController();
    getRecovery(brandId, controller.signal)
      .then((recovery) => { if (!controller.signal.aborted) setRecoveryState({ status: "ready", recovery }); })
      .catch(() => { if (!controller.signal.aborted) setRecoveryState({ status: "error" }); });
    return () => controller.abort();
  }, [brandId]);

  // F22-I05 rescope：件數只算還「開著」的列——已核對／已拒絕／已暫緩的停損列已經是完成
  // 狀態（`isQueueItemDone`，跟列自己的按鈕同一個判斷），不該再催使用者去處理。全部完成時
  // （open 件數 0）文案還是「都處理完了」，即使 `queue.items` 本身不是空的。
  const openCount = queueState.status === "ready"
    ? queueState.queue.items.filter((item) => !isQueueItemDone(item)).length
    : 0;
  const purpose = queueState.status === "ready"
    ? (openCount ? `${openCount} 件・由上往下處理就好` : "都處理完了")
    : undefined;
  const recovering = recoveryState.status === "ready" && recoveryState.recovery.recovering;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="今天需要你決定的事"
        description={purpose}
        actions={
          <>
            <Button asChild variant="outline">
              <Link to={`/brands/${brandId}/ads/month`}>每月回顧</Link>
            </Button>
            <ExistingCampaignDialog brandId={brandId} />
            <Button asChild>
              <Link to={`/brands/${brandId}/ads/new`}>建立投放計畫</Link>
            </Button>
          </>
        }
      />
      <div className="flex flex-col gap-6">
        <ChangeAttention brandId={brandId} />
        {recoveryState.status === "ready" && <RecoveryBanner recovery={recoveryState.recovery} />}
        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.9fr)_minmax(0,1fr)]">
          <DecisionQueue state={queueState} onRetry={() => setReload((v) => v + 1)} recovering={recovering} />
          <BudgetCard brandId={brandId} />
        </div>
        <div>
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-[15px] font-semibold">活動</h2>
            <Link to={`/brands/${brandId}/ads/campaigns`} className="text-sm text-primary hover:underline">
              查看全部活動 →
            </Link>
          </div>
          <CampaignCards brandId={brandId} />
        </div>
      </div>
    </div>
  );
}

export function AdsHomePage(props: { brandId: string }) {
  return <AdsHome key={`${getOrgId()}:${props.brandId}`} {...props} />;
}
