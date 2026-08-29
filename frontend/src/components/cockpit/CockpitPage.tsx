import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { fetchBrandMonth, fetchOverview, type BrandMonthMoney } from "@/lib/api";
import { formatCurrency, formatMetaRoas, formatRelativeHours, formatRoas } from "@/lib/format";
import { fetchMetaSpend, type MetaCampaignSpend, type MetaSpendSummary } from "@/lib/metaApi";

/** 單品牌頁（`/brands/:brandId`）。
 *
 * 外殼切片（2026-08-28）：原本的駕駛艙（KPI 卡、營收 vs 花費主圖、成效釘選區、警示區、
 * AI 油錢錶、內容產線）整組隨 `app/ads/` 一起刪掉——那些數字全部來自廣告成效快照，
 * 沒有成效資料就沒有數字（HANDOFF-shell-slice.md §3.8）。這一頁刻意保留而不是刪掉：
 * 它是外殼儀表板未來的位置，現在先是品牌標題＋一句空態。
 *
 * 品牌名稱從跨品牌總覽那支既有端點取（`/api/dashboard/overview`），不另開新端點——
 * 這一頁還沒有自己的資料，多開一支只為了拿一個名字不划算。
 *
 * 票 05：加回本月 Meta 花費（獨立於品牌名稱那次讀取，見下面 MetaSpendSection——花費
 * 讀取失敗不該連品牌標題都出不來）。 */
type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; brandName: string | null };

export function CockpitPage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    fetchOverview()
      .then((cards) => {
        if (cancelled) return;
        const card = cards.find((c) => c.brand_id === brandId);
        setState({ status: "ready", brandName: card ? card.brand_name : null });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [brandId]);

  const breadcrumb = (
    <Breadcrumb
      items={[
        { label: "跨品牌總覽", href: "/" },
        { label: state.status === "ready" && state.brandName ? state.brandName : "品牌" },
      ]}
    />
  );

  let content: ReactNode;
  if (state.status === "loading") {
    content = <EmptyState title="讀取中…" description="正在載入這個品牌。" />;
  } else if (state.status === "error") {
    content = (
      <EmptyState
        title="讀取失敗"
        description={state.message}
        actionHref="/"
        actionInternal
        actionLabel="回跨品牌總覽"
      />
    );
  } else if (state.brandName === null) {
    content = (
      <EmptyState
        title="找不到這個品牌"
        description="這個品牌可能已經被刪除，或者網址打錯了。"
        actionHref="/"
        actionInternal
        actionLabel="回跨品牌總覽"
      />
    );
  } else {
    content = (
      <div className="flex flex-col gap-6">
        <div className="flex items-center justify-between">
          <h1 className="font-display text-2xl text-foreground">{state.brandName}</h1>
          <Link
            to="/"
            className="text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            回跨品牌總覽
          </Link>
        </div>
        <EmptyState
          title="本期還沒有方案"
          description="產生本期方案的按鈕還沒接上來。品牌資料、產品與訂單可以先從左側選單進去看。"
        />
        <MonthMoneySection brandId={brandId} />
        <MetaSpendSection brandId={brandId} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {breadcrumb}
      {content}
    </div>
  );
}

type MoneyState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: BrandMonthMoney };

/** 票 06：本月花費／營收／毛利／ROAS 併桌——回答 ADR 0034 第二個失敗案例：不用再把
 * Meta 儀表板、Shopee 儀表板、自己網站後台各開一次，自己心算出這個月賺不賺錢。
 *
 * 票 12：營收改讀 `channel_revenue`，是跨通路總和（官網＋粉專／IG／LINE＋平台商店＋
 * 實體店），不再只算官網。毛利仍然只算官網——毛利算式吃 `order_item` × 單位成本，
 * 其他通路沒有逐項商品資料可算。平台商店（marketplace，蝦皮等）的欄位對照還沒拿真實
 * 匯出檔驗證過，`marketplace_uncalibrated` 為 true 時說明句要補這句提醒。
 *
 * 這裡的 ROAS 是「全通路營收 ÷ 花費」，跟下面逐活動表格裡 Meta 自己回報的 ROAS 是
 * 兩件不同的事——用 label 分開講清楚，不動下面表格既有的 ROAS 欄位。 */
