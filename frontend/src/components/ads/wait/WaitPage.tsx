import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { formatSyncTime } from "@/lib/format";
import { listCampaigns, type CampaignSyncState } from "@/lib/adsApi";
import { getTriage, type TriageItem } from "@/lib/adsTriageApi";
import { syncCampaign, syncJob } from "@/lib/adsExternalApi";
import { fetchOrders } from "@/lib/ordersApi";
import { ActionBar, Chip, DayTiles, ResultHero, TodoRow } from "../patterns";

/** 本機日曆日期小工具（同 `connections/DataConnectionsPage.tsx` 的先例，各自留一份，見那個
 * 檔案頂端的註解）——這頁在 `do_not_touch` 之外，沒有共用 lib 可以進出。 */
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
function todayLocalString(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}
function last7Days(endIso: string): string[] {
  const days: string[] = [];
  for (let i = 6; i >= 0; i -= 1) days.push(addDaysLocal(endIso, -i));
  return days;
}

/** `TodoRow` 的 `no` 只收數字（`patterns/**` 是這張票的 `do_not_touch`）——原型這幾列的「編號」
 * 一直都是圖示（🔌／📅／🧾／⏳），不是序數；用型別斷言把圖示塞進同一個插槽，不是另刻一份
 * `TodoRow`。 */
function iconSlot(icon: string): number {
  return icon as unknown as number;
}

const REASON_TEXT: Record<string, { title: string; subtitle: string }> = {
  below_sample_gate: { title: "樣本還不夠", subtitle: "每則廣告的花費或成果數還沒過門檻，累積中" },
  no_previous_window: {
    title: "缺前一期可比資料",
    subtitle: "預設只同步 30 天，28 天窗沒有前一期可比；手動同步更早的區間才能補",
  },
  result_unknown_days: { title: "成果數未知", subtitle: "平台沒回報這幾天的成果" },
};
// Feature Decisions 列出的順序——固定，不是後端回傳順序。
const REASON_ORDER = ["below_sample_gate", "no_previous_window", "result_unknown_days"] as const;

interface Row {
  key: string;
  emoji: string;
  title: string;
  subtitle: string;
  action?: { label: string; href: string };
}

/** 三個一定存在的事實列 + 「全部資料不足」時每個 `reason_code` 一列（Feature Decisions
 * 「Wait page」）——沒有 missing_days 才會顯示 reason_code 列，`missing_days` 本身已經解釋了
 * 「資料不足」的原因，兩邊不重複列。 */
function buildRows(brandId: string, sync: CampaignSyncState, coverage: { start: string; end: string } | null, missingDays: string[], items: TriageItem[], ordersLatest: string | null): Row[] {
  const rows: Row[] = [];
  if (sync.state === "disconnected") {
    rows.push({
      key: "disconnected", emoji: "🔌", title: "廣告帳戶未連接", subtitle: "重新連接後會自動補資料",
      action: { label: "去連接", href: `/brands/${brandId}/ads/connections` },
    });
  }
  if (missingDays.length > 0) {
    rows.push({
      key: "missing", emoji: "📅",
      title: `缺 ${missingDays.map(formatMD).join("、")}（${missingDays.length} 天）`,
      subtitle: "同步恢復後自動補",
    });
  }
  if (coverage && ordersLatest !== null && ordersLatest < coverage.end) {
    rows.push({
      key: "orders", emoji: "🧾", title: `商城報表只到 ${formatMD(ordersLatest)}`,
      subtitle: `補到 ${formatMD(coverage.end)} 才能對照訂單`,
      action: { label: "補報表", href: `/brands/${brandId}/orders` },
    });
  }
  if (missingDays.length === 0 && items.length > 0 && items.every((item) => item.class === "insufficient")) {
    const present = new Set(items.map((item) => item.reason_code));
    for (const code of REASON_ORDER) {
      if (present.has(code)) {
        const text = REASON_TEXT[code];
        rows.push({ key: code, emoji: "⏳", title: text.title, subtitle: text.subtitle });
      }
    }
  }
  return rows;
}

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "not_found" }
  | {
      status: "ready";
      campaignName: string;
      sync: CampaignSyncState;
      coverage: { start: string; end: string } | null;
      missingDays: string[];
      items: TriageItem[];
      ordersLatest: string | null;
    };

/** 資料不足 wait page（F24-I03，v7 原型 `waitPage()`）：首頁卡片與活動工作區在
 * `sync.state !== "disconnected"` 且「全部資料不足或缺天」時導來這裡——只列出真的存在的
 * 事實，不是每個活動都畫同一組列（Feature Decisions「Wait page」）。 */
