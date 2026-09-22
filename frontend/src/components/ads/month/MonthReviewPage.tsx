import { useEffect, useMemo, useState } from "react";
import { Image as ImageIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { getMonthlyBudget, type MonthlyBudget } from "@/lib/adsChangeApi";
import { listCampaigns, type CampaignCard as CampaignCardData } from "@/lib/adsApi";
import { getTriage, type TriageClass, type TriageItem } from "@/lib/adsTriageApi";
import { fetchOrders, type OrderSummary } from "@/lib/ordersApi";
import { ActionBar, Chip, Meter, ReservedSlotCard, Segmented } from "../patterns";
import { budgetMoney, currentBudgetMonth } from "../MonthlyBudgetPanel";

/** 每月回顧（F24-I04，v7 原型 `month()`）：活動照常投放，這頁只整理帳——內部投放計畫與平台
 * 原生物件不受影響，這裡不寫任何東西回廣告平台。 */

// 純數字，最多兩位小數，不四捨五入到整數（`triage`／`orders` 沒有回幣別／不需要幣別的量測值，
// 同 `home/CampaignCard.tsx`／`detail/CampaignDetailPage.tsx` 各自留一份的先例，這支不在
// `frontend/src/lib/**`，不能共用一份）。未知的量測值＝「累積中」（design-system §7）。
function formatAmount(value: number | null): string {
  if (value === null) return "累積中";
  return value.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
}

// 本機日曆日期小工具（同 `wait/WaitPage.tsx` 的先例，各自留一份）。
function parseLocalDateParts(iso: string): { y: number; m: number; d: number } {
  const [y, m, d] = iso.split("-").map(Number);
  return { y, m, d };
}
function formatMD(iso: string): string {
  const { m, d } = parseLocalDateParts(iso);
  return `${m}/${d}`;
}
function shiftMonth(base: string, delta: number): string {
  const [y, m] = base.split("-").map(Number);
  const d = new Date(y, m - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** 未知態的量尺（`Meter`／`patterns/**` 是這張票的 `do_not_touch`，不能加一個「打斜紋」變體
 * 進共用元件）——同 `home/CampaignCard.tsx` 的 `HatchedStrip` 先例，這支自己留一份，尺寸跟
 * `Meter` 的軸一致（`h-2.5 rounded-md`），這樣兩種量尺疊在同一欄看起來還是同一組。 */
function HatchedMeter({ left, right }: { left?: string; right?: string }) {
  return (
    <div data-slot="meter">
      <div
        aria-hidden="true"
        className="mt-1.5 mb-1 h-2.5 rounded-md bg-muted"
        style={{
          backgroundImage:
            "repeating-linear-gradient(45deg, var(--color-border), var(--color-border) 4px, transparent 4px, transparent 8px)",
        }}
      />
      {(left || right) && (
        <div className="numeric flex justify-between gap-2 text-[11.5px] text-muted-foreground">
          <span>{left}</span>
          <span>{right}</span>
        </div>
      )}
    </div>
  );
}

/** 廣告縮圖（同 `detail/CampaignDetailPage.tsx` 的 `AdThumb` 先例，這支不在 touch 範圍內，
 * 不能匯出共用，這裡自己留一份一樣的行為：`null` 或載入失敗都落到中性佔位圖示）。 */
function MaterialThumb({ url }: { url: string | null }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [url]);
  const showImage = url !== null && !failed;
  return (
    <div
      className="flex size-11 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-muted"
      aria-hidden="true"
    >
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element -- 這裡不是 Next.js 專案。
        <img src={url} alt="" className="size-full object-cover" onError={() => setFailed(true)} />
      ) : (
        <ImageIcon className="size-4 text-muted-foreground" />
      )}
    </div>
  );
}

type MonthChoice = "this" | "last";

type BudgetState = { status: "loading" } | { status: "error" } | { status: "ready"; budget: MonthlyBudget };

/** 全品牌花費卡：月選單只驅動這張卡（Feature Decisions）。`known_spend === null`（月預算的
 * `issues`沒有花費證據）沒有量尺，只印「花費未核實」＋第一條不確定原因；`amount === null`
 * （月總額還沒設定）打斜紋量尺；兩者都有值才是真的量尺。 */
