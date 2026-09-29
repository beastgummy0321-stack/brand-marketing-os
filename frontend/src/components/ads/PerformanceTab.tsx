import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import type { EChartsOption } from "echarts";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { EmptyState } from "@/components/layout/EmptyState";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { cn } from "@/lib/utils";
import { useEchart } from "@/lib/useEchart";
import { useOrgClock } from "@/lib/orgClock";
import { CHART_COLOR_AXIS_TEXT, CHART_COLOR_REVENUE, CHART_COLOR_SPEND } from "@/lib/chartColors";
import { formatCount, formatCurrency, formatMetaRoas, formatPercent } from "@/lib/format";
import {
  getPerformance,
  type CampaignDetail,
  type CampaignLabels,
  type CampaignPerformance,
} from "@/lib/adsApi";
import { CloseCampaignDialog, DayChips, EARLY_CLOSE_SENTENCE, coveredRange, shortDay } from "./CloseCampaignDialog";
import { ExperimentPlan } from "./ExperimentPlan";
import { SimulationRecovery } from "./SimulationRecovery";
import { nextStep, NextStepButton, type StepTarget } from "./nextStep";
import { Disclosure } from "./patterns";
import { nativeMetricScopes, nativePerformance, type PerformanceView } from "./nativePerformance";

// F05-I12：後端一律回傳 `campaign.labels`；預設值只在舊測試 fixture 沒帶這個欄位時頂上
// （同 `OverviewTab.tsx`／`StrategyTab.tsx` 的先例）。
const DEFAULT_LABELS: CampaignLabels = { conversion: "購買", count: "購買數", cpa: "每次購買成本" };

/** F28-I01: new close-outs always judge cost per result (`"cpa"`) against the one cap; the other
 * two only remain on verdicts written before it, read back from `verdict_json.metric`. */
type VerdictMetric = "cpa" | "roas" | "purchases";

function metricLabel(metric: VerdictMetric, labels: CampaignLabels): string {
  if (metric === "cpa") return labels.cpa;
  if (metric === "purchases") return labels.count;
  return "ROAS";
}

/** Meta 來源的購買／CPA 這版永遠未追蹤（§0「Meta purchases are 未追蹤 for the whole of F03」）
 * ——跟一般數字的「累積中」（之後會有）是不同的事實，所以不能借 format.ts 現成的
 * formatCount／formatCurrency，那兩顆對 null 印「累積中」。 */
function fmtPurchases(v: number | null): string {
  return v === null ? "未追蹤" : formatCount(v);
}
function fmtCpa(v: number | null): string {
  return v === null ? "算不出來" : formatCurrency(v);
}
function fmtMetricValue(metric: VerdictMetric, v: number | null): string {
  if (metric === "cpa") return fmtCpa(v);
  if (metric === "purchases") return fmtPurchases(v);
  return formatMetaRoas(v);
}

interface AdsVerdictJson {
  metric?: VerdictMetric;
  target?: number | null;
  actual?: number | null;
  window?: { start: string | null; end: string | null };
  sample_bucket?: string;
  missing?: string;
  close_reason?: string;
}

/** 跟 `app/ads/learning.py::_sentence` 同一套公式，純算術重現（不是再猜一次）——結案回應
 * 只帶 `verdict`／`verdict_json`，沒有把寫進學習帳本的那句話回傳給前端，這裡用同樣的輸入
 * 組出同一句，不必為了這一句話多開一個讀學習帳本的端點。 */
function learningSentence(c: CampaignDetail): string | null {
  if (!c.verdict) return null;
  const vj = c.verdict_json as AdsVerdictJson;
  const sample = vj.sample_bucket ?? "";
  if (c.verdict === "看不出") {
    return `「${c.name}」這次投放${vj.missing ?? ""}（樣本${sample}），每筆成本上限暫時看不出達成與否。`;
  }
  const num = (v: number | null | undefined) => (typeof v === "number" ? Math.round(v * 100) / 100 : v);
  return `「${c.name}」每筆成本上限 ${num(vj.target) ?? "－"}，實際 ${num(vj.actual) ?? "－"}，結果${c.verdict}（樣本${sample}）。`;
}

