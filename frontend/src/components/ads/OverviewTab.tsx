import { Check, Sparkles, Target, Wallet, BarChart2, Settings, Image as ImageIcon, TrendingUp, AlertTriangle, Clock } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { formatCurrency, formatCount, formatRoas } from "@/lib/format";
import { currentBudgetTotal, type CampaignDetail, type CampaignLabels, type SuccessMetric } from "@/lib/adsApi";
import { JudgmentBand, ActionTimeline, KpiStrip, type KpiCell, type TimelineItem } from "./patterns";
import { nextStep, type StepTarget, type WorkspaceTab } from "./nextStep";

const STAGE_LABELS = ["草稿", "策略", "投放結構", "素材", "投放中", "結案"] as const;

// F05-I12：後端一律回傳 `campaign.labels`；這裡的預設值只在舊測試 fixture 沒帶這個欄位時
// 頂上（同 `judgment` 選填的先例），跟 `app/ads/judgment.py::_CONVERSION_LABELS["purchase"]`
// 同一組字。
const DEFAULT_LABELS: CampaignLabels = { conversion: "購買", count: "購買數", cpa: "每次購買成本" };

function metricLabel(metric: SuccessMetric, labels: CampaignLabels): string {
  if (metric === "cpa") return labels.cpa;
  if (metric === "purchases") return labels.count;
  return "ROAS";
}

function formatTarget(metric: SuccessMetric, value: number): string {
  if (metric === "cpa") return formatCurrency(value);
  if (metric === "roas") return formatRoas(value);
  return formatCount(value);
}

const JUDGMENT_ICON = { good: TrendingUp, warn: AlertTriangle, neutral: Clock } as const;

export function OverviewTab({
  campaign: c,
  onChangeTab,
}: {
  campaign: CampaignDetail;
  onChangeTab: (target: StepTarget) => void;
}) {
  const labels = c.labels ?? DEFAULT_LABELS;
  const step = nextStep(c);
  const imported = c.origin === "imported";
  const runtime = c.context_json.runtime;
  const checkedAt = runtime && typeof runtime === "object" && "last_checked_at" in runtime && typeof runtime.last_checked_at === "string" ? runtime.last_checked_at : null;
  const roots = c.external_view?.entities.filter(e => e.native_kind === "campaign") ?? [];
  const root = roots.length === 1 ? roots[0] : undefined;
  const nativeStates = ["ACTIVE", "PAUSED", "ARCHIVED", "DELETED"];
  const nativeLabels = ["投放啟用", "已暫停", "已封存", "已刪除", "狀態未知"];
  const nativeIndex = nativeStates.indexOf(root?.native_status ?? "");
  const idx = imported ? (nativeIndex < 0 ? 4 : nativeIndex) : step.stageIndex;
  const stageLabels = imported ? nativeLabels : STAGE_LABELS;
  const t = currentBudgetTotal(c);
  const hasOutcome = (c.outcome.spend ?? 0) > 0 || (c.outcome.purchases ?? 0) > 0 || (c.outcome.revenue ?? 0) > 0;
  const pct = c.outcome.spend !== null && t.total !== null && t.total > 0 ? Math.round((c.outcome.spend / t.total) * 100) : null;

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
          ? `${metricLabel(c.success_metric, labels)} 目標 ${formatTarget(c.success_metric, c.success_target)}`
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
      value: hasOutcome && c.outcome.spend !== null ? formatCurrency(c.outcome.spend) : "還沒有成效資料",
      caption: hasOutcome
        ? t.total !== null
          ? `佔總預算 ${pct}%・平台回報`
          : "累計花費・平台回報"
        : "發布後才會有花費資料",
    },
  ];

  if (imported) {
    kpiCells[1] = {
      icon: Wallet, label: "平台預算",
      value: root?.budget_amount != null ? `${root.budget_amount.toLocaleString()} ${root.currency ?? "幣別未知"}` : "活動層級預算未知",
      caption: `${({ daily: "日預算", lifetime: "總額預算", unknown: "預算方式未知" } as Record<string, string>)[root?.budget_type ?? "unknown"] ?? root?.budget_type}・${root?.start_date ?? "開始日未知"} — ${root?.end_date ?? "結束日未知"}；各組預算見投放結構`,
    };
    kpiCells[2] = {
      icon: BarChart2, label: "已花費", value: c.external_view?.observations.length ? "查看成效分頁" : "尚無已讀回成效",
      caption: "依原生層級、幣別與歸因分開呈現；缺漏不代表 0。",
    };
  }

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
        {labels.conversion}、{labels.cpa}、ROAS 等成效數字在成效分頁——那裡分得出「未追蹤」與 0。
      </p>

      {imported ? (
        <JudgmentBand icon={Clock} sentence={`平台狀態：${nativeLabels[idx]}${root?.native_status ? `（${root.native_status}）` : ""}`} facts="顯示最近讀回的平台狀態；不代表內部策略、素材確認或上架流程已完成。" tone="neutral" />
      ) : c.judgment && (
        <JudgmentBand
          icon={JUDGMENT_ICON[judgmentTone]}
          sentence={c.judgment.text}
          facts={c.judgment.detail}
          tone={judgmentTone}
        />
      )}

      <section className="surface p-5 flex flex-wrap items-center justify-between gap-4" aria-label="檢討與持續追蹤">
        <div className="space-y-2"><h2 className="flex items-center gap-2 font-semibold"><Clock className="size-5 text-primary" />檢討與持續追蹤</h2>
          <p className="text-sm">查看單則廣告與商城證據，決定保留、觀察或準備新測試。</p>
          <p className="text-xs text-muted-foreground">{checkedAt ? `背景最近檢查：${new Date(checkedAt).toLocaleString("zh-TW")}。` : "尚無背景檢查紀錄，請先確認平台廣告對應與檢討條件。"}平台變更仍由你核准後手動操作。</p>
        </div>
        <Button onClick={() => onChangeTab("performance")}>前往廣告檢討 →</Button>
      </section>

      <div className="surface">
        <div className="surface-header">
          <h2>狀態時間軸</h2>{imported && <span className="text-xs text-muted-foreground">僅標示最近讀回狀態，非狀態變更歷程</span>}
        </div>
        <div className="surface-body flex items-center gap-0 pt-2">
          {stageLabels.map((label, i) => {
            const done = !imported && i < idx;
            const current = i === idx;
            return (
              <div key={label} className="relative flex-1 text-center">
                {i > 0 && (
                  <div
                    className={`absolute top-[9px] right-1/2 left-[-50%] h-0.5 ${
                      !imported && (done || current) ? "bg-primary" : "bg-border"
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
          <span className="text-sm">{step.sentence}</span>
          <Button size="sm" onClick={() => onChangeTab(step.target)}>
            {step.label}
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
