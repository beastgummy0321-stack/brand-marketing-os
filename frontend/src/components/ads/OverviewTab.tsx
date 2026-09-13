import { Check, Sparkles, Target, Wallet, BarChart2, Settings, Image as ImageIcon, TrendingUp, AlertTriangle, Clock } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { formatCurrency, formatCount, formatRoas } from "@/lib/format";
import { currentBudgetTotal, type CampaignDetail, type SuccessMetric } from "@/lib/adsApi";
import { JudgmentBand, ReservedSlotCard, DecisionCard, ActionTimeline, KpiStrip, type KpiCell, type TimelineItem } from "./patterns";

const STAGE_LABELS = ["草稿", "策略", "投放結構", "素材", "投放中", "結案"] as const;
type WorkspaceTab = "overview" | "strategy" | "structure" | "assets" | "performance";

const METRIC_LABEL: Record<SuccessMetric, string> = {
  cpa: "CPA",
  roas: "ROAS",
  purchases: "購買數",
};

function formatTarget(metric: SuccessMetric, value: number): string {
  if (metric === "cpa") return formatCurrency(value);
  if (metric === "roas") return formatRoas(value);
  return formatCount(value);
}

/** 依「backend state」推出目前走到哪一階段：每個條件只會把 idx 往前推，不回退——
 * 沿著 草稿→策略→投放結構→素材→投放中→結案 的既定順序。 */
function currentStageIndex(c: CampaignDetail): number {
  let idx = 0;
  if (c.budget_basis_json.strategy) idx = 1;
  if (c.groups.length > 0) idx = 2;
  if (c.asset_readiness.total > 0 && c.asset_readiness.ready_count >= c.asset_readiness.total) idx = 3;
  if (c.status === "live" || c.status === "ended") idx = 4;
  if (c.status === "closed") idx = 5;
  return idx;
}

function nextActionFor(c: CampaignDetail, idx: number): { text: string; tab: WorkspaceTab; label: string } {
  if (idx === 5) return { text: "Campaign 已結案，學習已寫入品牌智庫。", tab: "performance", label: "查看成效紀錄" };
  if (idx === 4) {
    return c.status === "ended"
      ? { text: "投放已結束，7 天後自動結案，也可以提前手動結案。", tab: "performance", label: "查看最終成效" }
      : { text: "查看成效與投放狀況。", tab: "performance", label: "查看成效" };
  }
  if (idx === 3) return { text: "素材已就位，接下來完成發布前的檢查與發布。", tab: "structure", label: "前往投放結構" };
  if (idx === 2) return { text: "投放結構已建立，交棒素材或勾選素材已就位。", tab: "assets", label: "前往素材" };
  return { text: "先確認推薦策略與預算情境。", tab: "strategy", label: "前往策略" };
}

const JUDGMENT_ICON = { good: TrendingUp, warn: AlertTriangle, neutral: Clock } as const;

