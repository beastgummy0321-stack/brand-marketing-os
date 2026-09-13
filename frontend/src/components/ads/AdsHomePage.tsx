import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { BarChart3, Plus } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { formatCurrency } from "@/lib/format";
import { getAdsHome, type AdsHome, type CampaignStatus } from "@/lib/adsApi";
import { JudgmentBand, DecisionCard, CampaignTile, ActionTimeline, ReservedSlotCard } from "./patterns";

export const STATUS_LABEL: Record<CampaignStatus, string> = {
  draft: "草稿",
  ready: "待發布",
  live: "投放中",
  ended: "已結束",
  closed: "已結案",
};

export const STATUS_TONE: Record<CampaignStatus, "secondary" | "default" | "outline"> = {
  draft: "secondary",
  ready: "outline",
  live: "default",
  ended: "outline",
  closed: "secondary",
};

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; home: AdsHome };

/** 投放中心首頁（F04-I09）：四塊判斷（整體判斷／需要你決定／進行中的 Campaign／最近做了什麼），
 * 照 `docs/design/ads/01-home.png`。所有判斷句與數字都來自 `getAdsHome`——這支不算數、不重拼。 */
export function AdsHomePage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const navigate = useNavigate();

  function load() {
    setState({ status: "loading" });
    getAdsHome(brandId)
      .then((home) => setState({ status: "ready", home }))
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
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />;
  } else {
    const { home } = state;
    content = (
      <div className="flex flex-col gap-4">
        <JudgmentBand icon={BarChart3} sentence={home.headline.text} facts={home.headline.facts} />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="flex flex-col gap-4 lg:col-span-2">
            <DecisionCard items={[]} />

            <div className="surface">
              <div className="surface-header">
                <h2>進行中的 Campaign</h2>
                <Link
                  to={`/brands/${brandId}/ads/campaigns`}
                  className="text-sm text-primary hover:underline"
                >
                  查看全部 →
                </Link>
              </div>
              <div className="surface-body">
                {home.campaigns.length === 0 ? (
                  <p className="py-6 text-center text-sm text-muted-foreground">
                    目前沒有進行中的 Campaign。
                  </p>
                ) : (
                  <div
                    data-testid="campaign-grid"
                    className="grid grid-cols-1 gap-4 sm:grid-cols-2 2xl:grid-cols-3"
                  >
                    {home.campaigns.map((c) => {
                      const spent = c.budget_progress.spent;
                      const total = c.budget_progress.total;
                      const pct = c.budget_progress.pct;
                      const spendText = spent !== null ? formatCurrency(spent) : "還沒有花費資料";
                      const budgetText = total !== null ? formatCurrency(total) : "尚未設定總預算";
                      const percentText =
                        pct !== null ? `${pct}%` : spent === null ? "未追蹤" : "未設定";
                      return (
                        <CampaignTile
                          key={c.id}
                          name={c.name}
                          statusLabel={STATUS_LABEL[c.status]}
                          statusTone={STATUS_TONE[c.status]}
                          meta={`目標・${c.objective}`}
                          spendText={spendText}
                          budgetText={budgetText}
                          percentText={percentText}
                          percent={pct ?? 0}
                          judgment={c.judgment.text}
                          judgmentDetail={c.judgment.detail}
                          onClick={() => navigate(`/brands/${brandId}/ads/campaigns/${c.id}`)}
                        />
                      );
                    })}
                  </div>
                )}
              </div>
            </div>

            <div className="surface flex items-center justify-between gap-4 border-dashed p-5">
              <div className="flex items-center gap-3">
                <div className="flex size-11 shrink-0 items-center justify-center rounded-full bg-accent">
                  <Plus className="size-5 text-primary" />
                </div>
                <div>
                  <p className="text-[15px] font-semibold">建立新的 Campaign</p>
                  <p className="text-sm text-muted-foreground">
                    告訴行銷駕駛艙你的目標，它會幫你完成後續設定。
                  </p>
                </div>
              </div>
              <Button variant="outline" onClick={() => navigate(`/brands/${brandId}/ads/new`)}>
                開始建立
              </Button>
            </div>
          </div>

          <div className="flex flex-col gap-4">
            <div className="surface">
              <div className="surface-header">
                <h2>行銷駕駛艙最近做了什麼</h2>
              </div>
              <div className="surface-body">
                <ActionTimeline
                  items={home.actions.map((a) => ({
                    id: `${a.campaign_id}-${a.time_text}-${a.title}`,
                    time: a.time_text,
                    title: a.title,
                    detail: a.detail,
                  }))}
                  emptyText="還沒有任何紀錄。"
                />
              </div>
            </div>

            <ReservedSlotCard
              title="行銷駕駛艙為你執行中"
              description="接上自動執行之後，這裡會列出系統自己做掉的調整。"
              tag="自動執行接上後開放"
            />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="投放中心"
        description="讓行銷駕駛艙幫你持續優化廣告投放。"
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