const VERDICT_TONE: Record<string, "default" | "destructive" | "outline"> = {
  達成: "default",
  未達成: "destructive",
  看不出: "outline",
};

function buildTrendOption(daily: PerformanceView["daily"], native = false, currency: string | null = null): EChartsOption {
  const roasLabel = native ? "ROAS" : "ROAS（保守）";
  return {
    grid: { left: 56, right: 56, top: 28, bottom: 40 },
    legend: { bottom: 0, textStyle: { color: CHART_COLOR_AXIS_TEXT, fontSize: 12 } },
    xAxis: { type: "category", data: daily.map((d) => d.day), axisLabel: { fontSize: 10 } },
    yAxis: [
      {
        type: "value",
        name: "花費",
        axisLabel: { formatter: (v: number) => v.toLocaleString("zh-TW") },
        splitLine: { lineStyle: { opacity: 0.35 } },
      },
      { type: "value", name: roasLabel, splitLine: { show: false } },
    ],
    tooltip: {
      trigger: "axis",
      formatter: (params: unknown) => {
        const list = params as { axisValue: string; seriesName: string; value: number | null }[];
        const lines = [`<b>${list[0]?.axisValue ?? ""}</b>`];
        for (const p of list) {
          lines.push(
            `${p.seriesName}：${p.seriesName === "花費" ? (native ? nativeMoney(p.value, currency) : formatCurrency(p.value)) : formatMetaRoas(p.value)}`,
          );
        }
        return lines.join("<br/>");
      },
    },
    series: [
      {
        name: "花費",
        type: "bar",
        data: daily.map((d) => d.spend),
        itemStyle: { color: CHART_COLOR_SPEND, opacity: 0.75 },
      },
      {
        name: roasLabel,
        type: "line",
        yAxisIndex: 1,
        connectNulls: false,
        data: daily.map((d) => native ? d.roas : d.roas_conservative),
        itemStyle: { color: CHART_COLOR_REVENUE },
      },
    ],
  };
}

function nativeMoney(value: number | null, currency: string | null) {
  return value === null ? "未知" : `${value.toLocaleString("zh-TW", { maximumFractionDigits: 2 })} ${currency ?? "幣別未知"}`;
}
function TrendChart({ daily, native, currency }: { daily: PerformanceView["daily"]; native: boolean; currency: string | null }) {
  const option = useMemo(() => buildTrendOption(daily, native, currency), [daily, native, currency]);
  const ref = useEchart(option);
  return <div ref={ref} className="h-64 w-full" />;
}

function Kpi({ label, value, caption }: { label: string; value: string; caption: string }) {
  return (
    <article className="surface p-4">
      <div className="mb-2 text-xs text-muted-foreground">{label}</div>
      <p className="metric-number">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{caption}</p>
    </article>
  );
}

function hasSavedComparison(campaign: CampaignDetail) {
  const value = campaign.context_json.comparison_plan;
  return Boolean(value && typeof value === "object");
}

/** 成效 tab（F03-I16）：素材／策略／結構那幾頁是「編輯」，這頁是「唯讀＋兩個動作」
 * （重新讀取平台、立即結案）——所有數字只認 `getPerformance`（F37：平台同步表），絕不讀
 * `campaign_detail.outcome`（那是列表卡片的 SQL 小計，§0「Two total-derivers exist」）。
 * 重新讀取平台一律是工作區的 `onSync`（同一個 `POST …/sync` 工作，自建與既有活動都一樣）。 */
