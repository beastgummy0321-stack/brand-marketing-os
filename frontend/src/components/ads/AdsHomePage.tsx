import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { formatCurrency } from "@/lib/format";
import { listCampaigns, type CampaignCard, type CampaignStatus } from "@/lib/adsApi";

const STATUS_LABEL: Record<CampaignStatus, string> = {
  draft: "草稿",
  ready: "待發布",
  live: "投放中",
  ended: "已結束",
  closed: "已結案",
};

const STATUS_TONE: Record<CampaignStatus, "secondary" | "default" | "outline"> = {
  draft: "secondary",
  ready: "outline",
  live: "default",
  ended: "outline",
  closed: "secondary",
};

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; campaigns: CampaignCard[] };

/** 投放中心首頁（F03-I13）：Campaign 清單，五分頁工作區的入口。工作佇列／建議卡／本月預算卡
 * 是 F04 的首頁工作（原型 `screen-overview.js` 有，這裡不做）——這支只做一張清單＋建立入口。 */
export function AdsHomePage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const navigate = useNavigate();

  function load() {
    setState({ status: "loading" });
    listCampaigns(brandId)
      .then((campaigns) => setState({ status: "ready", campaigns }))
      .catch((err: unknown) =>
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
        }),
      );
  }

  useEffect(load, [brandId]);

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />;
  } else if (state.campaigns.length === 0) {
    content = (
      <EmptyState
        title="這個品牌還沒有 Campaign"
        description="用一句話描述這次想達成的目標，讓行銷駕駛艙幫你規劃第一版策略。"
        actionLabel="建立 Campaign"
        onAction={() => navigate(`/brands/${brandId}/ads/new`)}
      />
    );
  } else {
    content = (
      <div className="table-surface">
        <table className="w-full text-left text-sm">
          <thead className="bg-muted text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">Campaign</th>
              <th className="px-3 py-2 font-medium">狀態</th>
              <th className="px-3 py-2 font-medium">投放期間</th>
              <th className="px-3 py-2 font-medium">目標</th>
              <th className="px-3 py-2 font-medium">預算（總額）</th>
              <th className="px-3 py-2 font-medium">花費（至今）</th>
            </tr>
          </thead>
          <tbody>
            {state.campaigns.map((c) => (
              <tr key={c.id} className="border-t border-border">
                <td className="px-3 py-2">
                  <button
                    type="button"
                    onClick={() => navigate(`/brands/${brandId}/ads/campaigns/${c.id}`)}
                    className="text-left font-medium text-primary hover:underline"
                  >
                    {c.name}
                  </button>
                </td>
                <td className="whitespace-nowrap px-3 py-2">
                  <Badge variant={STATUS_TONE[c.status]}>{STATUS_LABEL[c.status]}</Badge>
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-foreground">
                  {c.start_date && c.end_date ? `${c.start_date} ~ ${c.end_date}` : "未設定"}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-foreground">{c.objective}</td>
                <td className="whitespace-nowrap px-3 py-2 text-right numeric text-foreground">
                  {formatCurrency(c.budget_total ?? c.budget_planned)}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right numeric text-foreground">
                  {formatCurrency(c.outcome.spend)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="投放中心"
        description="Campaign 帶著目標與判斷依據，從策略到成效走完一整圈。"
        actions={
          <Button asChild>
            <Link to={`/brands/${brandId}/ads/new`}>建立 Campaign</Link>
          </Button>
        }
      />
      {content}
    </div>
  );
}
