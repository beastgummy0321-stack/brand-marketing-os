import { useState } from "react";
import type { EChartsOption } from "echarts";
import { Link } from "react-router-dom";
import { StatusLight } from "@/components/layout/StatusLight";
import { formatCount, formatCurrency, formatPercent, formatRelativeHours, formatRoas } from "@/lib/format";
import { triggerImmediateSync } from "@/lib/api";
import type { DashboardPerformanceView } from "@/lib/pinnedViewsApi";
import { useEchart } from "@/lib/useEchart";
import { READING_STATUS_LABELS } from "@/lib/warroomApi";

const READING_TONE: Record<string, string> = {
  scale_candidate: "bg-success/10 text-success",
  pause_candidate: "bg-danger/10 text-danger",
};

const HEALTH_LIGHT_KEYS = ["spend_rate", "cpa", "roas", "fatigue"] as const;

const WEEKLY_BURN_STATUS_LABELS: Record<string, string> = {
  normal: "正常",
  overspend: "燒太快",
  underspend: "花不完",
};

/** 這個品牌完全沒有檔期（S3P.13）：4 個真實視圖統一顯示區塊內空狀態。 */
export function NoCycleContent({ brandId }: { brandId: string }) {
  return (
    <div className="flex flex-col items-center gap-3 py-6 text-center">
      <p className="text-sm text-muted-foreground">這個品牌還沒開過廣告檔期。開一期廣告，這裡就會顯示成效。</p>
      <Link to={`/brands/${brandId}/campaigns/new`} className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90">
        開新檔期
      </Link>
    </div>
  );
}

/** 依釘選視圖種類畫對應內容（S3P.5-12）。`view` 為 `null` 由呼叫端另外走 `NoCycleContent`
 * （貼文留位視圖除外，那個永遠有值，見 `mocks/pinnedViewsData.ts buildPerformanceView()`）。 */
export function PinnedViewContent({ brandId, view, onRefresh }: { brandId: string; view: DashboardPerformanceView; onRefresh?: () => void }) {
  if (view.kind === "post_placeholder") return <PostPlaceholderContent />;
  if (view.kind === "ad_overview") return <AdOverviewContent brandId={brandId} view={view} onRefresh={onRefresh} />;
  if (view.kind === "weekly_burn") return <WeeklyBurnContent view={view} />;
  if (view.kind === "attribution") return <AttributionContent view={view} />;
  return <HealthLightsContent view={view} />;
}

/** S3P.7：貼文（短影音）成效——固定留位空態，任何品牌任何時候都顯示這個文案。 */
function PostPlaceholderContent() {
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border bg-muted/40 py-10 text-center">
      <p className="text-sm text-muted-foreground">
        這個功能還沒開通——之後接上 IG／TikTok 的貼文成效資料，會顯示在這裡。
      </p>
    </div>
  );
}

/** S3P.5-6：廣告總覽——這期曝光／點擊／花費／轉換／營收＋KPI＋判讀結論徽章，下方連結
 * 「看這期完整作戰室」（S8.0b 既有入口）／「查歷史檔期」。 */
function AdOverviewContent({ brandId, view, onRefresh }: { brandId: string; view: Extract<DashboardPerformanceView, { kind: "ad_overview" }>; onRefresh?: () => void }) {
  const { summary, reading_status } = view;
  const [syncing, setSyncing] = useState(false);
  const [syncAt, setSyncAt] = useState<string | null>(view.last_synced_at ?? null);
  const [syncError, setSyncError] = useState<string | null>(null);

  async function updateNow() {
    setSyncing(true);
    setSyncError(null);
    try {
      const result = await triggerImmediateSync(brandId);
      setSyncAt(result.updated_at);
      onRefresh?.();
    } catch (err) {
      setSyncError(err instanceof Error ? err.message : "更新失敗，請稍後再試。");
    } finally {
      setSyncing(false);
    }
  }
  const statusLabel = reading_status ? READING_STATUS_LABELS[reading_status] : null;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-foreground">廣告總覽</p>
          <p className="text-xs text-muted-foreground">{syncAt ? `更新於 ${formatRelativeHours(syncAt)}` : "尚未更新"}</p>
        </div>
        <button type="button" onClick={() => void updateNow()} disabled={syncing} className="rounded-md border border-primary px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-50">
          {syncing ? "更新中…" : "立刻更新"}
        </button>
      </div>
      {syncError && <p className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">{syncError}</p>}
      <div className="grid grid-cols-3 gap-3 sm:grid-cols-5">
        <Stat label="曝光" value={formatCount(summary.impressions)} />
        <Stat label="點擊" value={formatCount(summary.clicks)} />
        <Stat label="花費" value={formatCurrency(summary.spend)} />
        <Stat label="轉換" value={formatCount(summary.conversions)} />
        <Stat label="營收" value={formatCurrency(summary.revenue)} />
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="CTR" value={summary.kpis.ctr !== null ? formatPercent(summary.kpis.ctr) : "資料不足"} />
        <Stat label="CPC" value={summary.kpis.cpc !== null ? formatCurrency(summary.kpis.cpc) : "資料不足"} />
        <Stat label="CPA" value={summary.kpis.cpa !== null ? formatCurrency(summary.kpis.cpa) : "資料不足"} />
        <Stat label="ROAS" value={summary.kpis.roas !== null ? formatRoas(summary.kpis.roas) : "資料不足"} />
      </div>
      {statusLabel ? (
        <span className={`inline-flex w-fit items-center rounded-full px-2.5 py-1 text-xs font-medium ${READING_TONE[reading_status ?? ""] ?? "bg-muted text-muted-foreground"}`}>
          {statusLabel}
        </span>
      ) : (
        <p className="text-xs text-muted-foreground">這期還沒有判讀結論。</p>
      )}
      <div className="flex flex-wrap gap-3 border-t border-border pt-3 text-sm">
        <Link to={`/brands/${brandId}/campaigns/${view.cycle_id}`} className="font-medium text-primary hover:underline">
          看這期完整作戰室
        </Link>
        <Link to={`/brands/${brandId}/campaigns`} className="text-muted-foreground hover:underline">
          查歷史檔期
        </Link>
      </div>
    </div>
  );
}