export function PerformanceTab({
  brandId,
  campaign: c,
  onCampaignChange,
  onChangeTab,
  onSync,
  syncing = false,
  syncError = "",
}: {
  brandId: string;
  campaign: CampaignDetail;
  onCampaignChange: (campaign: CampaignDetail) => void;
  onChangeTab: (target: StepTarget) => void;
  onSync?: () => void;
  syncing?: boolean;
  /** The workspace's last sync failure (job error); the close dialog's 重讀仍失敗 note shows it. */
  syncError?: string;
}) {
  const { scope: draftScope } = useWorkspace();
  const [searchParams] = useSearchParams();
  // F27-I22：`?ad=<entity_id>` 深連結（review／已關閉列都會帶這個參數）——捲到並高亮
  // 「廣告花費占比」那一列；比對不到就印一行「這則廣告沒有成效資料」，不是靜默失敗。
  const highlightAd = searchParams.get("ad");
  const imported = c.origin === "imported";
  const scopes = useMemo(() => nativeMetricScopes(c.external_view), [c.external_view]);
  const [scopeKey, setScopeKey] = useState<string>();
  const selectedScope = scopes.find(scope => scope.key === scopeKey) ?? (highlightAd ? scopes.find(scope => scope.metricScope === "ad") : undefined) ?? scopes[0];
  const nativeData = useMemo(() => nativePerformance(c.external_view, selectedScope?.key), [c.external_view, selectedScope?.key]);
  const published = c.status === "live" || c.status === "ended" || c.status === "closed";
  const labels = c.labels ?? DEFAULT_LABELS;
  const { today } = useOrgClock(); // F36-I09 (ruling G): org calendar, not the browser's

  const [state, setState] = useState<
    | { status: "loading" }
    | { status: "error"; message: string }
    | { status: "ready"; data: CampaignPerformance }
  >({ status: "loading" });
  const [comparisonRefresh, setComparisonRefresh] = useState(0);
  // F40-I06: the dialog itself is `CloseCampaignDialog` (shared with the 這期狀態列); mounted only while open.
  const [closeOpen, setCloseOpen] = useState(false);

  const load = useCallback(() => {
    if (!published || imported) return;
    setState({ status: "loading" });
    getPerformance(brandId, c.id)
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) =>
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取成效失敗。" }),
      );
  }, [brandId, c.id, published, imported]);

  useEffect(load, [load]);

  // The workspace's platform read ended (syncing true → false): reload the numbers and the opened
  // comparison (the open close dialog releases its own held 確認結案).
  const wasSyncing = useRef(syncing);
  useEffect(() => {
    if (wasSyncing.current && !syncing) {
      load();
      setComparisonRefresh((current) => current + 1);
    }
    wasSyncing.current = syncing;
  }, [syncing, load]);

  const comparison = imported ? <Disclosure label="成效比較"><p className="text-sm text-muted-foreground">{c.capabilities?.unavailable.comparison ?? "既有平台活動不支援內部成效比較。"}</p></Disclosure> : <ExperimentPlan key={`${draftScope}:${brandId}:${c.id}`} draftScope={draftScope} brandId={brandId} campaignId={c.id}
    hasSavedComparison={hasSavedComparison(c)} refreshToken={`${c.status}:${comparisonRefresh}`}
    onViewPlan={() => onChangeTab("structure")} />;
  const recovery = !imported && c.simulation_mode ? <Disclosure label="內部驗收工具（隔離模擬）">
    <SimulationRecovery key={c.id} brandId={brandId} campaign={c} onChanged={onCampaignChange} onSaved={() => {
      load();
      setComparisonRefresh((current) => current + 1);
    }} />
  </Disclosure> : null;

  if (!published && !imported) {
    return (
      <div className="flex flex-col gap-4">
        <EmptyState
          title="還沒有成效資料"
          description={`Campaign 上線後，這裡會顯示每日花費、${labels.conversion}與 ROAS 趨勢，以及結案時的判定。`}
        />
        <NextStepButton step={nextStep(c)} onChangeTab={onChangeTab} />
        {comparison}
        {recovery}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {imported ? (
        <PerformanceReady simulated={false} native data={nativeData} labels={labels} refreshing={syncing}
          onRefresh={() => onSync?.()} refreshDisabled={!onSync} currency={selectedScope?.currency ?? null}
          scopeCaption={`${selectedScope?.label ?? "尚無資料範圍"} · ${c.external_view?.window.start ?? "未知"} ～ ${c.external_view?.window.end ?? "未知"}`}
          scopeControl={scopes.length > 0 ? <label className="flex flex-col gap-1 text-sm">資料範圍<select className="input-field" value={selectedScope?.key} onChange={event => setScopeKey(event.target.value)}>{scopes.map(scope => <option key={scope.key} value={scope.key}>{scope.label}</option>)}</select></label> : null}
          highlightAd={highlightAd} />
      ) : state.status === "loading" ? (
        <div className="surface">
          <div className="surface-body py-10 text-center text-sm text-muted-foreground">讀取中…</div>
        </div>
      ) : state.status === "error" ? (
        <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />
      ) : (
        <PerformanceReady simulated={!!c.simulation_mode || c.external_id?.startsWith("sim_") === true}
          data={state.data} labels={labels} refreshing={syncing} onRefresh={() => onSync?.()} refreshDisabled={!onSync}
          highlightAd={highlightAd} />
      )}

      {(imported || c.status === "live" || c.status === "ended") && (
        <div className="surface">
          <div className="surface-header">
            <h2>結案</h2>
          </div>
          <div className="surface-body flex items-center justify-between gap-4">
            <span className="flex flex-col gap-1 text-sm text-muted-foreground">
              <span>
                {imported ? (c.capabilities?.unavailable.close ?? "既有平台活動不使用內部結案。") : c.status === "ended"
                  ? "投放已結束，待人工結案；可以現在手動結案。"
                  : EARLY_CLOSE_SENTENCE}
              </span>
              {!imported && c.status === "live" && c.end_date && c.end_date > today && (
                <span className="text-xs text-muted-foreground">
                  投放期間到 {c.end_date}，現在結案等於提前結束
                </span>
              )}
            </span>
            <Button disabled={imported} onClick={() => setCloseOpen(true)}>立即結案</Button>
          </div>
        </div>
      )}

      {!imported && c.status === "closed" && <VerdictCard brandId={brandId} campaign={c} />}

      {comparison}
      {recovery}

      {closeOpen && (
        <CloseCampaignDialog brandId={brandId} campaign={c} onClose={() => setCloseOpen(false)}
          onCampaignChange={onCampaignChange} onSync={onSync} syncing={syncing} syncError={syncError} />
      )}
    </div>
  );
}

