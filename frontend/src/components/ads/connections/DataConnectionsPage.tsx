import { useEffect, useState } from "react";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { PageHeader } from "@/components/layout/PageHeader";
import { getOrgId } from "@/lib/auth";
import { formatMoney, formatSyncTime } from "@/lib/format";
import { getMonthlyBudget, type MonthlyBudget } from "@/lib/adsChangeApi";
import {
  fetchMetaAccounts,
  fetchMetaBackfillStatus,
  fetchMetaSpend,
  type MetaAccountsData,
  type MetaBackfillStatus,
  type MetaSpendSummary,
} from "@/lib/metaApi";
import { fetchOrders, type OrdersPageData } from "@/lib/ordersApi";
import { fetchProductList, type ProductListItem } from "@/lib/productsApi";
import { Chip } from "../patterns";
import { currentBudgetMonth } from "../MonthlyBudgetPanel";
import { ConnectionCard, type ConnectionState } from "./ConnectionCard";

type ReadyState = Extract<ConnectionState, { status: "ready" }>;

type LoadState<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; value: T };

/** 一張卡自己的讀取／重試（§1.7 item 9：一塊失敗不拖累其餘卡）。這五張卡各自打自己的
 * API，沒有共用的整包讀端點（Feature Decisions：agent choice）。 */
function useLoad<T>(loader: () => Promise<T>, deps: unknown[]): { state: LoadState<T>; reload: () => void } {
  const [state, setState] = useState<LoadState<T>>({ status: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    loader()
      .then((value) => {
        if (!cancelled) setState({ status: "ready", value });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" });
      });
    return () => {
      cancelled = true;
    };
    // deps 決定何時重打；loader 本身是每次 render 新建的閉包，不放進相依陣列。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, reloadKey]);
  return { state, reload: () => setReloadKey((v) => v + 1) };
}

function toCardState<T>(load: LoadState<T>, reload: () => void, map: (value: T) => ReadyState): ConnectionState {
  if (load.status === "loading") return { status: "loading" };
  if (load.status === "error") return { status: "error", message: load.message, onRetry: reload };
  return map(load.value);
}

function formatMD(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
}

// ---- 每張卡各自的資料 → 畫面狀態（純函式，方便直接測；不臆造原型的固定文案，
// 只有「影響」chip 沿用原型固定文案，見 Feature Decisions）。

export function accountsCardState(accounts: MetaAccountsData, spend: MetaSpendSummary, brandId: string): ReadyState {
  const bound = accounts.accounts.filter((a) => a.bound_brand_ids.includes(brandId));
  const lastPull = spend.last_pull_at ? formatSyncTime(spend.last_pull_at) : "尚未讀取";
  // lead 裁決：「帳戶權限失效」沒有後端欄位可判斷，不做、不假——這張卡固定 ok，只印
  // 帳戶數與最近讀取時間。
  return {
    status: "ready",
    tone: "ok",
    badge: "已連接",
    fact: `${bound.length} 個帳戶・最近讀取 ${lastPull}`,
    impacts: [],
    buttonLabel: "查看",
    buttonHref: "/settings?tab=meta",
  };
}

export function budgetCardState(budget: MonthlyBudget, brandId: string): ReadyState {
  const warn = budget.currency === null || budget.uncertainties.length > 0;
  const fact = budget.currency !== null && budget.amount !== null
    ? `月總額 ${formatMoney(budget.amount, budget.currency)}`
    : "幣別與金額尚未設定";
  const href = `/brands/${brandId}/ads`;
  return warn
    ? { status: "ready", tone: "warn", badge: "預算待核實", fact, impacts: ["加預算提議", "約撐得起幾則"], buttonLabel: "去核實", buttonHref: href }
    : { status: "ready", tone: "ok", badge: "已核實", fact, impacts: [], buttonLabel: "查看", buttonHref: href };
}

export function ordersCardState(data: OrdersPageData, brandId: string, today: Date): ReadyState {
  const href = `/brands/${brandId}/orders`;
  const latest = data.orders.items[0]?.order_date ?? null;
  if (!latest) {
    return {
      status: "ready", tone: "warn", badge: "尚未匯入",
      fact: "還沒有任何一筆訂單資料。",
      impacts: ["檢討頁的訂單對照"], buttonLabel: "補報表", buttonHref: href,
    };
  }
  const latestDate = new Date(`${latest}T00:00:00Z`);
  const yesterday = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - 1));
  const fact = `最新到 ${formatMD(latest)}`;
  if (latestDate.getTime() >= yesterday.getTime()) {
    return { status: "ready", tone: "ok", badge: "已更新", fact, impacts: [], buttonLabel: "查看", buttonHref: href };
  }
  const next = new Date(latestDate);
  next.setUTCDate(next.getUTCDate() + 1);
  return {
    status: "ready", tone: "warn", badge: `缺 ${next.getUTCMonth() + 1}/${next.getUTCDate()} 之後`,
    fact, impacts: ["檢討頁的訂單對照"], buttonLabel: "補報表", buttonHref: href,
  };
}