function SpendCard({ brandId, month }: { brandId: string; month: string }) {
  const [state, setState] = useState<BudgetState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    getMonthlyBudget(brandId, month, controller.signal)
      .then((budget) => {
        if (!controller.signal.aborted) setState({ status: "ready", budget });
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ status: "error" });
      });
    return () => controller.abort();
  }, [brandId, month]);

  return (
    <div className="surface p-5">
      <div className="flex items-baseline justify-between gap-2 text-xs text-muted-foreground">
        <span>全品牌花費</span>
        <span>
          {state.status === "ready" &&
            (state.budget.amount === null
              ? "月總額 尚未設定"
              : `月總額 ${budgetMoney(state.budget.amount, state.budget.currency)}`)}
        </span>
      </div>
      {state.status === "loading" && <Skeleton className="mt-2 h-8 w-32" />}
      {state.status === "error" && <p role="alert" className="mt-2 text-sm text-warning">花費暫時讀取不到。</p>}
      {state.status === "ready" && (() => {
        const { known_spend, amount, currency, uncertainties } = state.budget;
        if (known_spend === null) {
          return (
            <>
              <p className="mt-1 text-2xl font-semibold text-muted-foreground">花費未核實</p>
              {uncertainties.length > 0 && (
                <p className="mt-2 text-xs text-muted-foreground">{uncertainties[0]}</p>
              )}
            </>
          );
        }
        return (
          <>
            <p className="numeric mt-1 text-2xl font-semibold">{budgetMoney(known_spend, currency)}</p>
            {amount === null ? (
              <HatchedMeter />
            ) : (
              <Meter value={known_spend} max={amount} tone="success" />
            )}
          </>
        );
      })()}
    </div>
  );
}

/** 商城訂單卡：跟預算月選單無關，一律印自己回應的實際區間（`since`／`until`）；沒有前一個月
 * 可比（Feature Decisions「no previous-month comparison」），量尺沒有上限就不畫填色，只留軸
 * （`Meter` 自己的誠實空狀態），不硬湊一個假的比較基準。 */
function OrdersCard({ summary }: { summary: OrderSummary }) {
  const windowLabel = summary.since && summary.until
    ? `${formatMD(summary.since)}–${formatMD(summary.until)} 實收`
    : "近 31 天實收";
  return (
    <div className="surface p-5">
      <div className="flex items-baseline justify-between gap-2 text-xs text-muted-foreground">
        <span>商城訂單淨額・品牌整體</span>
        <span>{windowLabel}</span>
      </div>
      <p className="numeric mt-1 text-2xl font-semibold">{formatAmount(summary.net_revenue)}</p>
      <Meter value={summary.net_revenue} max={null} tone="success" />
    </div>
  );
}

/** 一個活動一列（Feature Decisions「各活動 rows」）：這一列是版面，不是共用元件——`TodoRow`
 * 的編號插槽塞不進活動 chip，這裡自己組 flex row（objective 明講不要硬套 `TodoRow`）。 */