function PerformanceReady({
  simulated,
  data,
  labels,
  refreshing,
  onRefresh,
  native = false,
  currency = null,
  scopeControl,
  scopeCaption,
  refreshDisabled = false,
  highlightAd = null,
}: {
  simulated: boolean;
  data: PerformanceView;
  labels: CampaignLabels;
  refreshing: boolean;
  onRefresh: () => void;
  native?: boolean;
  currency?: string | null;
  scopeControl?: React.ReactNode;
  scopeCaption?: string;
  refreshDisabled?: boolean;
  highlightAd?: string | null;
}) {
  const t = data.totals;
  const money = (value: number | null) => native ? nativeMoney(value, currency) : formatCurrency(value);
  const count = (value: number | null) => native && value === null ? "未知" : fmtPurchases(value);
  const cpa = (value: number | null) => native ? money(value) : fmtCpa(value);
  const percent = (value: number | null) => native && value === null ? "未知" : formatPercent(value);
  const roas = (value: number | null) => native && value === null ? "未知" : formatMetaRoas(value);
  const source = simulated ? "模擬回收" : "平台回報";
  const latestDay = data.daily[data.daily.length - 1]?.day ?? null;
  // F37 Contract P: the internal campaign's platform-read coverage (the native view has its own caption).
  const coverage = native ? null : data.coverage;
  const missingDays = coverage?.missing_days ?? [];
  const covered = coverage?.start && coverage.end ? coveredRange(coverage.start, coverage.end, missingDays) : null;
  const readStatus = !coverage
    ? latestDay ? `最新資料日 ${latestDay}` : "還沒有每日資料"
    : coverage.never_synced ? "還沒讀過平台資料"
    : covered ? `平台已讀到 ${shortDay(covered.first)} ～ ${shortDay(covered.last)}`
    : coverage.start ? "這段期間還沒讀到平台資料"
    : "還沒有完整的一天可讀";
  // F27-I22：`廣告花費占比` 那張表才有「這則廣告」的列——比對不到就是這次資料範圍裡沒有它
  // （不同資料範圍／幣別／歸因，或這則廣告根本沒有花費資料），不是程式錯誤，印一行誠實訊息。
  const matchedAd = highlightAd !== null ? data.ads.find((a) => a.ad_id === highlightAd) ?? null : null;
  const adNotFound = highlightAd !== null && matchedAd === null;
  const highlightRowRef = useRef<HTMLTableRowElement | null>(null);
  const scrolledToRef = useRef<string | null>(null);
  useEffect(() => {
    if (!matchedAd || scrolledToRef.current === matchedAd.ad_id) return;
    highlightRowRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    scrolledToRef.current = matchedAd.ad_id;
  }, [matchedAd]);
  const outcome = t.spend === null ? "尚無完整花費資料，暫時無法判讀成效。" : t.spend <= 0
    ? (native ? "已讀回花費為 0，暫時無法判讀 CPA 或 ROAS。" : "尚無花費資料，暫時無法判讀成效。")
    : t.purchases === null || t.revenue === null
      ? (native ? "已有花費資料；轉換或營收資料不完整，暫時不能判定 CPA 或 ROAS。" : "已有花費資料；轉換或營收未追蹤，暫時不能判定 CPA 或 ROAS。")
      : "已整理目前回收資料；請對照主要 KPI 與成功條件判讀。";
  return (
    <>
      <div className="surface">
        <div className="surface-header">
          <h2>目前成果</h2>
          <Button variant="outline" size="sm" onClick={onRefresh} disabled={refreshing || refreshDisabled}>
            <RefreshCw size={14} className={refreshing ? "animate-spin" : "hidden"} />
            {refreshing ? "讀取中…" : "重新讀取平台"}
          </Button>
        </div>
        <div className="surface-body flex flex-col gap-2">
          <p className="text-sm font-medium">{outcome}</p>
          {native && <p className="text-xs text-muted-foreground">{scopeCaption}。僅彙整已讀回資料，完整性未知。</p>}
          <p className="text-xs text-muted-foreground">資料狀態：{readStatus}；來源為{source}。</p>
          {missingDays.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-warning">
              有 {missingDays.length} 天還沒讀到平台資料：
              <DayChips days={missingDays.slice(0, 5)} />
              {missingDays.length > 5 && <span>…</span>}
              這幾天不算 0，按「重新讀取平台」補讀。
            </div>
          )}
          {(t.purchases === null || t.revenue === null) && <p className="text-xs text-warning">
            {native ? "轉換或營收未知時，CPA 與 ROAS 不能當成 0，也不能據此判定成效。" : "轉換或營收未追蹤時，CPA 與 ROAS 不能當成 0，也不能據此判定成效。"}
          </p>}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="花費" value={money(t.spend)} caption={`累計花費・${source}`} />
        <Kpi label={labels.count} value={count(t.purchases)} caption={`累計${labels.conversion}・${source}`} />
        <Kpi label="CPA" value={cpa(t.cpa)} caption={`花費 ÷ ${labels.conversion}`} />
        <Kpi label="ROAS" value={roas(native ? t.roas : t.roas_conservative)} caption={native ? "同一資料範圍營收 ÷ 花費" : `保守值・樂觀 ${formatMetaRoas(t.roas)}`} />
      </div>

      {adNotFound && <p className="text-sm text-muted-foreground">這則廣告沒有成效資料</p>}

      <Disclosure label="查看每日資料、次要指標與公式" defaultOpen={matchedAd !== null}>
        <div className="flex flex-col gap-4">
          {scopeControl}
          {native && <p className="text-xs text-muted-foreground">目前指標只計算所選層級、幣別與歸因；不同層級不相加。缺少資料顯示未知，不推算缺漏天數。</p>}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Kpi label="點擊率" value={percent(t.ctr)} caption="累計點擊 ÷ 曝光" />
            <Kpi label="曝光" value={native && t.impressions === null ? "未知" : formatCount(t.impressions)} caption={`累計曝光・${source}`} />
          </div>

      <div className="surface">
        <div className="surface-header">
          <h2>成效趨勢</h2>
        </div>
        <div className="surface-body flex flex-col gap-3">
          {data.daily.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">還沒有每日資料。</p>
          ) : (
            <TrendChart daily={data.daily} native={native} currency={currency} />
          )}
          <ul className="flex flex-col gap-1 text-xs text-muted-foreground">
            {(data.coverage?.expected ?? 0) > 0 && (
              <li>
                {data.coverage?.missing} 天沒讀到平台資料（期間共 {data.coverage?.expected} 天）
              </li>
            )}
            <li>{data.last_data_at ? `最新資料日：${data.daily[data.daily.length - 1]?.day ?? "－"}` : "還沒有資料"}</li>
          </ul>
        </div>
      </div>

      <div className="surface">
        <div className="surface-header"><h2>每日資料</h2></div>
        <div className="surface-body table-surface">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted text-muted-foreground"><tr>
              <th className="px-3 py-2 font-medium">日期</th><th className="px-3 py-2 font-medium">花費</th>
              <th className="px-3 py-2 font-medium">{labels.count}</th><th className="px-3 py-2 font-medium">CPA</th>
              <th className="px-3 py-2 font-medium">{native ? "ROAS" : "ROAS（保守／樂觀）"}</th>
            </tr></thead>
            <tbody>{data.daily.length ? data.daily.map((day) => <tr key={day.day} className="border-t border-border">
              <td className="px-3 py-2">{day.day}</td><td className="px-3 py-2">{money(day.spend)}</td>
              <td className="px-3 py-2">{count(day.purchases)}</td><td className="px-3 py-2">{cpa(day.cpa)}</td>
              <td className="px-3 py-2">{native ? roas(day.roas) : `${formatMetaRoas(day.roas_conservative)} ／ ${formatMetaRoas(day.roas)}`}</td>
            </tr>) : <tr><td colSpan={5} className="px-3 py-6 text-center text-muted-foreground">還沒有每日資料。</td></tr>}</tbody>
          </table>
        </div>
      </div>

      <div className="surface">
        <div className="surface-header">
          <h2>投放組成效</h2>
        </div>
        <div className="surface-body table-surface">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">投放組</th>
                <th className="px-3 py-2 font-medium">花費</th>
                <th className="px-3 py-2 font-medium">{labels.count}</th>
                <th className="px-3 py-2 font-medium">CPA</th>
                <th className="px-3 py-2 font-medium">{native ? "ROAS" : "ROAS（保守／樂觀）"}</th>
                <th className="px-3 py-2 font-medium">點擊率</th>
                <th className="px-3 py-2 font-medium">花費占比</th>
              </tr>
            </thead>
            <tbody>
              {data.groups.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-3 py-6 text-center text-muted-foreground">
                    還沒有投放組成效資料。
                  </td>
                </tr>
              ) : (
                data.groups.map((g) => (
                  <tr key={g.group_id} className="border-t border-border">
                    <td className="px-3 py-2">{g.name}</td>
                    <td className="px-3 py-2">{money(g.spend)}</td>
                    <td className="px-3 py-2">{count(g.purchases)}</td>
                    <td className="px-3 py-2">{cpa(g.cpa)}</td>
                    <td className="px-3 py-2">
                      {native ? roas(g.roas) : `${formatMetaRoas(g.roas_conservative)} ／ ${formatMetaRoas(g.roas)}`}
                    </td>
                    <td className="px-3 py-2">{percent(g.ctr)}</td>
                    <td className="px-3 py-2">{percent(g.spend_share)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="surface">
        <div className="surface-header">
          <h2>廣告花費占比</h2>
        </div>
        <div className="surface-body table-surface">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">廣告</th>
                <th className="px-3 py-2 font-medium">花費</th>
                <th className="px-3 py-2 font-medium">花費占比</th>
              </tr>
            </thead>
            <tbody>
              {data.ads.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-3 py-6 text-center text-muted-foreground">
                    還沒有廣告花費資料。
                  </td>
                </tr>
              ) : (
                data.ads.map((a) => (
                  <tr
                    key={a.ad_id}
                    ref={a.ad_id === highlightAd ? highlightRowRef : undefined}
                    data-testid={`ad-perf-row-${a.ad_id}`}
                    className={cn(
                      "border-t border-border",
                      a.ad_id === highlightAd && "bg-accent/60 ring-1 ring-inset ring-primary",
                    )}
                  >
                    <td className="px-3 py-2">{a.name}</td>
                    <td className="px-3 py-2">{money(a.spend)}</td>
                    <td className="px-3 py-2">{percent(a.spend_share)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
          <div className="rounded-md bg-muted p-3 text-xs text-muted-foreground">
            <p>{native ? "CPA＝花費 ÷ 轉換數；缺少資料時顯示「未知」。" : "CPA＝花費 ÷ 轉換數；沒有追蹤到轉換時顯示「算不出來」。"}</p>
            <p>{native ? "ROAS＝所選資料範圍的營收 ÷ 花費；任一筆營收未知時，不推算 ROAS。" : "ROAS 保守值用全部花費作分母；樂觀值只使用有追蹤營收的花費。兩者須一起看。"}</p>
            <p>{native ? "花費占比＝項目花費 ÷ 所選資料範圍總花費。投放組與廣告明細只顯示所選層級。" : "花費占比＝該投放組或廣告花費 ÷ Campaign 總花費。"}</p>
          </div>
        </div>
      </Disclosure>
    </>
  );
}

function VerdictCard({ brandId, campaign: c }: { brandId: string; campaign: CampaignDetail }) {
  const vj = c.verdict_json as AdsVerdictJson;
  const metric: VerdictMetric = vj.metric ?? "cpa";
  const verdict = c.verdict ?? "看不出";
  const sentence = learningSentence(c);
  return (
    <div className="surface">
      <div className="surface-header">
        <h2 className="flex items-center gap-2">
          結案判定
          <Badge variant={VERDICT_TONE[verdict] ?? "outline"}>{verdict}</Badge>
        </h2>
      </div>
      <div className="surface-body flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <div className="field-card">
            <div className="text-xs text-muted-foreground">判定指標</div>
            <div className="text-sm font-semibold">{metricLabel(metric, c.labels ?? DEFAULT_LABELS)}</div>
          </div>
          <div className="field-card">
            <div className="text-xs text-muted-foreground">上限</div>
            <div className="text-sm font-semibold">
              {vj.target == null ? "未設定" : fmtMetricValue(metric, vj.target)}
            </div>
          </div>
          <div className="field-card">
            <div className="text-xs text-muted-foreground">實際</div>
            <div className="text-sm font-semibold">{fmtMetricValue(metric, vj.actual ?? null)}</div>
          </div>
          <div className="field-card">
            <div className="text-xs text-muted-foreground">樣本</div>
            <div className="text-sm font-semibold">{vj.sample_bucket ?? "－"}</div>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          期間：{vj.window?.start ?? "－"} ~ {vj.window?.end ?? "－"}
        </p>
        {verdict === "看不出" && vj.missing && <p className="text-sm text-muted-foreground">{vj.missing}</p>}
        {sentence && (
          <div className="field-card">
            <div className="text-xs text-muted-foreground">學習</div>
            <p className="text-sm">{c.simulation_mode && "【隔離模擬，非市場實證】"}{sentence}</p>
            <Link to={`/brands/${brandId}/library`} className="text-xs text-primary hover:underline">
              查看品牌智庫 →
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
