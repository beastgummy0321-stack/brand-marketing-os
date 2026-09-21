import { useNavigate } from "react-router-dom";
import { EmptyState } from "@/components/layout/EmptyState";
import { CampaignTile } from "../patterns";
import { formatCurrency } from "@/lib/format";
import type { CampaignCard } from "@/lib/adsApi";
import { STATUS_LABEL, STATUS_TONE } from "./status";

/** 一張品牌卡牌一個 Campaign（F19-I02 版面骨架；每卡的目標／五分類條留給 I04）：沿用既有
 * `CampaignTile`，數字格式化與「未知≠0」規則都在呼叫端做好——元件本身不算數。 */
export function CampaignCards({ brandId, campaigns }: { brandId: string; campaigns: CampaignCard[] }) {
  const navigate = useNavigate();

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