function CampaignRow({
  brandId, campaign, items,
}: { brandId: string; campaign: CampaignCardData; items: TriageItem[] }) {
  const detailHref = `/brands/${brandId}/ads/campaigns/${campaign.id}/detail`;
  const windowDays = new Set(items.map((item) => item.window.days));
  const sameWindow = items.length > 0 && windowDays.size === 1;
  const totalSpend = items.reduce((sum, item) => sum + (item.current.spend ?? 0), 0);
  const totalResults = items.reduce((sum, item) => sum + (item.current.result_count ?? 0), 0);
  const spendValue = sameWindow ? totalSpend : null;
  const cost = sameWindow && totalResults > 0 ? totalSpend / totalResults : null;
  const targetValue = items.length > 0 ? items[0].target.value : null;
  const resultLabel = items.length > 0 ? items[0].current.result_label : "成果";
  const costLabel = `每次${resultLabel}成本`;

  const judged = targetValue !== null && cost !== null;
  const ok = judged && (cost as number) <= (targetValue as number);
  const chipTone = !judged ? "neutral" : ok ? "ok" : "warn";
  const chipLabel = !judged ? "未判斷" : ok ? "達標" : "未達標";
  const canBar = judged && (targetValue as number) > 0;

  let spendCaption: string;
  let spendText: string;
  if (items.length === 0) {
    spendCaption = "花費";
    spendText = "累積中";
  } else if (sameWindow) {
    spendCaption = `花費・近 ${items[0].window.days} 天`;
    spendText = formatAmount(spendValue);
  } else {
    spendCaption = "花費";
    spendText = "各廣告期間不同，未合計";
  }

  return (
    <div className="flex flex-wrap items-center gap-4 border-t border-border py-3.5 first:border-t-0">
      <Link
        to={detailHref}
        className="w-full max-w-[220px] shrink-0 truncate text-sm font-semibold hover:text-primary hover:underline sm:w-52"
        title={campaign.name}
      >
        {campaign.name}
      </Link>
      <div className="min-w-28 shrink-0 text-right">
        <p className="text-[11.5px] text-muted-foreground">{spendCaption}</p>
        <p className="numeric text-sm font-semibold">{spendText}</p>
      </div>
      <div className="min-w-[200px] flex-1">
        {canBar ? (
          <Meter
            value={cost as number}
            max={(targetValue as number) * 2}
            marker={targetValue}
            tone={ok ? "success" : "warning"}
            left={`${costLabel} ${formatAmount(cost)}`}
            right={`目標 ${formatAmount(targetValue)}`}
          />
        ) : (
          <HatchedMeter
            left={`${costLabel} ${formatAmount(cost)}`}
            right={targetValue === null ? "尚未設定目標" : `目標 ${formatAmount(targetValue)}`}
          />
        )}
      </div>
      <Chip tone={chipTone} className="w-16 shrink-0 justify-center">{chipLabel}</Chip>
    </div>
  );
}

const MATERIAL_GROUPS: { key: string; title: string; tone: "ok" | "bad" | "neutral"; classes: TriageClass[] }[] = [
  { key: "better", title: "有效", tone: "ok", classes: ["better"] },
  { key: "stop_loss", title: "無效・已停", tone: "bad", classes: ["stop_loss"] },
  { key: "flat_insufficient", title: "還看不出", tone: "neutral", classes: ["flat", "insufficient"] },
];

/** 素材：依 Feature Decisions 只分三組（有效／無效已停／還看不出），`worse`／`no_target` 不在
 * 這裡列——那兩類在活動卡與佇列已經有自己的處理入口。 */
