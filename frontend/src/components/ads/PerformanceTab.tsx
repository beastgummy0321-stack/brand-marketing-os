import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import type { EChartsOption } from "echarts";
import { Button } from "@/components/layout/ui/button";
import { Badge } from "@/components/layout/ui/badge";
import { EmptyState } from "@/components/layout/EmptyState";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/layout/ui/dialog";
import { useEchart } from "@/lib/useEchart";
import { CHART_COLOR_AXIS_TEXT, CHART_COLOR_REVENUE, CHART_COLOR_SPEND } from "@/lib/chartColors";
import { formatCount, formatCurrency, formatMetaRoas, formatPercent } from "@/lib/format";
import {
  closeCampaign,
  getPerformance,
  ingestOutcome,
  type CampaignDetail,
  type CampaignPerformance,
  type SuccessMetric,
} from "@/lib/adsApi";

const METRIC_LABELS: Record<SuccessMetric, string> = { cpa: "CPA", roas: "ROAS", purchases: "購買數" };

/** Meta 來源的購買／CPA 這版永遠未追蹤（§0「Meta purchases are 未追蹤 for the whole of F03」）
 * ——跟一般數字的「累積中」（之後會有）是不同的事實，所以不能借 format.ts 現成的
 * formatCount／formatCurrency，那兩顆對 null 印「累積中」。 */
function fmtPurchases(v: number | null): string {
  return v === null ? "未追蹤" : formatCount(v);
}
function fmtCpa(v: number | null): string {
  return v === null ? "算不出來" : formatCurrency(v);
}
function fmtMetricValue(metric: SuccessMetric, v: number | null): string {
  if (metric === "cpa") return fmtCpa(v);
  if (metric === "purchases") return fmtPurchases(v);
  return formatMetaRoas(v);
}

interface AdsVerdictJson {
  metric?: SuccessMetric;
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
  const label = METRIC_LABELS[c.success_metric] ?? c.success_metric;
  const sample = vj.sample_bucket ?? "";
  if (c.verdict === "看不出") {
    return `「${c.name}」這次投放${vj.missing ?? ""}（樣本${sample}），${label} 目標暫時看不出達成與否。`;
  }
  const actual = typeof vj.actual === "number" ? Math.round(vj.actual * 100) / 100 : vj.actual;
  return `「${c.name}」${label} 目標 ${vj.target ?? "－"}，實際 ${actual ?? "－"}，結果${c.verdict}（樣本${sample}）。`;
}

/** F04-I23：結案卡與確認對話框共用同一句，`live` 時都要看到——只宣告一次，不抽成新元件。 */
const EARLY_CLOSE_SENTENCE = "提前結案會用到目前為止的成效判定，判定後這個 Campaign 不再更新成效";

const VERDICT_TONE: Record<string, "default" | "destructive" | "outline"> = {
  達成: "default",
  未達成: "destructive",
  看不出: "outline",
};

function buildTrendOption(daily: CampaignPerformance["daily"]): EChartsOption {
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
      { type: "value", name: "ROAS（保守）", splitLine: { show: false } },
    ],
    tooltip: {
      trigger: "axis",
      formatter: (params: unknown) => {
        const list = params as { axisValue: string; seriesName: string; value: number | null }[];
        const lines = [`<b>${list[0]?.axisValue ?? ""}</b>`];
        for (const p of list) {
          lines.push(
            `${p.seriesName}：${p.seriesName === "花費" ? formatCurrency(p.value) : formatMetaRoas(p.value)}`,
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
        name: "ROAS（保守）",
        type: "line",
        yAxisIndex: 1,
        connectNulls: false,
        data: daily.map((d) => d.roas_conservative),
        itemStyle: { color: CHART_COLOR_REVENUE },
      },
    ],
  };
}

