import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowUpRight, Inbox, BarChart3 } from "lucide-react";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import { Button } from "@/components/layout/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";
import { fetchInbox } from "@/lib/inboxApi";
import { internalHref } from "@/lib/internalHref";
import type { MetaSpendSummary } from "@/lib/metaApi";
import { fetchCreativePerformance, fetchDiagnosis } from "@/lib/scheduleApi";
import {
  COORDINATE_DIMENSIONS,
  type CoordinateDimension,
} from "@/lib/coordinatesApi";
import { splitPlottable } from "@/lib/quadrant";
import { formatMetaRoas } from "@/lib/format";

export const number = (value: number) =>
  value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
export function WidgetHeader({
  title,
  action,
}: {
  title: string;
  action?: ReactNode;
}) {
  return (
    <div className="surface-header">
      <h2 className="flex items-center gap-2">
        <BarChart3 size={16} className="text-muted-foreground" />
        {title}
      </h2>
      {action}
    </div>
  );
}
export function SpendDistribution({ data }: { data: MetaSpendSummary }) {
  const rows = [...data.campaigns]
    .sort((a, b) => b.spend - a.spend)
    .slice(0, 5);
  const max = Math.max(1, ...rows.map((r) => r.spend));
  return (
    <>
      <WidgetHeader title="活動花費分布" />
      <div className="surface-body">
        <p className="metric-number mb-1">{number(data.total.spend)}</p>
        <p className="mb-7 text-xs text-muted-foreground">
          本月累計 · 依廣告帳戶回報金額
        </p>
        {!rows.length ? (
          <EmptyState
            title="尚無花費資料"
            description="連接 Meta 並完成每日資料拉取後，這裡會顯示花費最高的活動。"
            actionInternal
            actionHref="/settings?tab=meta"
            actionLabel="連接 Meta"
          />
        ) : (
          <div className="grid gap-5">
            {rows.map((row, i) => (
              <div key={row.campaign_id}>
                <div className="mb-2 flex justify-between gap-3 text-xs">
                  <span className="truncate" title={row.campaign_name}>
                    {row.campaign_name}
                  </span>
                  <span className="numeric">{number(row.spend)}</span>
                </div>
                <div className="h-2.5 rounded bg-muted">
                  <div
                    className="chart-bar"
                    style={{
                      width: `${(row.spend / max) * 100}%`,
                      background: [
                        "var(--color-primary)",
                        "var(--color-chart-spend)",
                        "var(--color-chart-aqua)",
                        "var(--color-chart-soft)",
                        "var(--color-chart-rest)",
                      ][i],
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
        <p className="mt-5 text-xs text-muted-foreground">
          依花費排序，最多顯示 5 個活動。
        </p>
      </div>
    </>
  );
}
export function CampaignTable({ data }: { data: MetaSpendSummary }) {
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(data.campaigns.length / 5));
  const current = Math.min(page, pageCount - 1);
  return (
    <>
      <WidgetHeader
        title="活動概況"
        action={
          <span className="text-xs text-muted-foreground">
            {data.campaigns.length} 個活動
          </span>
        }
      />
      <div className="overflow-x-auto">
        <table className="text-left text-xs">
          <thead>
            <tr>
              {["活動名稱", "花費", "曝光", "點擊", "Meta ROAS"].map(
                (label) => (
                  <th key={label} className="whitespace-nowrap">
                    {label}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {data.campaigns.slice(current * 5, current * 5 + 5).map((row) => (
              <tr key={row.campaign_id} className="border-t border-border">
                <td className="max-w-52">
                  <span className="line-clamp-2" title={row.campaign_name}>
                    {row.campaign_name}
                  </span>
                </td>
                <td>{number(row.spend)}</td>
                <td>{number(row.impressions)}</td>
                <td>{number(row.clicks)}</td>
                <td className="font-medium text-primary">
                  {formatMetaRoas(row.roas)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!data.campaigns.length && (
        <div className="p-8 text-center text-muted-foreground">
          本月尚無活動資料
        </div>
      )}
      <div className="flex items-center justify-between gap-2 border-t border-border px-5 py-3">
        <span className="text-xs text-muted-foreground">
          {current + 1} / {pageCount} 頁
        </span>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="ghost"
            disabled={!current}
            onClick={() => setPage(current - 1)}
          >
            上一頁
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={current + 1 >= pageCount}
            onClick={() => setPage(current + 1)}
          >
            下一頁
          </Button>
        </div>
      </div>
    </>
  );
}
export function InboxWidget({ brandId }: { brandId: string }) {
  const { scope } = useWorkspace();
  const query = useQuery({ queryKey: [scope, "inbox"], queryFn: fetchInbox });
  const items =
    query.data?.open.filter((item) => item.brand_id === brandId) ?? [];
  return (
    <>
      <WidgetHeader
        title="待處理"
        action={
          <Link className="text-xs text-primary" to="/inbox">
            全部 <ArrowUpRight size={13} className="inline" />
          </Link>
        }
      />
      <div className="surface-body">
        {query.isPending ? (
          <p className="text-muted-foreground">讀取中…</p>
        ) : query.isError ? (
          <p role="alert">
            {query.error.message}
            <Button variant="link" onClick={() => void query.refetch()}>
              重試
            </Button>
          </p>
        ) : items.length ? (
          <div className="divide-y divide-border">
            {items.slice(0, 4).map((item) => (
              <Link
                key={item.id}
                to={item.action_url ? internalHref(item.action_url) : "/inbox"}
                className="flex gap-3 py-4"
              >
                <span
                  className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${item.severity === "money_loss" ? "bg-destructive" : "bg-warning"}`}
                />
                <div className="min-w-0">
                  <p className="mb-1 text-xs text-muted-foreground">
                    {item.category_label}
                  </p>
                  <p className="line-clamp-2 text-sm">{item.message}</p>
                </div>
                <ArrowUpRight
                  size={14}
                  className="ml-auto text-muted-foreground"
                />
              </Link>
            ))}
          </div>
        ) : (
          <div className="flex min-h-44 flex-col items-center justify-center gap-3 text-muted-foreground">
            <Inbox size={28} strokeWidth={1.4} />
            <p>目前沒有待處理事項</p>
          </div>
        )}
      </div>
    </>
  );
}
export function PerformanceWidget({
  brandId,
  onDetails,
}: {
  brandId: string;
  onDetails: () => void;
}) {
  const { scope } = useWorkspace();
  const [dimension, setDimension] = useState<CoordinateDimension>("angle");
  const [currency, setCurrency] = useState("");
  const query = useQuery({
    queryKey: [scope, brandId, "creative-performance"],
    queryFn: () => fetchCreativePerformance(brandId),
  });
  const diagnosis = useQuery({
    queryKey: [scope, brandId, "diagnosis"],
    queryFn: () => fetchDiagnosis(brandId),
  });
  const currencies = query.data?.currencies ?? [];
  const selected =
    currencies.find((c) => c.currency === currency) ?? currencies[0];
  const active = selected?.dimensions.find((d) => d.dimension === dimension);
  const { points, noSpend, noRevenue } = splitPlottable(active?.values ?? []);
  const breakeven = diagnosis.data?.breakeven.roas ?? null;
  const sorted = [...points].sort((a, b) => b.spend - a.spend).slice(0, 5);
  const max = Math.ceil(
    Math.max(1, breakeven ?? 0, ...sorted.map((p) => Math.max(p.low, p.high))) *
      1.15,
  );
  return (
    <>
      <WidgetHeader
        title="素材成效比較"
        action={
          <Button variant="ghost" size="sm" onClick={onDetails}>
            完整分析 <ArrowUpRight />
          </Button>
        }
      />
      <div className="surface-body">
        <div className="mb-5 flex flex-wrap gap-2">
          <select
            aria-label="成效維度"
            value={dimension}
            onChange={(e) =>
              setDimension(e.target.value as CoordinateDimension)
            }
          >
            {COORDINATE_DIMENSIONS.map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
          {currencies.length > 0 && (
            <select
              aria-label="成效幣別"
              value={selected?.currency}
              onChange={(e) => setCurrency(e.target.value)}
            >
              {currencies.map((c) => (
                <option key={c.currency}>{c.currency}</option>
              ))}
            </select>
          )}
        </div>
        {query.isPending ? (
          <p className="py-8 text-muted-foreground">成效資料讀取中…</p>
        ) : query.isError ? (
          <p role="alert">
            {query.error.message}
            <Button variant="link" onClick={() => void query.refetch()}>
              重試
            </Button>
          </p>
        ) : !sorted.length ? (
          <div className="py-8 text-center text-muted-foreground">
            {!currencies.length
              ? "本月尚無素材成效資料"
              : "目前沒有可計算 ROAS 的座標"}
          </div>
        ) : (
          <div
            role="img"
            aria-label="各座標 ROAS 區間；下方列出保守值至有追蹤花費的比值"
            className="grid gap-4"
          >
            {sorted.map((p) => (
              <div key={p.key}>
                <div className="mb-2 flex justify-between gap-3 text-xs">
                  <span className="truncate">{p.label}</span>
                  <span className="numeric shrink-0">
                    {p.low.toFixed(2)}–{p.high.toFixed(2)}x
                  </span>
                </div>
                <div className="relative h-3 rounded bg-muted">
                  {breakeven !== null && (
                    <span
                      className="absolute -top-1 z-10 h-5 border-l border-dashed border-muted-foreground"
                      style={{ left: `${(breakeven / max) * 100}%` }}
                    />
                  )}
                  <span
                    className="absolute h-3 min-w-0.5 rounded bg-primary/65"
                    style={{
                      left: `${(Math.min(p.low, p.high) / max) * 100}%`,
                      width: `${(Math.abs(p.high - p.low) / max) * 100}%`,
                    }}
                  />
                  <span
                    className="absolute top-0 h-3 w-1 rounded bg-primary"
                    style={{ left: `${(p.low / max) * 100}%` }}
                  />
                </div>
              </div>
            ))}
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>0x</span>
              <span>
                {breakeven === null
                  ? "尚無可用打平線"
                  : `打平 ${breakeven.toFixed(2)}x`}
              </span>
              <span>{max}x</span>
            </div>
          </div>
        )}
        <p className="mt-5 text-xs leading-relaxed text-muted-foreground">
          區間：營收 ÷ 全部花費 → 營收 ÷ 有追蹤花費。依花費顯示前 5 項。
        </p>
        {!!(
          noSpend.length ||
          noRevenue.length ||
          active?.untagged.ad_count
        ) && (
          <p className="mt-2 text-xs text-muted-foreground">
            零花費 {noSpend.length} 項 · 未追蹤營收 {noRevenue.length} 項 ·
            未標座標 {active?.untagged.ad_count ?? 0} 則（花費{" "}
            {number(active?.untagged.spend ?? 0)} {selected?.currency}）
          </p>
        )}
      </div>
    </>
  );
}