/** S3P.8-9：本週燒錢與進度——時間進度 vs 預算進度對照＋狀態文字＋剩餘天數。 */
function WeeklyBurnContent({ view }: { view: Extract<DashboardPerformanceView, { kind: "weekly_burn" }> }) {
  if (view.status === "insufficient_sample" || view.time_progress === null || view.budget_progress === null) {
    return <p className="py-6 text-center text-sm text-muted-foreground">這期才剛開始，還看不出燒錢速度。</p>;
  }
  const timePct = Math.round(view.time_progress * 100);
  const budgetPct = Math.round(view.budget_progress * 100);
  return (
    <div className="flex flex-col gap-3">
      <ProgressBar label="時間進度" pct={timePct} colorClassName="bg-muted-foreground" />
      <ProgressBar label="預算進度" pct={budgetPct} colorClassName={view.status === "overspend" ? "bg-danger" : view.status === "underspend" ? "bg-warning" : "bg-success"} />
      <p className="text-sm text-foreground">
        已經過 {timePct}% 天數，花了 {budgetPct}% 預算——
        <span className="font-medium">{WEEKLY_BURN_STATUS_LABELS[view.status]}</span>
        ・剩餘 {view.days_left} 天
      </p>
    </div>
  );
}

function ProgressBar({ label, pct, colorClassName }: { label: string; pct: number; colorClassName: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-16 shrink-0 text-xs text-muted-foreground">{label}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
        <div className={`h-full rounded-full ${colorClassName}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
      <span className="w-10 shrink-0 text-right text-xs tabular-nums text-foreground">{pct}%</span>
    </div>
  );
}

/** S3P.10-11：訂單歸因——環形圖（毛單／淨單／排除／自然單）＋下方四個數字明細，完全沒有
 * 訂單資料時環形圖位置顯示空狀態文字。 */
function AttributionContent({ view }: { view: Extract<DashboardPerformanceView, { kind: "attribution" }> }) {
  const total = view.gross.count + view.net.count + view.excluded.count + view.natural.count;
  const option: EChartsOption = {
    tooltip: { trigger: "item" },
    legend: { bottom: 0 },
    series: [
      {
        type: "pie",
        radius: ["40%", "68%"],
        avoidLabelOverlap: true,
        label: { formatter: "{b}\n{d}%" },
        data: [
          { name: "毛單", value: view.gross.count },
          { name: "淨單", value: view.net.count },
          { name: "排除", value: view.excluded.count },
          { name: "自然單", value: view.natural.count },
        ],
      },
    ],
  };
  const ref = useEchart(option);

  if (total === 0) {
    return <p className="py-6 text-center text-sm text-muted-foreground">這期還沒有收到訂單歸因資料。</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      <div ref={ref} className="h-56 w-full" />
      <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        {([
          ["毛單", view.gross],
          ["淨單", view.net],
          ["排除", view.excluded],
          ["自然單", view.natural],
        ] as const).map(([label, cat]) => (
          <div key={label}>
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="text-foreground">{cat.count} 筆・{formatCurrency(cat.net_revenue)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** S3P.12：檔期健康燈號——四顆大燈號，全綠收合成一行，異常才展開數字＋白話說明（跟 S8R.20
 * 成效區資料源共用同一份 `health_lights.compute()`，這裡是駕駛艙獨立畫的版本，不 import
 * `components/warroom/`——模組化鐵則「跨 feature 只准 import components/layout 與 lib」）。 */
function HealthLightsContent({ view }: { view: Extract<DashboardPerformanceView, { kind: "health_lights" }> }) {
  const entries = HEALTH_LIGHT_KEYS.map((key) => ({ key, light: view[key] }));
  const allGreen = entries.every((e) => e.light.status === "green");

  if (allGreen) {
    return <p className="rounded-md bg-success/10 px-3 py-2 text-sm font-medium text-success">這期看起來一切正常</p>;
  }

  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
      {entries.map(({ key, light }) => (
        <div key={key} className="flex flex-col gap-1">
          <StatusLight status={light.status} label={light.label} />
          {light.status !== "green" && <p className="text-xs text-muted-foreground">{light.note}</p>}
        </div>
      ))}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border p-3 text-center">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-base font-semibold text-foreground">{value}</p>
    </div>
  );
}
