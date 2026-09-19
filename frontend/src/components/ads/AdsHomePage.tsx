import { ExistingCampaignDialog } from "./ExistingCampaignDialog";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, type NavigateFunction } from "react-router-dom";
import { BarChart3, Plus } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { formatCurrency } from "@/lib/format";
import { getAdsHome, type AdsHome, type CampaignStatus } from "@/lib/adsApi";
import { fetchLaunchReadiness, type LaunchReadiness } from "@/lib/adsLaunchApi";
import { JudgmentBand, CampaignTile, ActionTimeline, ReadinessList } from "./patterns";
import { Disclosure } from "./patterns/Disclosure";
import { MonthlyBudgetPanel, currentBudgetMonth } from "./MonthlyBudgetPanel";
import { ChangeAttention } from "./ChangeAttention";
import { getOrgId } from "@/lib/auth";

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
type ReadinessLoadState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; readiness: LaunchReadiness };

function AdsHome({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [readinessState, setReadinessState] = useState<ReadinessLoadState>({ status: "loading" });
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
    setReadinessState({ status: "loading" });
    fetchLaunchReadiness(brandId)
      .then((readiness) => setReadinessState({ status: "ready", readiness }))
      .catch(() => setReadinessState({ status: "error" }));
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
    const campaigns = [...new Map([...home.campaigns, ...(home.imported_campaigns ?? [])].map(c => [c.id, c])).values()];
    content = (
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-1 items-start gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
          <div className="flex flex-col gap-4">
            <ChangeAttention brandId={brandId} />
            <div className="surface">
              <div className="surface-header">
                <h2>{home.imported_campaigns?.length ? "活動" : "進行中的活動"}</h2>
                <Link
                  to={`/brands/${brandId}/ads/campaigns`}
                  className="text-sm text-primary hover:underline"
                >
                  查看全部 →
                </Link>
              </div>
              <div className="surface-body">
                {campaigns.length === 0 ? (
                  <p className="py-6 text-center text-sm text-muted-foreground">
                    目前沒有進行中的活動。
                  </p>
                ) : (
                  <div
                    data-testid="campaign-grid"
                    className="grid grid-cols-1 gap-4 sm:grid-cols-2 2xl:grid-cols-3"
                  >
                    {campaigns.map((c) => {
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
                          statusLabel={c.origin === "imported" ? "平台活動" : STATUS_LABEL[c.status]}
                          statusTone={STATUS_TONE[c.status]}
                          meta={`目標・${c.objective || "尚待確認"}`}
                          spendText={c.origin === "imported" ? "進入活動查看花費" : spendText}
                          budgetText={c.origin === "imported" ? "平台預算" : budgetText}
                          percentText={c.origin === "imported" ? "未知" : percentText}
                          percent={c.origin === "imported" ? 0 : pct ?? 0}
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

          </div>
          <MonthlyBudgetPanel brandId={brandId} month={currentBudgetMonth()} />
        </div>
        <JudgmentBand icon={BarChart3} sentence={home.headline.text} facts={home.headline.facts} />
        <Disclosure label="查看新活動的建檔準備">
          <NewCampaignCard brandId={brandId} readinessState={readinessState} navigate={navigate} />
        </Disclosure>
          <Disclosure label="查看歷史操作紀錄">
            <p className="mb-3 text-xs text-muted-foreground">這些是過去的系統紀錄；舊有發布或同步文字不代表本次平台變更已核對。請以活動內的逐項核對結果為準。</p>
            <ActionTimeline items={home.actions.map((a) => ({
              id: `${a.campaign_id}-${a.time_text}-${a.title}`, time: a.time_text,
              title: a.title, detail: a.detail,
            }))} emptyText="還沒有任何紀錄。" />
          </Disclosure>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="投放中心"
        description="讓行銷駕駛艙幫你持續優化廣告投放。"
        actions={
          <div className="flex gap-2"><ExistingCampaignDialog brandId={brandId} /><Button asChild>
            <Link to={`/brands/${brandId}/ads/new`}>建立投放計畫</Link>
          </Button></div>
        }
      />
      {content}
    </div>
  );
}

export function AdsHomePage(props: { brandId: string }) {
  return <AdsHome key={`${getOrgId()}:${props.brandId}`} {...props} />;
}

/** 「建立新的 Campaign」卡（F05-I10）：綠燈畫面跟原本一模一樣，其餘顏色多印檢查表，
 * 句子與按鈕文字都來自 `fetchLaunchReadiness`，這支不重判斷、不擋路由。 */
function NewCampaignCard({
  brandId,
  readinessState,
  navigate,
}: {
  brandId: string;
  readinessState: ReadinessLoadState;
  navigate: NavigateFunction;
}) {
  const isBlocking =
    readinessState.status === "ready" && readinessState.readiness.state !== "green";

  if (!isBlocking) {
    return (
      <div className="surface flex items-center justify-between gap-4 border-dashed p-5">
        <div className="flex items-center gap-3">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-full bg-accent">
            <Plus className="size-5 text-primary" />
          </div>
          <div>
            <p className="text-[15px] font-semibold">建立投放計畫</p>
            <p className="text-sm text-muted-foreground">
              告訴行銷駕駛艙你的目標，它會幫你完成後續設定。
            </p>
          </div>
        </div>
        <Button variant="outline" onClick={() => navigate(`/brands/${brandId}/ads/new`)}>
          開始建立
        </Button>
      </div>
    );
  }

  const { readiness } = readinessState;
  const missing = readiness.items.filter((item) => item.state !== "green").length;

  return (
    <div className="surface flex flex-col gap-4 border-dashed p-5">
      <div className="flex items-center gap-3">
        <div className="flex size-11 shrink-0 items-center justify-center rounded-full bg-accent">
          <Plus className="size-5 text-primary" />
        </div>
        <div>
          <p className="text-[15px] font-semibold">建立投放計畫</p>
          <p className="text-sm text-muted-foreground">
            還缺 {missing} 項，補齊之後系統才算得出預算與成效。
          </p>
        </div>
      </div>
      <ReadinessList readiness={readiness} />
      <div className="flex gap-3">
        <Button onClick={() => navigate(readiness.primary.href)}>{readiness.primary.label}</Button>
        {readiness.secondary && (
          <Button variant="outline" onClick={() => navigate(readiness.secondary?.href ?? "")}>
            {readiness.secondary.label}
          </Button>
        )}
      </div>
    </div>
  );
}