export function productsCardState(products: ProductListItem[], brandId: string): ReadyState {
  const href = `/brands/${brandId}/products`;
  const confirmed = products.filter((p) => p.economics_status === "confirmed").length;
  const fact = `${products.length} 個商品，${confirmed} 個有成本`;
  return confirmed >= 1
    ? { status: "ready", tone: "ok", badge: "可算打平值", fact, impacts: [], buttonLabel: "查看", buttonHref: href }
    : { status: "ready", tone: "warn", badge: "尚未有成本可算", fact, impacts: ["目標購買成本"], buttonLabel: "補成本", buttonHref: href };
}

export function historyCardState(backfill: MetaBackfillStatus, brandId: string): ReadyState {
  const href = `/brands/${brandId}/intake/history`;
  if (backfill.running) {
    return {
      status: "ready", tone: "neutral", badge: "帶入中",
      fact: "背景整理過去的廣告紀錄中，稍後再回來看。",
      impacts: [], buttonLabel: "查看", buttonHref: href,
    };
  }
  if (!backfill.earliest_spend_date || !backfill.latest_spend_date) {
    return {
      status: "ready", tone: "warn", badge: "尚未帶入",
      fact: "還沒有過去的廣告紀錄。",
      impacts: [], buttonLabel: "查看", buttonHref: href,
    };
  }
  const earliest = new Date(`${backfill.earliest_spend_date}T00:00:00Z`);
  const latest = new Date(`${backfill.latest_spend_date}T00:00:00Z`);
  const months = (latest.getUTCFullYear() - earliest.getUTCFullYear()) * 12
    + (latest.getUTCMonth() - earliest.getUTCMonth()) + 1;
  return { status: "ready", tone: "ok", badge: "完成", fact: `已帶入 ${months} 個月`, impacts: [], buttonLabel: "查看", buttonHref: href };
}

/** 平台尚未支援的灰卡——一份頁面自己的清單常數（Feature Decisions：不從共用核心引入，
 * 這頁自己記自己要提的平台名稱）。 */
const UNSUPPORTED_PLATFORMS: { icon: string; name: string }[] = [{ icon: "G", name: "Google Ads" }];

function DataConnections({ brandId }: { brandId: string }) {
  const month = currentBudgetMonth();

  const accountsLoad = useLoad(() => Promise.all([fetchMetaAccounts(), fetchMetaSpend(brandId)]), [brandId]);
  const budgetLoad = useLoad(() => getMonthlyBudget(brandId, month), [brandId, month]);
  const ordersLoad = useLoad(() => fetchOrders(brandId), [brandId]);
  const productsLoad = useLoad(() => fetchProductList(brandId), [brandId]);
  const historyLoad = useLoad(() => fetchMetaBackfillStatus(brandId), [brandId]);

  const cards: { icon: string; title: string; state: ConnectionState }[] = [
    {
      icon: "∞", title: "Meta 廣告帳戶",
      state: toCardState(accountsLoad.state, accountsLoad.reload, ([accounts, spend]) => accountsCardState(accounts, spend, brandId)),
    },
    {
      icon: "💱", title: "Meta 預算金額",
      state: toCardState(budgetLoad.state, budgetLoad.reload, (budget) => budgetCardState(budget, brandId)),
    },
    {
      icon: "🧾", title: "商城訂單報表",
      state: toCardState(ordersLoad.state, ordersLoad.reload, (orders) => ordersCardState(orders, brandId, new Date())),
    },
    {
      icon: "🏷", title: "商品售價與成本",
      state: toCardState(productsLoad.state, productsLoad.reload, (products) => productsCardState(products, brandId)),
    },
    {
      icon: "🗂", title: "過去的廣告紀錄",
      state: toCardState(historyLoad.state, historyLoad.reload, (backfill) => historyCardState(backfill, brandId)),
    },
  ];

  const allSettled = cards.every((c) => c.state.status !== "loading");
  const need = cards.filter((c) => c.state.status === "ready" && c.state.tone === "warn").length;
  const homeHref = `/brands/${brandId}/ads`;

  return (
    <div className="flex max-w-[1180px] flex-col gap-5">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "資料連線" }]} />
      <PageHeader
        title="資料連線"
        description={allSettled ? `${need} 項需要處理` : undefined}
        actions={<Chip tone="ok">🔒 只讀取，不會修改你的廣告</Chip>}
      />
      <div className="grid grid-cols-1 gap-4 min-[1101px]:grid-cols-2">
        {cards.map((card) => (
          <ConnectionCard key={card.title} icon={card.icon} title={card.title} state={card.state} />
        ))}
        {UNSUPPORTED_PLATFORMS.map((platform) => (
          <div
            key={platform.name}
            className="surface flex items-center gap-4 p-5 opacity-55"
            data-testid={`connection-card-unsupported-${platform.name}`}
          >
            <div
              className="grid size-[52px] shrink-0 place-items-center rounded-[14px] bg-muted text-2xl"
              aria-hidden="true"
            >
              {platform.icon}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <b className="text-[15px]">{platform.name}</b>
                <Chip>尚未支援</Chip>
              </div>
              <p className="mt-0.5 text-[13px] text-muted-foreground">接上後開放</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function DataConnectionsPage(props: { brandId: string }) {
  return <DataConnections key={`${getOrgId()}:${props.brandId}`} {...props} />;
}