export function OverviewTab({
  campaign: c,
  onChangeTab,
}: {
  campaign: CampaignDetail;
  onChangeTab: (tab: WorkspaceTab) => void;
}) {
  const idx = currentStageIndex(c);
  const next = nextActionFor(c, idx);
  const t = currentBudgetTotal(c);
  const hasOutcome = c.outcome.spend > 0 || c.outcome.purchases > 0 || c.outcome.revenue > 0;
  const pct = t.total !== null && t.total > 0 ? Math.round((c.outcome.spend / t.total) * 100) : null;

  const budgetCaption =
    (t.total !== null ? `日預算 ${formatCurrency(t.dailySum)}／天 × ${t.days} 天` : "還沒設定投放起訖日") +
    (c.budget_planned !== null ? `・採用情境 ${formatCurrency(c.budget_planned)}` : "");

  const kpiCells: KpiCell[] = [
    {
      icon: Target,
      label: "Campaign 目標",
      value: c.objective,
      caption:
        c.success_target !== null
          ? `${METRIC_LABEL[c.success_metric]} 目標 ${formatTarget(c.success_metric, c.success_target)}`
          : "未設定成功條件",
    },
    {
      icon: Wallet,
      label: "總預算",
      value: t.total !== null ? formatCurrency(t.total) : "尚未設定",
      caption: budgetCaption,
    },
    {
      icon: BarChart2,
      label: "已花費",
      value: hasOutcome ? formatCurrency(c.outcome.spend) : "還沒有成效資料",
      caption: hasOutcome
        ? t.total !== null
          ? `佔總預算 ${pct}%・平台回報`
          : "累計花費・平台回報"
        : "發布後才會有花費資料",
    },
  ];

  const judgmentTone = c.judgment?.tone ?? "neutral";
  const timelineItems: TimelineItem[] = (c.action_lines ?? []).map((a, i) => ({
    id: `${a.campaign_id}_${i}`,
    time: a.time_text,
    title: a.title,
    detail: a.detail,
  }));

  const shortcuts: { icon: typeof BarChart2; title: string; detail: string; tab: WorkspaceTab }[] = [
    { icon: BarChart2, title: "查看成效", detail: "瀏覽關鍵指標與走勢圖", tab: "performance" },
    { icon: Settings, title: "查看投放設定", detail: "受眾、預算、排程等設定", tab: "structure" },
    { icon: ImageIcon, title: "查看素材", detail: "所有素材與表現數據", tab: "assets" },
    { icon: Sparkles, title: "查看策略", detail: "推薦策略與預算情境", tab: "strategy" },
  ];

  return (
    <div className="flex flex-col gap-4">
      <KpiStrip cells={kpiCells} />
      <p className="text-xs text-muted-foreground">
        購買、CPA、ROAS 等成效數字在成效分頁——那裡分得出「未追蹤」與 0。
      </p>

      {c.judgment && (
        <JudgmentBand
          icon={JUDGMENT_ICON[judgmentTone]}
          sentence={c.judgment.text}
          facts={c.judgment.detail}
          tone={judgmentTone}
        />
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <ReservedSlotCard
            title="行銷駕駛艙為你執行中"
            description="接上自動執行之後，這裡會列出系統正在做的事與下一步；現在所有調整都由你確認後才發生。"
            tag="自動執行接上後開放"
          />
        </div>
        <DecisionCard items={[]} />
      </div>

      <div className="surface">
        <div className="surface-header">
          <h2>狀態時間軸</h2>
        </div>
        <div className="surface-body flex items-center gap-0 pt-2">
          {STAGE_LABELS.map((label, i) => {
            const done = i < idx;
            const current = i === idx;
            return (
              <div key={label} className="relative flex-1 text-center">
                {i > 0 && (
                  <div
                    className={`absolute top-[9px] right-1/2 left-[-50%] h-0.5 ${
                      done || current ? "bg-primary" : "bg-border"
                    }`}
                  />
                )}
                <div
                  className={`relative z-10 mx-auto mb-1.5 flex size-[18px] items-center justify-center rounded-full text-primary-foreground ${
                    done ? "bg-success" : current ? "bg-primary" : "bg-border"
                  }`}
                >
                  {done && <Check size={11} />}
                </div>
                <div className={`text-sm ${current ? "font-semibold" : ""}`}>{label}</div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="surface">
        <div className="surface-header">
          <h2 className="flex items-center gap-1.5">
            <Sparkles size={15} /> 下一步
          </h2>
        </div>
        <div className="surface-body flex items-center justify-between gap-4">
          <span className="text-sm">{next.text}</span>
          <Button variant="outline" size="sm" onClick={() => onChangeTab(next.tab)}>
            {next.label}
          </Button>
        </div>
      </div>

      <div className="surface">
        <div className="surface-header">
          <h2>最近做了什麼</h2>
        </div>
        <div className="surface-body">
          <ActionTimeline items={timelineItems} emptyText="這個 Campaign 還沒有異動紀錄。" />
        </div>
      </div>

      <div>
        <h2 className="mb-1 text-base font-semibold">更多 Campaign 資訊</h2>
        <p className="mb-3 text-sm text-muted-foreground">查看詳細數據與設定，隨時掌握投放進度。</p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {shortcuts.map((s) => {
            const Icon = s.icon;
            return (
              <button
                key={s.title}
                type="button"
                onClick={() => onChangeTab(s.tab)}
                className="surface flex items-center gap-3 p-4 text-left transition-colors hover:bg-accent/60"
              >
                <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent">
                  <Icon className="size-4 text-primary" />
                </div>
                <div className="flex-1">
                  <p className="text-sm font-semibold">{s.title}</p>
                  <p className="text-xs text-muted-foreground">{s.detail}</p>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
