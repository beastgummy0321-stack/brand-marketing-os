import { Target, Wallet, BarChart2, TrendingUp, AlertTriangle, Clock } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { formatCurrency } from "@/lib/format";
import { formatInstant, useOrgClock } from "@/lib/orgClock";
import type { CampaignDetail, CampaignLabels } from "@/lib/adsApi";
import { JudgmentBand, ActionTimeline, KpiStrip, type KpiCell, type TimelineItem } from "./patterns";
import type { StepTarget } from "./nextStep";
import { syncNoteTone, type SyncNote } from "./detail/PeriodStatusRow";

// F05-I12：後端一律回傳 `campaign.labels`；這裡的預設值只在舊測試 fixture 沒帶這個欄位時
// 頂上（同 `judgment` 選填的先例），跟 `app/ads/judgment.py::_CONVERSION_LABELS["purchase"]`
// 同一組字。
const DEFAULT_LABELS: CampaignLabels = { conversion: "購買", count: "購買數", cpa: "每次購買成本" };

const JUDGMENT_ICON = { good: TrendingUp, warn: AlertTriangle, neutral: Clock } as const;

/** The imported campaign's platform read: 重新讀取平台 and its failure (the workspace owns the sync job). */
/** The imported campaign's platform read: 重新讀取平台, a request that failed, and the last read's served outcome (F49
 * Contract O, printed as served). */
export interface PlatformSync { onSync: () => void; syncing: boolean; error: string; note?: SyncNote | null }

/** v10 (F30-I07): the overview's 「進階：更多活動資訊」 fold — what the old overview showed that the v10 prototype does
 * not (the three-number strip, the backend's judgement sentence, 檢討與持續追蹤, 最近做了什麼, and for an imported
 * campaign its platform state, connections and 重新讀取平台). Nothing here is deleted, only folded (CLAUDE.md three
 * layers). The old stage timeline, next-step card and shortcut tiles are gone: the stage rail, the bottom bar and
 * the tab bar carry them now. */
export function OverviewTab({
  campaign: c,
  onChangeTab,
  platformSync,
}: {
  campaign: CampaignDetail;
  onChangeTab: (target: StepTarget) => void;
  platformSync?: PlatformSync;
}) {
  const { timezone } = useOrgClock();
  const labels = c.labels ?? DEFAULT_LABELS;
  const imported = c.origin === "imported";
  const runtime = c.context_json.runtime;
  const checkedAt = runtime && typeof runtime === "object" && "last_checked_at" in runtime && typeof runtime.last_checked_at === "string" ? runtime.last_checked_at : null;
  const roots = c.external_view?.entities.filter(e => e.native_kind === "campaign") ?? [];
  const root = roots.length === 1 ? roots[0] : undefined;
  const lastRead = Object.values(c.external_view?.sync ?? {}).map(s => s.last_success_at).filter((value): value is string => Boolean(value)).sort().at(-1);
  // F48 Contract M: the period total is the server's `budget_total` (after adoption it equals the chosen total); the
  // overview computes no money of its own.
  const total = c.budget_total;
  const hasOutcome = (c.outcome.spend ?? 0) > 0 || (c.outcome.purchases ?? 0) > 0 || (c.outcome.revenue ?? 0) > 0;

  const budgetCaption = total !== null
    ? "投放組每日預算 × 投放天數"
    : c.budget_planned !== null ? `已選 ${formatCurrency(c.budget_planned)}，展開投放組後算總預算` : "還沒選預算";

  const kpiCells: KpiCell[] = [
    {
      icon: Target,
      label: "Campaign 目標",
      value: c.objective,
      // F28-I01: the one cap, read-only here (set on the strategy tab).
      caption:
        c.cap.value !== null
          ? `每筆${labels.conversion}成本上限 ${c.cap.basis === "break_even" ? "暫用打平 " : ""}${formatCurrency(c.cap.value)}`
          : "未設定上限",
    },
    {
      icon: Wallet,
      label: "總預算",
      value: total !== null ? formatCurrency(total) : "尚未設定",
      caption: budgetCaption,
    },
    {
      icon: BarChart2,
      label: "已花費",
      value: hasOutcome && c.outcome.spend !== null ? formatCurrency(c.outcome.spend) : "還沒有成效資料",
      caption: hasOutcome
        ? "累計花費・平台回報"
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

  return (
    <div className="flex flex-col gap-4">
      <KpiStrip cells={kpiCells} />
      <p className="text-xs text-muted-foreground">
        {labels.conversion}、{labels.cpa}、ROAS 等成效數字在成效分頁——那裡分得出「未追蹤」與 0。
      </p>

      {imported ? (
        <>
          {/* F49 Contract L: the root's served delivery word (its platform adapter's status table), never the code. */}
          <JudgmentBand icon={Clock} sentence={`平台狀態：${root?.delivery_label ?? "平台狀態不明"}`} facts="顯示最近讀回的平台狀態；不代表內部策略、素材確認或上架流程已完成。" tone="neutral" />
          <div className="flex flex-wrap items-center gap-3">
            <p className="min-w-0 flex-1 text-xs text-muted-foreground">
              {c.external_view?.connections.map(connection => `${connection.platform === "meta" ? "Meta" : connection.platform} · ${connection.source_account} · ${connection.state === "connected" ? "已連線" : "連線中斷，保留歷史"}`).join("；")}
              {" · 最近成功："}{lastRead ? formatInstant(lastRead, timezone, "md_hm") : "尚未成功讀回"}
              {" · 活動設定不代表已實際投遞"}
              {Object.entries(c.external_view?.sync ?? {}).filter(([, value]) => value.error || value.error_code).map(([section, value]) => <span className="text-warning" key={section}> · {section}：{value.error ?? value.error_code}</span>)}
            </p>
            {platformSync && (
              <Button size="sm" variant="outline" disabled={platformSync.syncing} onClick={platformSync.onSync}>
                {platformSync.syncing ? "同步中…" : "重新讀取平台"}
              </Button>
            )}
          </div>
          {platformSync?.error && <p role="alert" className="text-sm text-destructive">{platformSync.error}</p>}
          {!platformSync?.error && platformSync?.note && !platformSync.syncing && (
            <p role="status" data-state={platformSync.note.state} className={`text-sm ${syncNoteTone(platformSync.note)}`}>{platformSync.note.text}</p>
          )}
        </>
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
          <p className="text-xs text-muted-foreground">{checkedAt ? `背景最近檢查：${formatInstant(checkedAt, timezone, "md_hm")}。` : "尚無背景檢查紀錄，請先確認平台廣告對應與檢討條件。"}平台變更仍由你核准後手動操作。</p>
        </div>
        <Button onClick={() => onChangeTab("perf")}>前往廣告檢討 →</Button>
      </section>

      <div className="surface">
        <div className="surface-header">
          <h2>最近做了什麼</h2>
        </div>
        <div className="surface-body">
          <ActionTimeline items={timelineItems} emptyText="這個 Campaign 還沒有異動紀錄。" />
        </div>
      </div>
    </div>
  );
}