function MonthMoneySection({ brandId }: { brandId: string }) {
  const [state, setState] = useState<MoneyState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchBrandMonth(brandId)
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [brandId]);

  if (state.status === "loading") {
    return <p className="text-sm text-muted-foreground">本月概況讀取中…</p>;
  }
  if (state.status === "error") {
    return <p className="text-sm text-danger">本月概況讀取失敗：{state.message}</p>;
  }

  const {
    spend,
    revenue,
    margin,
    margin_unknown_sku_count: unknownSkuCount,
    roas,
    has_orders: hasOrders,
    marketplace_uncalibrated: marketplaceUncalibrated,
  } = state.data;

  const revenueText = hasOrders ? formatCurrency(revenue) : "本月還沒有訂單";
  let marginText: string;
  if (!hasOrders) {
    marginText = "本月還沒有訂單";
  } else if (margin !== null) {
    marginText = formatCurrency(margin);
  } else if (revenue === null) {
    marginText = "累積中";
  } else {
    marginText = `成本還沒登記，算不出毛利（${unknownSkuCount} 個 SKU 還沒登記成本）`;
  }

  return (
    <section className="flex flex-col gap-3">
      <h2 className="font-display text-xl text-foreground">本月概況</h2>
      <p className="text-sm text-muted-foreground">
        營收是每個通路加總（官網、粉專／IG／LINE、平台商店、實體店）。
        {marketplaceUncalibrated &&
          "其中平台商店的數字來自還沒拿真實匯出檔驗證過的匯入程式，這部分還不能全信。"}
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MoneyTile label="本月花費" value={formatCurrency(spend)} />
        <MoneyTile label="本月營收（全通路）" value={revenueText} />
        <MoneyTile label="本月毛利（官網）" value={marginText} />
        <MoneyTile label="全通路 ROAS（營收 ÷ 花費，非平台回報）" value={formatRoas(roas)} />
      </div>
    </section>
  );
}

function MoneyTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-lg font-medium text-foreground">{value}</p>
    </div>
  );
}

type SpendState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: MetaSpendSummary };

/** 票 05：本月 Meta 花費／成效，逐活動＋一列總計。獨立於品牌標題的讀取，失敗互不
 * 牽連。ROAS 為 null 一律顯示「未追蹤」，不是 0（`formatMetaRoas`）——這是這張票
 * 存在的理由，見票面說明。 */
function MetaSpendSection({ brandId }: { brandId: string }) {
  const [state, setState] = useState<SpendState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchMetaSpend(brandId)
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [brandId]);

  if (state.status === "loading") {
    return <p className="text-sm text-muted-foreground">本月 Meta 花費讀取中…</p>;
  }
  if (state.status === "error") {
    return <p className="text-sm text-danger">本月 Meta 花費讀取失敗：{state.message}</p>;
  }

  const { campaigns, total, last_pull_at: lastPullAt } = state.data;

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="font-display text-xl text-foreground">本月 Meta 花費</h2>
        <span className="text-sm text-muted-foreground">
          {lastPullAt ? `上次成功拉取：${formatRelativeHours(lastPullAt)}` : "尚未成功拉取過"}
        </span>
      </div>
      {campaigns.length === 0 ? (
        <EmptyState
          title="這個月還沒有 Meta 花費資料"
          description="把 Meta 廣告帳戶連接並綁定到這個品牌，資料會在每日拉取後出現在這裡。"
          actionHref="/settings"
          actionInternal
          actionLabel="前往設定連接 Meta"
        />
      ) : (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted text-muted-foreground">
              <tr>
                <SpendHeader>活動</SpendHeader>
                <SpendHeader>花費</SpendHeader>
                <SpendHeader>曝光</SpendHeader>
                <SpendHeader>點擊</SpendHeader>
                <SpendHeader>ROAS</SpendHeader>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((row) => (
                <SpendRow key={row.campaign_id} row={row} />
              ))}
              <SpendRow row={total} isTotal />
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function SpendRow({ row, isTotal = false }: { row: MetaCampaignSpend; isTotal?: boolean }) {
  return (
    <tr className={`border-t border-border ${isTotal ? "font-medium text-foreground" : ""}`}>
      <SpendCell>{row.campaign_name}</SpendCell>
      <SpendCell>{formatCurrency(row.spend)}</SpendCell>
      <SpendCell>{row.impressions.toLocaleString("zh-TW")}</SpendCell>
      <SpendCell>{row.clicks.toLocaleString("zh-TW")}</SpendCell>
      <SpendCell>{formatMetaRoas(row.roas)}</SpendCell>
    </tr>
  );
}

function SpendHeader({ children }: { children: ReactNode }) {
  return <th className="whitespace-nowrap px-3 py-2 font-medium">{children}</th>;
}

function SpendCell({ children }: { children: ReactNode }) {
  return <td className="whitespace-nowrap px-3 py-2 text-foreground">{children}</td>;
}
