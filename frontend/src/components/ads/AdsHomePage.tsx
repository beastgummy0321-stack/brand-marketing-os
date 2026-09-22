import { ExistingCampaignDialog } from "./ExistingCampaignDialog";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/layout/ui/button";
import { refreshQueue } from "@/lib/adsTriageApi";
import type { CampaignCard as CampaignCardData } from "@/lib/adsApi";
import { formatSyncTime } from "@/lib/format";
import { ChangeAttention } from "./ChangeAttention";
import { DecisionQueue, type QueueState } from "./home/DecisionQueue";
import { CampaignCards } from "./home/CampaignCards";
import { BudgetCard } from "./home/BudgetCard";
import { Chip } from "./patterns";
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
  // F24-I02：頁首「最近同步・N 項待處理」晶片——`CampaignCards` 自己打 `listCampaigns`
  // （review repair (b) 的獨立讀取不變），這裡只被動接收它打完後的同一批結果，不重打一次。
  const [syncCampaigns, setSyncCampaigns] = useState<CampaignCardData[]>([]);

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

  // F24-I02 Feature Decisions "Header chip"：「最近同步」只看 `state==="ok"` 的時間戳——
  // 失敗的同步把舊時間戳留在原地（I01 裁決），算進來會把「上次失敗」誤讀成「剛剛才讀過」。
  // 「異常」件數另外數 failed／disconnected 的活動；「N 項待處理」＝這頁自己的 openCount，
  // 跟上面佇列標題共用同一個數字，不是另一套計算。
  const okSyncTimestamps = syncCampaigns
    .map((c) => c.data?.sync)
    .filter((sync): sync is NonNullable<typeof sync> => !!sync && sync.state === "ok" && sync.last_success_at !== null)
    .map((sync) => sync.last_success_at as string);
  const latestSyncAt = okSyncTimestamps.length > 0
    ? okSyncTimestamps.reduce((latest, current) => (current > latest ? current : latest))
    : null;
  const abnormalSyncCount = syncCampaigns
    .filter((c) => c.data?.sync?.state === "failed" || c.data?.sync?.state === "disconnected").length;
  const syncLabel = latestSyncAt ? `最近同步 ${formatSyncTime(latestSyncAt)}` : "尚未同步";

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="今天需要你決定的事"
        description={purpose}
        actions={
          <>
            <Button asChild variant="link" className="h-auto gap-2 p-0 hover:no-underline">
              <Link to={`/brands/${brandId}/ads/connections`} className="flex items-center gap-2">
                <Chip tone={abnormalSyncCount > 0 ? "warn" : "neutral"}>
                  {syncLabel}{abnormalSyncCount > 0 ? `・${abnormalSyncCount} 個活動讀取異常` : ""}
                </Chip>
                <Chip tone={openCount > 0 ? "warn" : "neutral"}>{openCount} 項待處理</Chip>
              </Link>
            </Button>
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
          <CampaignCards brandId={brandId} onSync={setSyncCampaigns} />
        </div>
      </div>
    </div>
  );
}

export function AdsHomePage(props: { brandId: string }) {
  return <AdsHome key={`${getOrgId()}:${props.brandId}`} {...props} />;
}
