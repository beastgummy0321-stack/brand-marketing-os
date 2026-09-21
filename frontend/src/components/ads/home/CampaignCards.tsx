import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { CampaignTile } from "../patterns";
import { formatCurrency } from "@/lib/format";
import { listCampaigns, type CampaignCard } from "@/lib/adsApi";
import { STATUS_LABEL, STATUS_TONE } from "./status";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; campaigns: CampaignCard[] };

/** 一張卡一個 Campaign（F19-I02 版面骨架；每卡的目標／五分類條留給 I04）：沿用既有
 * `CampaignTile`，數字格式化與「未知≠0」規則都在呼叫端做好——元件本身不算數。自己打
 * `listCampaigns`，讀取失敗不拖累佇列卡或月預算卡（review repair (b)）。只列未結案的
 * Campaign（含既有平台活動）；已結案的透過 `AdsHomePage` 旁邊的「查看全部活動」連到清單頁
 * 找，不在這裡塞（review repair (h)）。 */
export function CampaignCards({ brandId }: { brandId: string }) {
  const navigate = useNavigate();
  const [state, setState] = useState<State>({ status: "loading" });
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    listCampaigns(brandId)
      .then((campaigns) => { if (!cancelled) setState({ status: "ready", campaigns }); })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" });
      });
    return () => { cancelled = true; };
  }, [brandId, reload]);

  if (state.status === "loading") {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 2xl:grid-cols-3">
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
    <div data-testid="campaign-grid" className="grid grid-cols-1 gap-4 sm:grid-cols-2 2xl:grid-cols-3">
      {campaigns.map((c) => {
        const spent = c.budget_progress.spent;
        const total = c.budget_progress.total;
        const pct = c.budget_progress.pct;
        const spendText = spent !== null ? formatCurrency(spent) : "還沒有花費資料";
        const budgetText = total !== null ? formatCurrency(total) : "尚未設定總預算";
        const percentText = pct !== null ? `${pct}%` : spent === null ? "未追蹤" : "未設定";
        return (
          <CampaignTile
            key={c.id}
            name={c.name}
            statusLabel={c.origin === "imported" ? "平台活動" : STATUS_LABEL[c.status]}
            statusTone={STATUS_TONE[c.status]}
            meta={`目標・${c.objective || "尚待確認"}`}
            spendText={c.origin === "imported" ? "進入活動查看花費" : spendText}
            budgetText={c.origin === "imported" ? "平台預算" : budgetText}
            percentText={c.origin === "imported" ? "未知" : percentText}
            percent={c.origin === "imported" ? 0 : (pct ?? 0)}
            judgment={c.judgment.text}
            judgmentDetail={c.judgment.detail}
            onClick={() => navigate(`/brands/${brandId}/ads/campaigns/${c.id}`)}
          />
        );
      })}
    </div>
  );
}
