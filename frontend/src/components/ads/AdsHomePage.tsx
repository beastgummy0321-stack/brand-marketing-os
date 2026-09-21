import { ExistingCampaignDialog } from "./ExistingCampaignDialog";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { listCampaigns, type CampaignCard } from "@/lib/adsApi";
import { refreshQueue, type QueuePayload } from "@/lib/adsTriageApi";
import { getChangeControlSummary } from "@/lib/adsChangeApi";
import { ChangeAttention } from "./ChangeAttention";
import { DecisionQueue } from "./home/DecisionQueue";
import { CampaignCards } from "./home/CampaignCards";
import { BudgetCard } from "./home/BudgetCard";
import { getOrgId } from "@/lib/auth";

export { STATUS_LABEL, STATUS_TONE } from "./home/status";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; queue: QueuePayload; campaigns: CampaignCard[] };

/** 投放中心首頁（F19-I02）：v7 版面——今天需要你決定的事（品牌層決定佇列＋月預算）在上，
 * 活動卡在下。照 `docs/design/ads/prototype-v7-ads-center.html` 的 `home()`，不沿用舊版
 * 判斷帶／時間軸／建檔檢查表那一套（那些留給各自的元件檔，首頁不再引用）。 */
function AdsHome({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [showChangeAttention, setShowChangeAttention] = useState(false);

  function load() {
    setState({ status: "loading" });
    Promise.all([refreshQueue(brandId), listCampaigns(brandId)])
      .then(([queue, campaigns]) => setState({ status: "ready", queue, campaigns }))
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(load, [brandId]);

  // ChangeAttention 只在真的有待確認清單時才佔首屏（Feature Decisions）；它自己會再讀一次
  // 完整內容並自帶錯誤重試，這裡只用來決定要不要掛上去，讀取失敗時保守顯示。
  useEffect(() => {
    const controller = new AbortController();
    getChangeControlSummary(brandId, controller.signal)
      .then((summary) => { if (!controller.signal.aborted) setShowChangeAttention(summary.pending_count > 0); })
      .catch(() => { if (!controller.signal.aborted) setShowChangeAttention(true); });
    return () => controller.abort();
  }, [brandId]);

  const purpose = state.status === "ready"
    ? (state.queue.items.length ? `${state.queue.items.length} 件・由上往下處理就好` : "都處理完了")
    : undefined;

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />;
  } else {
    const { queue, campaigns } = state;
    content = (
      <div className="flex flex-col gap-6">
        {showChangeAttention && <ChangeAttention brandId={brandId} />}
        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.9fr)_minmax(0,1fr)]">
          <DecisionQueue queue={queue} />
          <BudgetCard brandId={brandId} />
        </div>
        <div>
          <h2 className="mb-3 text-[15px] font-semibold">活動</h2>
          <CampaignCards brandId={brandId} campaigns={campaigns} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="今天需要你決定的事"
        description={purpose}
        actions={
          <>
            <Button variant="outline" disabled aria-label="每月回顧，接上後開放">每月回顧</Button>
            <Badge variant="secondary">接上後開放</Badge>
            <ExistingCampaignDialog brandId={brandId} />
            <Button asChild>
              <Link to={`/brands/${brandId}/ads/new`}>建立投放計畫</Link>
            </Button>
          </>
        }
      />
      {content}
    </div>
  );
}

export function AdsHomePage(props: { brandId: string }) {
  return <AdsHome key={`${getOrgId()}:${props.brandId}`} {...props} />;
}
