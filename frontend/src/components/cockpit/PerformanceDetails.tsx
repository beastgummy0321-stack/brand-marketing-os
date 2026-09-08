import { useEffect, useState, type ReactNode } from "react";
import { CoordinateQuadrantChart } from "@/components/cockpit/CoordinateQuadrantChart";
import {
  DiagnosisResult,
  DiagnosisRunButton,
  useDiagnosisPanel,
} from "@/components/cockpit/DiagnosisPanel";
import { EmptyState } from "@/components/layout/EmptyState";
import { fetchBrandMonth, type BrandMonthMoney } from "@/lib/api";
import {
  COORDINATE_DIMENSIONS,
  type CoordinateDimension,
} from "@/lib/coordinatesApi";
import { formatCurrency, formatMetaRoas, formatMoney, formatRoas } from "@/lib/format";
import {
  fetchCreativePerformance,
  type CreativePerformanceCurrency,
  type CreativePerformanceUntagged,
  type CreativePerformanceValue,
} from "@/lib/scheduleApi";

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
export function MonthMoneySection({ brandId }: { brandId: string }) {
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
            message:
              err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
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
    return (
      <p className="text-sm text-danger">本月概況讀取失敗：{state.message}</p>
    );
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
        <MoneyTile
          label="全通路 ROAS（營收 ÷ 花費，非平台回報）"
          value={formatRoas(roas)}
        />
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

function SpendHeader({ children }: { children: ReactNode }) {
  return (
    <th className="whitespace-nowrap px-3 py-2 font-medium">{children}</th>
  );
}

function SpendCell({ children }: { children: ReactNode }) {
  return (
    <td className="whitespace-nowrap px-3 py-2 text-foreground">{children}</td>
  );
}

type PerformanceState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; currencies: CreativePerformanceCurrency[] };

/** 票 T5（ADR 0057）：本月每個座標維度的花費／成效——跟上面「本月 Meta 花費」讀同一批
 * 花費（同一個窗口），只是按素材的七維座標分組而不是按活動分組，兩邊的總計必須對得上
 * （done-check 10）。獨立的讀取／失敗狀態，一區失敗不牽連鄰居（這一頁既有的慣例）。
 *
 * 維度太多、一頁擠不下（docs/design-system.md §1：不做一路下滑的長頁）：用
 * 現有的分頁按鈕視覺語彙（比照 `LibraryPage.tsx` 的分頁按鈕樣式）做一個維度挑選器，
 * 底下永遠只有一張表。 */