function MaterialGroups({ items }: { items: TriageItem[] }) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      {MATERIAL_GROUPS.map((group) => {
        const groupItems = items.filter((item) => group.classes.includes(item.class));
        return (
          <div key={group.key} className="surface p-5">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-[15px] font-semibold">{group.title}</h3>
              <Chip tone={group.tone}>{groupItems.length} 則</Chip>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              {groupItems.length === 0 ? (
                <p className="text-xs text-muted-foreground">目前沒有廣告落在這一類。</p>
              ) : (
                groupItems.map((item) => <MaterialThumb key={item.entity_id} url={item.thumbnail_url} />)
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

interface CampaignRowData { campaign: CampaignCardData; items: TriageItem[] }

type RowsState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; rows: CampaignRowData[] };

type OrdersState = { status: "loading" } | { status: "unavailable" } | { status: "ready"; summary: OrderSummary };

/** 訂單卡自己打自己的 API（review 先例：`AdsHomePage.tsx` 佇列／月預算／活動卡三塊各自獨立
 * 讀取，一塊失敗不拖累另外兩塊；design-system §1.7 worker self-check #9）——不跟「各活動」的
 * `listCampaigns`／`getTriage` 串在同一條 promise 鏈，這樣活動讀取失敗也不會連累這張卡。 */
function OrdersCardContainer({ brandId }: { brandId: string }) {
  const [state, setState] = useState<OrdersState>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchOrders(brandId)
      .then((data) => {
        if (!cancelled) setState({ status: "ready", summary: data.summary });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "unavailable" });
      });
    return () => {
      cancelled = true;
    };
  }, [brandId]);

  if (state.status !== "ready") return null;
  return <OrdersCard summary={state.summary} />;
}

export function MonthReviewPage({ brandId }: { brandId: string }) {
  const homeHref = `/brands/${brandId}/ads`;
  const thisMonth = useMemo(() => currentBudgetMonth(), []);
  const lastMonth = useMemo(() => shiftMonth(thisMonth, -1), [thisMonth]);
  const [monthChoice, setMonthChoice] = useState<MonthChoice>("this");
  const selectedMonth = monthChoice === "this" ? thisMonth : lastMonth;

  const [state, setState] = useState<RowsState>({ status: "loading" });
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    listCampaigns(brandId)
      .then((campaigns) => {
        const open = campaigns.filter((c) => c.status !== "closed");
        return Promise.all(
          open.map((campaign) =>
            getTriage(brandId, campaign.id).then((triage) => ({ campaign, items: triage.items })),
          ),
        );
      })
      .then((rows) => {
        if (!cancelled) setState({ status: "ready", rows });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" });
      });
    return () => {
      cancelled = true;
    };
  }, [brandId, reload]);

  const now = new Date();
  const titleMonth = now.getMonth() + 1;
  const lastCalendarMonth = titleMonth === 1 ? 12 : titleMonth - 1;
  const nextCalendarMonth = titleMonth === 12 ? 1 : titleMonth + 1;

  const allItems = state.status === "ready" ? state.rows.flatMap((r) => r.items) : [];

  return (
    <div className="flex max-w-[1180px] flex-col gap-5">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "每月回顧" }]} />

      <PageHeader
        title={`${titleMonth} 月回顧`}
        description="活動照常投放，這裡只整理帳"
        actions={
          <Segmented
            label="選擇月份"
            value={monthChoice}
            onChange={setMonthChoice}
            options={[
              { value: "last", label: `${lastCalendarMonth} 月` },
              { value: "this", label: `${titleMonth} 月` },
            ]}
          />
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <SpendCard brandId={brandId} month={selectedMonth} />
        <OrdersCardContainer brandId={brandId} />
      </div>

      <div>
        <h2 className="mb-3 text-[15px] font-semibold">各活動</h2>
        {state.status === "loading" && (
          <div className="surface p-5">
            <Skeleton className="h-24 w-full" />
          </div>
        )}
        {state.status === "error" && (
          <EmptyState
            title="讀取失敗"
            description={state.message}
            onAction={() => setReload((v) => v + 1)}
            actionLabel="重新讀取"
          />
        )}
        {state.status === "ready" && (
          state.rows.length === 0 ? (
            <EmptyState title="還沒有 Campaign" description="建立第一個 Campaign 後，這裡會列出每個活動的花費與判斷。" />
          ) : (
            <div className="surface px-5">
              {state.rows.map(({ campaign, items }) => (
                <CampaignRow key={campaign.id} brandId={brandId} campaign={campaign} items={items} />
              ))}
            </div>
          )
        )}
      </div>

      {state.status === "ready" && (
        <div>
          <h2 className="mb-3 text-[15px] font-semibold">素材</h2>
          <MaterialGroups items={allItems} />
        </div>
      )}

      <div>
        <h2 className="mb-3 text-[15px] font-semibold">記入品牌學習</h2>
        <ReservedSlotCard
          title="品牌學習紀錄"
          description="系統會整理每一次的判斷結果，記錄哪些方向對這個品牌有效或無效。"
          tag="接上後開放"
        />
      </div>

      <div>
        <h2 className="mb-3 text-[15px] font-semibold">✦ {nextCalendarMonth} 月建議</h2>
        <ReservedSlotCard
          title="下月建議"
          description="依這個月的判斷結果，整理下個月可以先做的素材與設定調整。"
          tag="接上後開放"
        />
      </div>

      <ActionBar back={<Button variant="ghost" asChild><Link to={homeHref}>← 投放中心</Link></Button>} />
    </div>
  );
}