export function WaitPage({ brandId, campaignId }: { brandId: string; campaignId: string }) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  const [busy, setBusy] = useState(false);
  const [syncId, setSyncId] = useState<string | null>(null);
  const [syncActionError, setSyncActionError] = useState<string | null>(null);
  const lifetime = useRef(new AbortController());
  useEffect(() => {
    lifetime.current = new AbortController();
    return () => lifetime.current.abort();
  }, []);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    Promise.all([
      listCampaigns(brandId),
      getTriage(brandId, campaignId),
      // review 先例（`CampaignDetailPage.tsx`）：訂單只餵一顆選用的列，讀失敗不該拖累整頁
      // （design-system §1.7 self-check 9）。
      fetchOrders(brandId).catch(() => null),
    ])
      .then(([campaigns, triage, orders]) => {
        if (cancelled) return;
        const campaign = campaigns.find((c) => c.id === campaignId);
        if (!campaign) {
          setState({ status: "not_found" });
          return;
        }
        const data = triage.data;
        const ordersLatest = orders ? orders.orders.items.find((item) => item.order_date !== null)?.order_date ?? null : null;
        setState({
          status: "ready",
          campaignName: campaign.name,
          sync: data?.sync ?? { state: "never", error: null, last_success_at: null },
          coverage: data?.coverage ?? null,
          missingDays: data?.missing_days ?? [],
          items: triage.items,
          ordersLatest,
        });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({ status: "error", message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。" });
      });
    return () => {
      cancelled = true;
    };
  }, [brandId, campaignId, reloadKey]);

  // 重新檢查＝跟 `CampaignWorkspace.tsx` 同一支：`syncCampaign` 預設 body，回傳的 job id
  // 進 poll，直到不是 pending／running 才重新讀這頁。
  async function recheck() {
    if (busy) return;
    setBusy(true);
    setSyncActionError(null);
    const signal = lifetime.current.signal;
    try {
      const result = await syncCampaign(brandId, campaignId);
      if (!signal.aborted) setSyncId(result.job.id);
    } catch (err) {
      if (!signal.aborted) {
        setSyncActionError(err instanceof Error ? err.message : "重新檢查失敗。");
        setBusy(false);
      }
    }
  }
  useEffect(() => {
    if (!syncId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await syncJob(brandId, syncId!, controller.signal);
        if (controller.signal.aborted) return;
        if (["pending", "running"].includes(result.job.status)) {
          timer = setTimeout(() => void poll(), 3000);
        } else {
          setSyncId(null);
          setBusy(false);
          if (result.job.error) setSyncActionError(result.job.error);
          setReloadKey((k) => k + 1);
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          setSyncActionError(err instanceof Error ? err.message : "同步狀態讀取失敗。");
          setSyncId(null);
          setBusy(false);
        }
      }
    }
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [syncId, brandId]);

  const homeHref = `/brands/${brandId}/ads`;
  const campaignHref = `/brands/${brandId}/ads/campaigns/${campaignId}`;

  if (state.status === "loading") {
    return (
      <div className="flex max-w-[1180px] flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "資料不足" }]} />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="flex max-w-[1180px] flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "資料不足" }]} />
        <EmptyState title="讀取失敗" description={state.message} onAction={() => setReloadKey((v) => v + 1)} actionLabel="重新讀取" />
      </div>
    );
  }
  if (state.status === "not_found") {
    return (
      <div className="flex max-w-[1180px] flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "資料不足" }]} />
        <EmptyState title="讀取失敗" description="找不到這個 Campaign。" onAction={() => setReloadKey((v) => v + 1)} actionLabel="重新讀取" />
      </div>
    );
  }

  const { campaignName, sync, coverage, missingDays, items, ordersLatest } = state;
  const rows = buildRows(brandId, sync, coverage, missingDays, items, ordersLatest);
  const tiles = last7Days(coverage?.end ?? todayLocalString());
  const missingSet = new Set(missingDays);
  const hint = sync.state !== "never" && sync.last_success_at ? `最近同步 ${formatSyncTime(sync.last_success_at)}` : "尚未同步";

  return (
    <div className="flex max-w-[1180px] flex-col gap-4">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: campaignName }]} />

      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <ResultHero tone="warn" mark="…" title="資料不足，這個活動先不判斷" note={campaignName} />
        </div>
        <Chip tone="warn" className="shrink-0">平台照常投放，不受影響</Chip>
      </div>

      {rows.length > 0 && (
        <div className="rounded-xl border border-border bg-card px-6">
          {rows.map((row) => (
            <TodoRow
              key={row.key}
              no={iconSlot(row.emoji)}
              action={
                row.action ? (
                  <Button variant="outline" size="sm" asChild>
                    <Link to={row.action.href}>{row.action.label} →</Link>
                  </Button>
                ) : (
                  <Chip tone="neutral">自動</Chip>
                )
              }
            >
              <b className="font-semibold">{row.title}</b>
              <div className="text-[13px] text-muted-foreground">{row.subtitle}</div>
            </TodoRow>
          ))}
        </div>
      )}

      <div className="surface p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-[15px] font-semibold">最近 7 天</h2>
          <Link to={campaignHref} className="text-xs text-muted-foreground underline-offset-4 hover:underline">之前的紀錄仍可查看</Link>
        </div>
        <div className="mt-3">
          <DayTiles days={tiles} missing={missingSet} />
        </div>
      </div>

      {syncActionError && <p role="alert" className="text-sm text-destructive">{syncActionError}</p>}

      <ActionBar
        back={<Button variant="ghost" asChild><Link to={homeHref}>← 投放中心</Link></Button>}
        hint={hint}
      >
        <Button disabled={busy} onClick={() => void recheck()}>{busy ? "檢查中…" : "重新檢查 →"}</Button>
      </ActionBar>
    </div>
  );
}
