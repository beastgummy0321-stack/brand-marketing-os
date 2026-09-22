import { ExistingCampaignDialog } from "./ExistingCampaignDialog";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/layout/ui/button";
import { refreshQueue } from "@/lib/adsTriageApi";
import { ChangeAttention } from "./ChangeAttention";
import { DecisionQueue, type QueueState } from "./home/DecisionQueue";
import { CampaignCards } from "./home/CampaignCards";
import { BudgetCard } from "./home/BudgetCard";
import { getOrgId } from "@/lib/auth";
import { isQueueItemDone } from "./home/status";

export { STATUS_LABEL, STATUS_TONE } from "./home/status";

/** 投放中心首頁（F19-I02）：v7 版面——今天需要你決定的事（品牌層決定佇列＋月預算）在上，
 * 活動卡在下。照 `docs/design/ads/prototype-v7-ads-center.html` 的 `home()`，不沿用舊版
 * 判斷帶／時間軸／建檔檢查表那一套（那些留給各自的元件檔，首頁不再引用）。
 *
 * Review repair (b)：佇列／月預算／活動卡三塊各自獨立讀取，一塊失敗不拖累另外兩塊——這支
 * 只管佇列（header 的件數也來自它）跟其餘兩塊各自的元件檔自己打自己的 API。 */
function AdsHome({ brandId }: { brandId: string }) {
  const [queueState, setQueueState] = useState<QueueState>({ status: "loading" });
  const [reload, setReload] = useState(0);

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

  // F22-I05 rescope：件數只算還「開著」的列——已核對／已拒絕／已暫緩的停損列已經是完成
  // 狀態（`isQueueItemDone`，跟列自己的按鈕同一個判斷），不該再催使用者去處理。全部完成時
  // （open 件數 0）文案還是「都處理完了」，即使 `queue.items` 本身不是空的。
  const openCount = queueState.status === "ready"
    ? queueState.queue.items.filter((item) => !isQueueItemDone(item)).length
    : 0;
  const purpose = queueState.status === "ready"
    ? (openCount ? `${openCount} 件・由上往下處理就好` : "都處理完了")
    : undefined;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="今天需要你決定的事"
        description={purpose}
        actions={
          <>
            {/* review repair (f)：非互動佔位，同 ReservedSlotCard 規則——連 disabled 假按鈕都不做。 */}
            <span className="inline-flex items-center rounded-full border border-dashed border-border bg-muted px-3 py-1.5 text-sm text-muted-foreground">
              每月回顧・接上後開放
            </span>
            <ExistingCampaignDialog brandId={brandId} />
            <Button asChild>
              <Link to={`/brands/${brandId}/ads/new`}>建立投放計畫</Link>
            </Button>
          </>
        }
      />
      <div className="flex flex-col gap-6">
        <ChangeAttention brandId={brandId} />
        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.9fr)_minmax(0,1fr)]">
          <DecisionQueue state={queueState} onRetry={() => setReload((v) => v + 1)} />
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