export function CreativePerformanceSection({ brandId }: { brandId: string }) {
  const [state, setState] = useState<PerformanceState>({ status: "loading" });
  const [dimension, setDimension] = useState<CoordinateDimension>(
    COORDINATE_DIMENSIONS[0][0],
  );
  // 票 02（T6c）：成效判讀——按鈕擺標題列、結果擺標題下方，狀態全部留在這個 hook
  // （見 `DiagnosisPanel.tsx` 檔頭說明），不在這裡多長業務邏輯。
  const diagnosisPanel = useDiagnosisPanel(brandId);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchCreativePerformance(brandId)
      .then((data) => {
        if (!cancelled)
          setState({ status: "ready", currencies: data.currencies });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setState({
            status: "error",
            message:
              err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [brandId]);

  if (state.status === "loading") {
    return (
      <p className="text-sm text-muted-foreground">本月素材座標成效讀取中…</p>
    );
  }
  if (state.status === "error") {
    return (
      <p className="text-sm text-danger">
        本月素材座標成效讀取失敗：{state.message}
      </p>
    );
  }

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-display text-xl text-foreground">素材座標成效</h2>
        <DiagnosisRunButton panel={diagnosisPanel} />
      </div>
      <DiagnosisResult panel={diagnosisPanel} />
      {state.currencies.length === 0 ? (
        <EmptyState
          title="這個月還沒有 Meta 花費資料"
          description="這一區跟上面「本月 Meta 花費」讀同一批數字，等那邊出現資料，這裡也會一起出現。"
        />
      ) : (
        state.currencies.map((currency) => (
          <CurrencyPerformance
            key={currency.currency}
            data={currency}
            showCurrencyLabel={true}
            dimension={dimension}
            onDimensionChange={setDimension}
            // 圖上的打平線跟判讀卡片必須是同一條線——一頁兩個賺賠標準，圖會把其實在賠錢的
            // 座標畫成贏家（`ads-commerce.md:13`）。判讀還沒讀回來（或算不出毛利率）就不畫。
            breakeven={
              diagnosisPanel.state.status === "ready"
                ? diagnosisPanel.state.diagnosis.breakeven.roas
                : null
            }
          />
        ))
      )}
    </section>
  );
}

function CurrencyPerformance({
  data,
  showCurrencyLabel,
  dimension,
  onDimensionChange,
  breakeven,
}: {
  data: CreativePerformanceCurrency;
  showCurrencyLabel: boolean;
  dimension: CoordinateDimension;
  onDimensionChange: (d: CoordinateDimension) => void;
  breakeven: number | null;
}) {
  const active = data.dimensions.find((d) => d.dimension === dimension);
  const values = active ? active.values : [];
  const untagged = active ? active.untagged : { spend: 0, ad_count: 0 };
  const onlyUntagged = values.length === 0 && untagged.ad_count > 0;

  return (
    <div className="flex flex-col gap-2">
      {showCurrencyLabel && (
        <p className="text-sm font-medium text-foreground">{data.currency}</p>
      )}
      <div className="flex flex-wrap gap-1.5">
        {COORDINATE_DIMENSIONS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => onDimensionChange(key)}
            className={
              "rounded-md px-3 py-1.5 text-sm font-medium transition-colors " +
              (dimension === key
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground")
            }
          >
            {label}
          </button>
        ))}
      </div>
      {onlyUntagged && (
        <EmptyState
          title="還沒有座標可以對"
          description="這個品牌本月的花費目前都對不到任何座標。"
        />
      )}
      <>
        {/* 票 T6b：同一份數字先看圖再看表——圖回答「哪個座標在賺、哪個在賠」，表回答
            「確切是多少」。兩邊讀同一個 `active`，不另外抓一次資料。 */}
        <CoordinateQuadrantChart
          currency={data.currency}
          values={values}
          untagged={untagged}
          breakeven={breakeven}
        />
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted text-muted-foreground">
              <tr>
                <SpendHeader>座標</SpendHeader>
                <SpendHeader>花費</SpendHeader>
                <SpendHeader>曝光</SpendHeader>
                <SpendHeader>點擊</SpendHeader>
                <SpendHeader>營收</SpendHeader>
                <SpendHeader>ROAS</SpendHeader>
                <SpendHeader>資料覆蓋率</SpendHeader>
                <SpendHeader>廣告數</SpendHeader>
              </tr>
            </thead>
            <tbody>
              {values.map((value) => (
                <CoordinateValueRow
                  key={value.key}
                  value={value}
                  currency={data.currency}
                />
              ))}
              {untagged.ad_count > 0 && (
                <UntaggedRow untagged={untagged} currency={data.currency} />
              )}
            </tbody>
          </table>
        </div>
      </>
    </div>
  );
}

function CoordinateValueRow({
  value,
  currency,
}: {
  value: CreativePerformanceValue;
  currency: string;
}) {
  return (
    <tr className="border-t border-border">
      <SpendCell>{value.label}</SpendCell>
      <SpendCell>{formatMoney(value.spend, currency)}</SpendCell>
      <SpendCell>{value.impressions.toLocaleString("zh-TW")}</SpendCell>
      <SpendCell>{value.clicks.toLocaleString("zh-TW")}</SpendCell>
      <SpendCell>
        {value.revenue === null
          ? "未追蹤"
          : formatMoney(value.revenue, currency)}
      </SpendCell>
      <SpendCell>{formatMetaRoas(value.roas)}</SpendCell>
      <SpendCell>{(value.roas_coverage * 100).toFixed(0)}%</SpendCell>
      <SpendCell>{value.ad_count}</SpendCell>
    </tr>
  );
}

/** `未標座標`：視覺上獨立一列（票面要求），非零時永遠出現在表格最後一列。 */
function UntaggedRow({
  untagged,
  currency,
}: {
  untagged: CreativePerformanceUntagged;
  currency: string;
}) {
  return (
    <tr className="border-t border-border bg-muted/40 font-medium text-foreground">
      <SpendCell>未標座標</SpendCell>
      <SpendCell>{formatMoney(untagged.spend, currency)}</SpendCell>
      <SpendCell>—</SpendCell>
      <SpendCell>—</SpendCell>
      <SpendCell>—</SpendCell>
      <SpendCell>—</SpendCell>
      <SpendCell>—</SpendCell>
      <SpendCell>{untagged.ad_count}</SpendCell>
    </tr>
  );
}