function TrendChart({ daily }: { daily: CampaignPerformance["daily"] }) {
  const option = useMemo(() => buildTrendOption(daily), [daily]);
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

/** 成效 tab（F03-I16）：素材／策略／結構那幾頁是「編輯」，這頁是「唯讀＋兩個動作」
 * （重新整理成效、立即結案）——所有數字只認 `getPerformance`／`ingestOutcome`，絕不讀
 * `campaign_detail.outcome`（那是列表卡片的 SQL 小計，§0「Two total-derivers exist」）。 */
export function PerformanceTab({
  brandId,
  campaign: c,
  onCampaignChange,
}: {
  brandId: string;
  campaign: CampaignDetail;
  onCampaignChange: (campaign: CampaignDetail) => void;
}) {
  const published = c.status === "live" || c.status === "ended" || c.status === "closed";
  const today = new Date().toLocaleDateString("sv-SE");

  const [state, setState] = useState<
    | { status: "loading" }
    | { status: "error"; message: string }
    | { status: "ready"; data: CampaignPerformance }
  >({ status: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const [closeOpen, setCloseOpen] = useState(false);
  const [closing, setClosing] = useState(false);
  const [closeError, setCloseError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!published) return;
    setState({ status: "loading" });
    getPerformance(brandId, c.id)
      .then((data) => setState({ status: "ready", data }))
      .catch((err: unknown) =>
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取成效失敗。" }),
      );
  }, [brandId, c.id, published]);

  useEffect(load, [load]);

  async function handleRefresh() {
    setRefreshing(true);
    try {
      const data = await ingestOutcome(brandId, c.id);
      setState({ status: "ready", data });
    } catch (err) {
      setState({ status: "error", message: err instanceof Error ? err.message : "重新整理成效失敗。" });
    } finally {
      setRefreshing(false);
    }
  }

  async function handleClose() {
    setClosing(true);
    setCloseError(null);
    try {
      const updated = await closeCampaign(brandId, c.id);
      onCampaignChange(updated);
      setCloseOpen(false);
    } catch (err) {
      setCloseError(err instanceof Error ? err.message : "結案失敗，請稍後再試。");
    } finally {
      setClosing(false);
    }
  }

  if (!published) {
    return (
      <EmptyState
        title="還沒有成效資料"
        description="Campaign 上線後，這裡會顯示每日花費、購買與 ROAS 趨勢，以及結案時的判定。"
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {state.status === "loading" ? (
        <div className="surface">
          <div className="surface-body py-10 text-center text-sm text-muted-foreground">讀取中…</div>
        </div>
      ) : state.status === "error" ? (
        <EmptyState title="讀取失敗" description={state.message} onAction={load} actionLabel="重新載入" />
      ) : (
        <PerformanceReady data={state.data} refreshing={refreshing} onRefresh={() => void handleRefresh()} />
      )}

      {(c.status === "live" || c.status === "ended") && (
        <div className="surface">
          <div className="surface-header">
            <h2>結案</h2>
          </div>
          <div className="surface-body flex items-center justify-between gap-4">
            <span className="flex flex-col gap-1 text-sm text-muted-foreground">
              <span>
                {c.status === "ended"
                  ? "投放已結束，7 天後系統會自動結案，也可以現在提前手動結案。"
                  : EARLY_CLOSE_SENTENCE}
              </span>
              {c.status === "live" && c.end_date && c.end_date > today && (
                <span className="text-xs text-muted-foreground">
                  投放期間到 {c.end_date}，現在結案等於提前結束
                </span>
              )}
            </span>
            <Button onClick={() => setCloseOpen(true)}>立即結案</Button>
          </div>
        </div>
      )}

      {c.status === "closed" && <VerdictCard brandId={brandId} campaign={c} />}

      <Dialog open={closeOpen} onOpenChange={(open) => !open && setCloseOpen(false)}>
        <DialogContent>
          <DialogTitle>結案</DialogTitle>
          <DialogDescription>
            結案後會對照成功條件寫下判定，並在品牌智庫留一條學習，Campaign 之後會被鎖定，不能再改。
            {c.status === "live" && ` ${EARLY_CLOSE_SENTENCE}`}
          </DialogDescription>
          {closeError && <p className="text-sm text-danger">{closeError}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCloseOpen(false)} disabled={closing}>
              取消
            </Button>
            <Button type="button" onClick={() => void handleClose()} disabled={closing}>
              {closing ? "結案中…" : "確認結案"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function PerformanceReady({
  data,
  refreshing,
  onRefresh,
}: {
  data: CampaignPerformance;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const t = data.totals;
  return (
    <>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Kpi label="花費" value={formatCurrency(t.spend)} caption="累計花費・平台回報" />
        <Kpi label="購買" value={fmtPurchases(t.purchases)} caption="累計購買・平台回報" />
        <Kpi label="CPA" value={fmtCpa(t.cpa)} caption="花費 ÷ 購買" />
        <Kpi label="ROAS" value={formatMetaRoas(t.roas_conservative)} caption={`保守值・樂觀 ${formatMetaRoas(t.roas)}`} />
        <Kpi label="點擊率" value={formatPercent(t.ctr)} caption="累計點擊 ÷ 曝光" />
        <Kpi label="曝光" value={formatCount(t.impressions)} caption="累計曝光・平台回報" />
      </div>

      <div className="surface">
        <div className="surface-header">
          <h2>成效趨勢</h2>
          <Button variant="outline" size="sm" onClick={onRefresh} disabled={refreshing}>
            <RefreshCw size={14} className={refreshing ? "animate-spin" : "hidden"} />
            {refreshing ? "整理中…" : "重新整理成效"}
          </Button>
        </div>
        <div className="surface-body flex flex-col gap-3">
          {data.daily.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">還沒有每日資料。</p>
          ) : (
            <TrendChart daily={data.daily} />
          )}
          <ul className="flex flex-col gap-1 text-xs text-muted-foreground">
            {data.coverage.expected > 0 && (
              <li>
                {data.coverage.missing} 個廣告日沒有資料（共 {data.coverage.expected} 個）
              </li>
            )}
            <li>{data.last_data_at ? `最新資料日：${data.daily[data.daily.length - 1]?.day ?? "－"}` : "還沒有資料"}</li>
          </ul>
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
                <th className="px-3 py-2 font-medium">購買</th>
                <th className="px-3 py-2 font-medium">CPA</th>
                <th className="px-3 py-2 font-medium">ROAS（保守／樂觀）</th>
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
                    <td className="px-3 py-2">{formatCurrency(g.spend)}</td>
                    <td className="px-3 py-2">{fmtPurchases(g.purchases)}</td>
                    <td className="px-3 py-2">{fmtCpa(g.cpa)}</td>
                    <td className="px-3 py-2">
                      {formatMetaRoas(g.roas_conservative)} ／ {formatMetaRoas(g.roas)}
                    </td>
                    <td className="px-3 py-2">{formatPercent(g.ctr)}</td>
                    <td className="px-3 py-2">{formatPercent(g.spend_share)}</td>
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
                  <tr key={a.ad_id} className="border-t border-border">
                    <td className="px-3 py-2">{a.name}</td>
                    <td className="px-3 py-2">{formatCurrency(a.spend)}</td>
                    <td className="px-3 py-2">{formatPercent(a.spend_share)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

function VerdictCard({ brandId, campaign: c }: { brandId: string; campaign: CampaignDetail }) {
  const vj = c.verdict_json as AdsVerdictJson;
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
            <div className="text-sm font-semibold">{METRIC_LABELS[c.success_metric] ?? c.success_metric}</div>
          </div>
          <div className="field-card">
            <div className="text-xs text-muted-foreground">目標</div>
            <div className="text-sm font-semibold">
              {vj.target == null ? "未設定" : fmtMetricValue(c.success_metric, vj.target)}
            </div>
          </div>
          <div className="field-card">
            <div className="text-xs text-muted-foreground">實際</div>
            <div className="text-sm font-semibold">{fmtMetricValue(c.success_metric, vj.actual ?? null)}</div>
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
            <p className="text-sm">{sentence}</p>
            <Link to={`/brands/${brandId}/library`} className="text-xs text-primary hover:underline">
              查看品牌智庫 →
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
