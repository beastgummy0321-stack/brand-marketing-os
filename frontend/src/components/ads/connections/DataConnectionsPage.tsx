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

// ---- 本機日曆日期的小工具（lead 修正 2026-09-22）：「今天／昨天」一律比較瀏覽器本機的
// 日曆日，不是 UTC 日——`new Date("YYYY-MM-DD")` 是 UTC 午夜，UTC getter 也是 UTC，兩者
// 跟使用者看到的「今天」在 UTC+8 這種時區會差一天。日期字串固定「YYYY-MM-DD」等寬格式，
// 字串比大小＝時間先後，不用建 Date 就能比較；只有「+1 天」需要真的做日曆運算，
// 用 `new Date(y, m-1, d)`（三個數字的建構子是本機時間，不是字串解析）＋本機 getter。

function parseLocalDateParts(iso: string): { y: number; m: number; d: number } {
  const [y, m, d] = iso.split("-").map(Number);
  return { y, m, d };
}

function formatMD(iso: string): string {
  const { m, d } = parseLocalDateParts(iso);
  return `${m}/${d}`;
}

function addDaysLocal(iso: string, days: number): string {
  const { y, m, d } = parseLocalDateParts(iso);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() + days);
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
}

/** 今天的本機日曆日字串（元件呼叫端用；純函式測試自己灌字串進去，不依賴系統時鐘）。 */
function todayLocalString(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function computeBoundCount(accounts: MetaAccountsData, brandId: string): number {
  return accounts.accounts.filter((a) => a.bound_brand_ids.includes(brandId)).length;
}

// ---- 每張卡各自的資料 → 畫面狀態（純函式，方便直接測；不臆造原型的固定文案，
// 只有「影響」chip 沿用原型固定文案，見 Feature Decisions）。lead 修正 2026-09-22：
// 逐條對照產生欄位的後端程式重新核過一次，原版有六處寫錯。

export function accountsCardState(accounts: MetaAccountsData, spend: MetaSpendSummary, brandId: string): ReadyState {
  const bound = computeBoundCount(accounts, brandId);
  const href = "/settings?tab=meta";
  if (bound === 0) {
    return { status: "ready", tone: "warn", badge: "尚未連接", fact: "還沒有連接廣告帳戶", impacts: [], buttonLabel: "去連接", buttonHref: href };
  }
  const lastPull = spend.last_pull_at ? formatSyncTime(spend.last_pull_at) : "尚未讀取";
  return {
    status: "ready", tone: "ok", badge: "已連接",
    fact: `${bound} 個帳戶・最近讀取 ${lastPull}`,
    impacts: [], buttonLabel: "查看", buttonHref: href,
  };
}

export function budgetCardState(budget: MonthlyBudget, brandId: string): ReadyState {
  const href = `/brands/${brandId}/ads`;
  const impacts = ["加預算提議", "約撐得起幾則"];
  if (budget.amount === null) {
    // 同 MonthlyBudgetPanel.tsx:51 的訊號：amount === null 就是「從沒設定過」。
    return { status: "ready", tone: "warn", badge: "尚未設定", fact: "尚未設定金額。", impacts, buttonLabel: "去核實", buttonHref: href };
  }
  if (budget.currency === null) {
    return { status: "ready", tone: "warn", badge: "預算待核實", fact: `金額 ${budget.amount}，幣別待核實。`, impacts, buttonLabel: "去核實", buttonHref: href };
  }
  // uncertainties 不算 warn（幾乎永遠非空、這顆按鈕也修不了）——lead 修正。
  return { status: "ready", tone: "ok", badge: "已設定", fact: formatMoney(budget.amount, budget.currency), impacts: [], buttonLabel: "查看", buttonHref: href };
}

export function ordersCardState(data: OrdersPageData, brandId: string, todayLocal: string): ReadyState {
  const href = `/brands/${brandId}/orders`;
  const impacts = ["檢討頁的訂單對照"];
  if (data.orders.total === 0) {
    return { status: "ready", tone: "warn", badge: "尚未匯入", fact: "還沒有任何一筆訂單資料。", impacts, buttonLabel: "補報表", buttonHref: href };
  }
  // `ORDER BY order_date DESC` 把 NULL 排最前（app/orders/repository.py:438）——這一頁抓
  // 這一頁第一筆「有日期」的訂單，不是抓第一筆。
  const latest = data.orders.items.find((item) => item.order_date !== null)?.order_date ?? null;
  if (!latest) {
    return { status: "ready", tone: "warn", badge: "日期不明", fact: "這一頁的訂單都沒有日期。", impacts, buttonLabel: "補報表", buttonHref: href };
  }
  const yesterday = addDaysLocal(todayLocal, -1);
  const fact = `最新到 ${formatMD(latest)}`;
  if (latest >= yesterday) {
    return { status: "ready", tone: "ok", badge: "已更新", fact, impacts: [], buttonLabel: "查看", buttonHref: href };
  }
  const next = addDaysLocal(latest, 1);
  return { status: "ready", tone: "warn", badge: `缺 ${formatMD(next)} 之後`, fact, impacts, buttonLabel: "補報表", buttonHref: href };
}

export function productsCardState(products: ProductListItem[], brandId: string): ReadyState {
  const href = `/brands/${brandId}/products`;
  const impacts = ["目標購買成本"];
  // 「可賣」的定義跟產品清單頁一樣：上架中、且不是別列的母產品（母產品本身
  // `economics_status` 固定 "none"，不是真的缺成本，不該被算進分母）。
  const parentIds = new Set(products.map((p) => p.parent_id).filter((id): id is string => Boolean(id)));
  const sellable = products.filter((p) => p.status === "active" && !parentIds.has(p.id));
  const confirmed = sellable.filter((p) => p.economics_status === "confirmed").length;
  const fact = `${sellable.length} 個商品，${confirmed} 個有成本`;
  if (sellable.length === 0) {
    return { status: "ready", tone: "warn", badge: "尚未建立商品", fact, impacts, buttonLabel: "補成本", buttonHref: href };
  }
  if (confirmed >= 1) {
    return { status: "ready", tone: "ok", badge: "可算打平值", fact, impacts: [], buttonLabel: "查看", buttonHref: href };
  }
  return { status: "ready", tone: "warn", badge: "缺成本", fact, impacts, buttonLabel: "補成本", buttonHref: href };
}

/** 過去的廣告紀錄卡的資料：真的讀到的狀態，或「沒有已連接帳戶」這個不打 API 的閘門態
 * （lead 修正：backfill GET 在沒有綁定帳戶時回 409，這裡先看帳戶卡的結果，0 個帳戶就
 * 不送這支請求）。 */
export type HistoryCardInput = MetaBackfillStatus | "no-accounts";

export function historyCardState(input: HistoryCardInput, brandId: string): ReadyState {
  const href = `/brands/${brandId}/intake/history`;
  if (input === "no-accounts") {
    return { status: "ready", tone: "warn", badge: "先連接帳戶", fact: "還沒有已連接的廣告帳戶，無法帶入過去的紀錄。", impacts: [], buttonLabel: "查看", buttonHref: href };
  }
  if (input.running) {
    return { status: "ready", tone: "neutral", badge: "帶入中", fact: "背景整理過去的廣告紀錄中，稍後再回來看。", impacts: [], buttonLabel: "查看", buttonHref: href };
  }
  if (!input.earliest_spend_date) {
    return { status: "ready", tone: "warn", badge: "尚未帶入", fact: "還沒有過去的廣告紀錄。", impacts: [], buttonLabel: "查看", buttonHref: href };
  }
  const earliest = parseLocalDateParts(input.earliest_spend_date);
  const latest = parseLocalDateParts(input.latest_spend_date ?? input.earliest_spend_date);
  const months = (latest.y - earliest.y) * 12 + (latest.m - earliest.m) + 1;
  return { status: "ready", tone: "ok", badge: "完成", fact: `已帶入 ${months} 個月`, impacts: [], buttonLabel: "查看", buttonHref: href };
}

/** 平台尚未支援的灰卡——一份頁面自己的清單常數（Feature Decisions：不從共用核心引入，
 * 這頁自己記自己要提的平台名稱）。 */
const UNSUPPORTED_PLATFORMS: { icon: string; name: string }[] = [{ icon: "G", name: "Google Ads" }];

/** 過去的廣告紀錄卡：只有在已知「至少 1 個已綁定帳戶」時才打 `fetchMetaBackfillStatus`；
 * 帳戶卡還沒讀完（`gate.settled === false`）先停在 loading，帳戶卡讀失敗則視為「不確定
 * 是不是 0」，照常嘗試讀（不因為另一張卡失敗就永遠卡住）。 */
function useHistoryLoad(brandId: string, gate: { settled: boolean; zero: boolean }): { state: LoadState<HistoryCardInput>; reload: () => void } {
  const [state, setState] = useState<LoadState<HistoryCardInput>>({ status: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => {
    if (!gate.settled) {
      setState({ status: "loading" });
      return;
    }
    if (gate.zero) {
      setState({ status: "ready", value: "no-accounts" });
      return;
    }
    let cancelled = false;
    setState({ status: "loading" });
    fetchMetaBackfillStatus(brandId)
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brandId, gate.settled, gate.zero, reloadKey]);
  return { state, reload: () => setReloadKey((v) => v + 1) };
}

function DataConnections({ brandId }: { brandId: string }) {
  const month = currentBudgetMonth();

  const accountsLoad = useLoad(() => Promise.all([fetchMetaAccounts(), fetchMetaSpend(brandId)]), [brandId]);
  const budgetLoad = useLoad(() => getMonthlyBudget(brandId, month), [brandId, month]);
  const ordersLoad = useLoad(() => fetchOrders(brandId), [brandId]);
  const productsLoad = useLoad(() => fetchProductList(brandId), [brandId]);

  const accountsSettled = accountsLoad.state.status !== "loading";
  const boundZero = accountsLoad.state.status === "ready" && computeBoundCount(accountsLoad.state.value[0], brandId) === 0;
  const historyLoad = useHistoryLoad(brandId, { settled: accountsSettled, zero: boundZero });

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
      state: toCardState(ordersLoad.state, ordersLoad.reload, (orders) => ordersCardState(orders, brandId, todayLocalString())),
    },
    {
      icon: "🏷", title: "商品售價與成本",
      state: toCardState(productsLoad.state, productsLoad.reload, (products) => productsCardState(products, brandId)),
    },
    {
      icon: "🗂", title: "過去的廣告紀錄",
      state: toCardState(historyLoad.state, historyLoad.reload, (value) => historyCardState(value, brandId)),
    },
  ];

  const allSettled = cards.every((c) => c.state.status !== "loading");
  // header：warn 卡＋讀取失敗的卡都算「需要處理」（lead 修正）。
  const need = cards.filter((c) => (c.state.status === "ready" && c.state.tone === "warn") || c.state.status === "error").length;
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
            className="surface bg-muted flex items-center gap-4 p-5 opacity-55"
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
