import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { CampaignCard } from "./CampaignCard";
import { listCampaigns, type CampaignCard as CampaignCardData } from "@/lib/adsApi";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; campaigns: CampaignCardData[] };

/** 一張卡一個 Campaign（F19-I02 版面骨架；F19-I04 換上 v7 `CampaignCard`——名稱、目標、
 * 五分類條見那支）。自己打 `listCampaigns`，讀取失敗不拖累佇列卡或月預算卡（review repair
 * (b)）。只列未結案的 Campaign（含既有平台活動）；已結案的透過 `AdsHomePage` 旁邊的
 * 「查看全部活動」連到清單頁找，不在這裡塞（review repair (h)）。
 *
 * F24-I02：`onSync` 是給 `AdsHomePage.tsx` 的頁首同步晶片用的旁路——這支還是自己獨立打
 * `listCampaigns`（讀取失敗不拖累頁首，跟其餘兩塊一樣獨立），只是成功時把整批 campaign
 * 「順便」回報給上層，不必上層再打第二支同一支 API。用 ref 存 callback，不進 effect 的
 * 依賴陣列，避免上層每次 render 傳新的箭頭函式時重打一次 `listCampaigns`。 */
export function CampaignCards({ brandId, onSync }: { brandId: string; onSync?: (campaigns: CampaignCardData[]) => void }) {
  const navigate = useNavigate();
  const [state, setState] = useState<State>({ status: "loading" });
  const [reload, setReload] = useState(0);
  const onSyncRef = useRef(onSync);
  onSyncRef.current = onSync;

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    listCampaigns(brandId)
      .then((campaigns) => {
        if (cancelled) return;
        setState({ status: "ready", campaigns });
        onSyncRef.current?.(campaigns);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" });
      });
    return () => { cancelled = true; };
  }, [brandId, reload]);

  if (state.status === "loading") {
    return (
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2 2xl:grid-cols-3">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <EmptyState
        title="讀取失敗"
        description={state.message}
        onAction={() => setReload((v) => v + 1)}
        actionLabel="重新載入"
      />
    );
  }

  const campaigns = state.campaigns.filter((c) => c.status !== "closed");

  if (campaigns.length === 0) {
    return (
      <EmptyState
        title="還沒有 Campaign"
        description="建立第一個 Campaign，讓行銷駕駛艙幫你完成後續設定。"
        actionLabel="建立投放計畫"
        onAction={() => navigate(`/brands/${brandId}/ads/new`)}
      />
    );
  }

  return (
    <div data-testid="campaign-grid" className="grid grid-cols-1 gap-4 xl:grid-cols-2 2xl:grid-cols-3">
      {campaigns.map((c) => (
        <CampaignCard key={c.id} brandId={brandId} campaign={c} />
      ))}
    </div>
  );
}
