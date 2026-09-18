import { ExistingCampaignDialog } from "./ExistingCampaignDialog";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AlertTriangle, Clock, Megaphone, TrendingUp } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Badge } from "@/components/layout/ui/badge";
import { KpiStrip } from "./patterns";
import { STATUS_LABEL, STATUS_TONE } from "./AdsHomePage";
import { formatCurrency } from "@/lib/format";
import { listCampaigns, type CampaignCard, type CampaignStatus } from "@/lib/adsApi";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; campaigns: CampaignCard[] };

type FilterKey = "all" | "live" | "upcoming" | "ended" | "imported";

const UPCOMING_STATUSES: CampaignStatus[] = ["draft", "ready"];
const ENDED_STATUSES: CampaignStatus[] = ["ended", "closed"];

const JUDGMENT_ICON: Record<CampaignCard["judgment"]["tone"], typeof TrendingUp> = {
  good: TrendingUp,
  warn: AlertTriangle,
  neutral: Clock,
};

function formatDate(iso: string): string {
  const d = new Date(iso);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}/${mm}/${dd}`;
}

/** 所有 Campaign 清單（F04-I10），照 `docs/design/ads/02-campaign-list.png`。首頁（I09）只放
 * 進行中的卡片，這裡是可篩可搜的完整清單——§0 next goal「回頭找到任何一次投放」。
 *
 * 一次讀完 `listCampaigns`，篩選與搜尋都在瀏覽器端做：筆數是一個品牌的 Campaign 數，
 * 不會大到需要後端分頁，不必為了這一頁多開一支分頁 API。 */
export function AllCampaignsPage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [filter, setFilter] = useState<FilterKey>("all");
  const [search, setSearch] = useState("");
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

  const campaigns = state.status === "ready" ? state.campaigns : [];

  const counts = useMemo(
    () => ({
      all: campaigns.length,
      imported: campaigns.filter(c => c.origin === "imported").length,
      live: campaigns.filter((c) => c.origin !== "imported" && c.status === "live").length,
      upcoming: campaigns.filter((c) => c.origin !== "imported" && UPCOMING_STATUSES.includes(c.status)).length,
      ended: campaigns.filter((c) => c.origin !== "imported" && ENDED_STATUSES.includes(c.status)).length,
    }),
    [campaigns],
  );

  const visible = useMemo(() => {
    const byFilter = campaigns.filter((c) => {
      if (filter === "imported") return c.origin === "imported";
      if (filter !== "all" && c.origin === "imported") return false;
      if (filter === "live") return c.status === "live";
      if (filter === "upcoming") return UPCOMING_STATUSES.includes(c.status);
      if (filter === "ended") return ENDED_STATUSES.includes(c.status);
      return true;
    });
    const q = search.trim().toLowerCase();
    if (!q) return byFilter;
    return byFilter.filter((c) => c.name.toLowerCase().includes(q));
  }, [campaigns, filter, search]);

  let content: ReactNode;
  if (state.status === "loading") {
    content = (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  } else if (state.status === "error") {
    content = <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />;
  } else if (campaigns.length === 0) {
    content = (
      <EmptyState
        title="這個品牌還沒有 Campaign"
        description="建立第一個 Campaign，讓行銷駕駛艙幫你完成後續設定。"
        actionLabel="建立 Campaign"
        onAction={() => navigate(`/brands/${brandId}/ads/new`)}
      />
    );
  } else {
    content = (
      <div className="flex flex-col gap-4">
        <KpiStrip
          cells={[
            {
              icon: Megaphone,
              label: "進行中的 Campaign",
              value: String(counts.live),
              caption: "持續帶來曝光與轉換",
            },
            {
              icon: Clock,
              label: "即將上線的 Campaign",
              value: String(counts.upcoming),
              caption: "已排程，準備就緒",
            },
            {
              icon: TrendingUp,
              label: "已結束的 Campaign",
              value: String(counts.ended),
              caption: "可以回頭看結案判斷",
            },
          ]}
        />

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            {(
              [
                ["all", "全部", counts.all],
                ["imported", "既有平台活動", counts.imported],
                ["live", "進行中", counts.live],
                ["upcoming", "即將上線", counts.upcoming],
                ["ended", "已結束", counts.ended],
              ] as [FilterKey, string, number][]
            ).map(([key, label, count]) => (
              <Button
                key={key}
                type="button"
                size="sm"
                variant={filter === key ? "default" : "outline"}
                onClick={() => setFilter(key)}
              >
                {label} {count}
              </Button>
            ))}
          </div>
          <Input
            aria-label="搜尋 Campaign 名稱"
            placeholder="搜尋 Campaign 名稱"
            className="max-w-xs"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className="table-surface">
          <table className="w-full min-w-[1100px] text-left text-sm">
            <thead className="bg-muted text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Campaign 名稱</th>
                <th className="px-3 py-2 font-medium">狀態</th>
                <th className="px-3 py-2 font-medium">目標</th>
                <th className="px-3 py-2 font-medium">預算進度</th>
                <th className="px-3 py-2 font-medium">行銷駕駛艙一句判斷</th>
                <th className="whitespace-nowrap px-3 py-2 font-medium">建立時間</th>
                <th className="px-3 py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {visible.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-3 py-6 text-center text-sm text-muted-foreground">
                    沒有符合的 Campaign。
                  </td>
                </tr>
              ) : (
                visible.map((c) => {
                  const spent = c.budget_progress.spent;
                  const total = c.budget_progress.total;
                  const pct = c.budget_progress.pct;
                  const percent = Math.min(100, Math.max(0, pct ?? 0));
                  const percentText = pct !== null ? `${pct}%` : spent === null ? "未追蹤" : "未設定";
                  const amountText =
                    total === null
                      ? "尚未設定總預算"
                      : `${spent === null ? "還沒有花費資料" : formatCurrency(spent)} / ${formatCurrency(total)}`;
                  const JudgmentIcon = JUDGMENT_ICON[c.judgment.tone];
                  return (
                    <tr key={c.id} className="border-t border-border align-top">
                      <td className="px-3 py-2 font-medium">{c.name}{c.origin === "imported" && <span className="mt-1 block text-xs text-muted-foreground">既有平台活動</span>}</td>
                      <td className="px-3 py-2">
                        <Badge variant={STATUS_TONE[c.status]}>{c.origin === "imported" ? "平台狀態見原始資料" : STATUS_LABEL[c.status]}</Badge>
                      </td>
                      <td className="px-3 py-2">{c.objective}</td>
                      <td className="px-3 py-2">
                        <div className="flex flex-col gap-1">
                          <div className="flex items-baseline justify-between gap-2">
                            <span className="numeric text-xs">{amountText}</span>
                            <span className="numeric whitespace-nowrap text-xs text-muted-foreground">{percentText}</span>
                          </div>
                          <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                            <div
                              className="h-full rounded-full bg-primary"
                              style={{ width: `${percent}%` }}
                            />
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-start gap-1.5">
                          <JudgmentIcon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                          <div>
                            <p className="font-medium">{c.judgment.text}</p>
                            <p className="text-xs text-muted-foreground">{c.judgment.detail}</p>
                          </div>
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-3 py-2">
                        <p>{formatDate(c.created_at)}</p>
                      </td>
                      <td className="px-3 py-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => navigate(`/brands/${brandId}/ads/campaigns/${c.id}`)}
                        >
                          查看這次投放
                        </Button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="所有 Campaign"
        description="管理進行中與即將上線的投放，掌握整體成效與進度。"
        actions={
          <div className="flex gap-2"><ExistingCampaignDialog brandId={brandId} /><Button asChild>
            <Link to={`/brands/${brandId}/ads/new`}>建立 Campaign</Link>
          </Button></div>
        }
      />
      {content}
    </div>
  );
}
