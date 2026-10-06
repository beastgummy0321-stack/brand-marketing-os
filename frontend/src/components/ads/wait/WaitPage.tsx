import { campaignPath } from "@/lib/adsRoutes";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { formatInstant, useOrgClock } from "@/lib/orgClock";
import { cn } from "@/lib/utils";
import { listCampaigns, type CampaignLifecycle, type CampaignSyncState } from "@/lib/adsApi";
import { getTriage, type CampaignDataStatus, type TriageDayState, type TriageItem } from "@/lib/adsTriageApi";
import { syncCampaign } from "@/lib/adsExternalApi";
import { getConnections, type AdsConnections } from "@/lib/adsConnectionsApi";
import { useSyncOutcome } from "@/lib/useSyncOutcome";
import { ActionBar, Chip, Legend, ResultHero, TodoRow, useAdsRules, type AdsRules } from "../patterns";

/** `YYYY-MM-DD` → `M/D` (formatting only; the page does no date arithmetic — every day it prints is served). */
function formatMD(iso: string): string {
  const [, m, d] = iso.split("-").map(Number);
  return `${m}/${d}`;
}

/** `TodoRow` 的 `no` 只收數字（`patterns/**` 不在這張票的 touch）——原型這幾列的「編號」一直都是圖示
 * （🔌／📅／🧾／⏳），不是序數；用型別斷言把圖示塞進同一個插槽，不是另刻一份 `TodoRow`。 */
function iconSlot(icon: string): number {
  return icon as unknown as number;
}

type RowAction = { kind: "link"; label: string; href: string } | { kind: "resync" };

interface Row {
  key: string;
  emoji: string;
  title: string;
  subtitle: string;
  action?: RowAction;
  /** A fact the system fixes by itself (no exit): the 「自動」 chip. Reason rows without an exit print nothing. */
  auto?: boolean;
  /** A waiting `reason_code` row (Contract Q), not a fact row. */
  reason?: boolean;
}

/** F49 Contract Q (wait reasons): the ads that wait for something — every ad except the ones already judged (a trend
 * was computed, `change_pct`, or it is 沒賣出). Their `reason_code`s, first appearance first (the order triage serves
 * them), one row each; the words and the exit are the served `rules.reasons[code]` (`fix`). */
function waitingCodes(items: TriageItem[]): string[] {
  const codes: string[] = [];
  for (const item of items) {
    if (item.change_pct !== null || item.grade === "wasted") continue;
    if (!codes.includes(item.reason_code)) codes.push(item.reason_code);
  }
  return codes;
}

function reasonAction(fix: AdsRules["reasons"][string]["fix"] | undefined, brandId: string, campaignHref: string): RowAction | undefined {
  if (fix === "resync") return { kind: "resync" };
  if (fix === "connections") return { kind: "link", label: "去資料連線", href: `/brands/${brandId}/ads/connections` };
  if (fix === "cap") return { kind: "link", label: "去策略設定", href: `${campaignHref}?tab=strategy` };
  return undefined; // `wait` and null: nothing to press here
}

/** The fact rows that really exist (Feature Decisions 「Wait page」), then one row per waiting `reason_code`. */
function buildRows(brandId: string, campaignHref: string, sync: CampaignSyncState, coverage: { start: string; end: string } | null, missingDays: string[], items: TriageItem[], ordersMissing: string[], rules: AdsRules | null): Row[] {
  const rows: Row[] = [];
  if (sync.state === "disconnected") {
    rows.push({
      key: "disconnected", emoji: "🔌", title: "廣告帳戶未連接", subtitle: "重新連接後會自動補資料",
      action: { kind: "link", label: "去連接", href: `/brands/${brandId}/ads/connections` },
    });
  } else if (sync.state === "auth_expired") {
    // F27-I21: 讀取失敗的段落自己存的 error_code 讀成授權錯誤——重新授權走既有的 Meta 連線入口
    // （`DataConnectionsPage.tsx`／`PublishPage.tsx` 同一個 `/settings?tab=meta`）。
    rows.push({
      key: "auth_expired", emoji: "🔌", title: "Meta 讀取權限失效", subtitle: "重新授權後會自動補資料",
      action: { kind: "link", label: "重新授權", href: "/settings?tab=meta" },
    });
  }
  if (missingDays.length > 0) {
    rows.push({
      key: "missing", emoji: "📅", auto: true,
      title: `缺 ${missingDays.map(formatMD).join("、")}（${missingDays.length} 天）`,
      subtitle: "同步恢復後自動補",
    });
  }
  // F31-I07：訂單缺口跟資料連線頁同一條規則——`GET …/connections` 的 `orders.missing_days`
  // （匯入已經涵蓋、當天沒有訂單的日子不算缺），只看這個活動覆蓋範圍內的那幾天。
  const ordersGap = coverage ? ordersMissing.filter((day) => day >= coverage.start && day <= coverage.end) : [];
  if (coverage && ordersGap.length > 0) {
    rows.push({
      key: "orders", emoji: "🧾", title: `商城報表從 ${formatMD(ordersGap[0])} 起還沒補`,
      subtitle: `補到 ${formatMD(coverage.end)} 才能對照訂單`,
      action: { kind: "link", label: "補報表", href: `/brands/${brandId}/orders` },
    });
  }
  // F49 Contract Q: every waiting code, words from the served table (empty while the rules load — no fallback).
  for (const code of waitingCodes(items)) {
    const reason = rules?.reasons[code];
    rows.push({
      key: `reason:${code}`, emoji: "⏳", reason: true, title: reason?.title ?? "", subtitle: reason?.text ?? "",
      action: reasonAction(reason?.fix, brandId, campaignHref),
    });
  }
  return rows;
}

/** A read that broke (F49 Contract O): the hero prints the served status sentence and the read's own error. */
const BROKEN_READ: ReadonlySet<CampaignSyncState["state"]> = new Set(["failed", "auth_expired", "disconnected"]);

type Hero = { tone: "warn" | "ok" | "neutral" | "bad"; mark: string; title: string; note?: string };

/** F47-I06 / F49: the title follows what the data says. A draft has nothing to read; a broken read says so with its
 * reason (never 資料齊了); a fact row (a gap, a missing report) keeps 資料不足; no gap and some ad judged says the
 * numbers are in, naming the served window — the reason rows then explain only the ads still waiting (or a trend
 * footnote such as 沒有上一段可以比), not the whole campaign. */
function waitHero(lifecycle: CampaignLifecycle | null, sync: CampaignSyncState, status: CampaignDataStatus | null, rows: Row[], items: TriageItem[], days: TileDay[]): Hero {
  if (lifecycle?.state === "draft") return { tone: "neutral", mark: "…", title: "這個活動還沒上架，沒有平台資料可讀" };
  if (BROKEN_READ.has(sync.state)) {
    return { tone: "bad", mark: "!", title: status?.label || "這次沒讀到平台資料", note: sync.error ?? undefined };
  }
  if (rows.some((row) => !row.reason)) return { tone: "warn", mark: "…", title: "資料不足，這個活動先不判斷" };
  if (sync.state === "never") return { tone: "neutral", mark: "…", title: "還沒同步過，先不判斷", note: "按「重新檢查」讀一次平台的數字" };
  if (items.some((item) => item.grade !== "insufficient" && item.grade !== "no_target")) {
    const read = days.length > 0 && days.every((d) => d.state !== "missing");
    return {
      tone: "ok", mark: "✓", title: "資料齊了，可以回活動看判讀",
      note: read ? `${formatMD(days[0].day)}～${formatMD(days[days.length - 1].day)} 每天都讀過` : undefined,
    };
  }
  if (items.length === 0) return { tone: "neutral", mark: "…", title: "還沒有廣告數字，先不判斷", note: "平台開始花錢後，下次同步會出現第一筆數字" };
  return { tone: "warn", mark: "…", title: "資料不足，這個活動先不判斷" };
}

interface TileDay { day: string; state: TriageDayState }

/** F49 Contract V: one tile per served day, three states — the shared `DayTiles` knows two (data／gap). */
const TILE: Record<TriageDayState, { word: string; box: string; swatch: string }> = {
  data: { word: "有資料", box: "bg-primary text-primary-foreground", swatch: "bg-primary" },
  empty: { word: "讀過・沒花費", box: "bg-muted text-muted-foreground", swatch: "bg-muted" },
  missing: { word: "缺", box: "border border-dashed border-danger bg-card text-danger", swatch: "border border-dashed border-danger bg-card" },
};

function ReadDays({ days }: { days: TileDay[] }) {
  const present = (Object.keys(TILE) as TriageDayState[]).filter((s) => days.some((d) => d.state === s));
  return (
    <>
      <div data-slot="day-tiles" className="flex flex-wrap gap-1" aria-label="每日資料">
        {days.map((d) => (
          <i key={d.day} data-state={d.state} title={`${d.day} ${TILE[d.state].word}`} aria-label={`${d.day} ${TILE[d.state].word}`}
            className={cn("grid size-10 place-items-center rounded-md text-[13px] not-italic", TILE[d.state].box)}>
            {Number(d.day.slice(-2))}
          </i>
        ))}
      </div>
      {present.length > 1 && <Legend className="mt-2" items={present.map((s) => ({ label: TILE[s].word, swatch: TILE[s].swatch }))} />}
    </>
  );
}

/** One re-read the user asked for (F49 Contract O): mounted after the POST, so its outcome read starts fresh and
 * follows `useSyncOutcome` until the read finished; then it hands the outcome up once. */
function RecheckOutcome({ brandId, campaignId, onSettled }: { brandId: string; campaignId: string; onSettled: (result: { state: string; text: string }) => void }) {
  const outcome = useSyncOutcome({ brandId, campaignId });
  const settled = useRef(false);
  useEffect(() => {
    if (settled.current) return;
    if (outcome.error) {
      settled.current = true;
      onSettled({ state: "failed", text: outcome.error });
    } else if (outcome.state !== null && outcome.state !== "running") {
      settled.current = true;
      onSettled({ state: outcome.state, text: outcome.text });
    }
  }, [outcome.state, outcome.text, outcome.error, onSettled]);
  return outcome.text ? <p className="text-sm text-muted-foreground" aria-live="polite">{outcome.text}</p> : null;
}

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "not_found" }
  | {
      status: "ready";
      campaignName: string;
      lifecycle: CampaignLifecycle | null;
      sync: CampaignSyncState;
      dataStatus: CampaignDataStatus | null;
      coverage: { start: string; end: string } | null;
      missingDays: string[];
      days: TileDay[];
      items: TriageItem[];
      /** The `orders` source's `missing_days` from `GET …/connections` (the one orders-coverage rule). */
      ordersMissing: string[];
    };

/** 資料不足 wait page（F24-I03，v7 原型 `waitPage()`）：只列出真的存在的事實與每個等待原因（F49 Contract Q），
 * 格子畫後端讀過的日子（Contract V），重新讀取照 `useSyncOutcome` 說結果（Contract O），依活動一生給出口
 * （Contract L：草稿去準備、已結束去結案）。 */
export function WaitPage({ brandId, campaignId }: { brandId: string; campaignId: string }) {
  const { timezone } = useOrgClock();
  const [state, setState] = useState<State>({ status: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  const [posting, setPosting] = useState(false);
  const [recheckRound, setRecheckRound] = useState(0);
  const [recheckResult, setRecheckResult] = useState<{ state: string; text: string } | null>(null);
  const rules = useAdsRules();
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
      getConnections(brandId).catch((): AdsConnections | null => null),
    ])
      .then(([campaigns, triage, connections]) => {
        if (cancelled) return;
        const campaign = campaigns.find((c) => c.id === campaignId);
        if (!campaign) {
          setState({ status: "not_found" });
          return;
        }
        const data = triage.data;
        const ordersMissing = connections?.sources.find((source) => source.kind === "orders")?.missing_days ?? [];
        setState({
          status: "ready",
          campaignName: campaign.name,
          lifecycle: campaign.lifecycle ?? null,
          sync: data?.sync ?? { state: "never", error: null, last_success_at: null },
          dataStatus: data?.status ?? null,
          coverage: data?.coverage ?? null,
          missingDays: data?.missing_days ?? [],
          days: data?.days ?? [],
          items: triage.items,
          ordersMissing,
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

  // 重新檢查＝跟 `CampaignWorkspace.tsx` 同一支 `syncCampaign`；送出後掛上 `RecheckOutcome` 跟著讀結果。
  async function recheck() {
    if (posting || recheckRound > 0) return;
    setPosting(true);
    setRecheckResult(null);
    const signal = lifetime.current.signal;
    try {
      await syncCampaign(brandId, campaignId);
      if (!signal.aborted) setRecheckRound((n) => n + 1);
    } catch (err) {
      if (!signal.aborted) setRecheckResult({ state: "failed", text: err instanceof Error ? err.message : "重新檢查失敗。" });
    } finally {
      if (!signal.aborted) setPosting(false);
    }
  }
  const settleRecheck = useCallback((result: { state: string; text: string }) => {
    setRecheckResult(result);
    setRecheckRound(0);
    setReloadKey((k) => k + 1);
  }, []);
  const busy = posting || recheckRound > 0;

  const homeHref = `/brands/${brandId}/ads`;
  const campaignHref = campaignPath(brandId, campaignId);

  if (state.status === "loading") {
    return (
      <div className="flex max-w-[1180px] flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "資料狀況" }]} />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (state.status === "error") {
    return (
      <div className="flex max-w-[1180px] flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "資料狀況" }]} />
        <EmptyState title="讀取失敗" description={state.message} onAction={() => setReloadKey((v) => v + 1)} actionLabel="重新讀取" />
      </div>
    );
  }
  if (state.status === "not_found") {
    return (
      <div className="flex max-w-[1180px] flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "資料狀況" }]} />
        <EmptyState title="讀取失敗" description="找不到這個 Campaign。" onAction={() => setReloadKey((v) => v + 1)} actionLabel="重新讀取" />
      </div>
    );
  }

  const { campaignName, lifecycle, sync, dataStatus, coverage, missingDays, days, items, ordersMissing } = state;
  const draft = lifecycle?.state === "draft";
  // Closeout exists only for an internal campaign (`can_close`); an imported ended campaign has none.
  const ended = lifecycle?.state === "ended" && lifecycle.can_close;
  // A draft is on no platform: no fact rows, no tiles, nothing to re-read (drill-11 B7).
  const rows = draft ? [] : buildRows(brandId, campaignHref, sync, coverage, missingDays, items, ordersMissing, rules);
  const hint = sync.state !== "never" && sync.last_success_at ? `最近同步 ${formatInstant(sync.last_success_at, timezone, "md_hm")}` : "尚未同步";
  const hero = waitHero(lifecycle, sync, dataStatus, rows, items, days);
  const recheckFailed = recheckResult !== null && (recheckResult.state === "failed" || recheckResult.state === "partial");

  return (
    <div className="flex max-w-[1180px] flex-col gap-4">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: campaignName }]} />

      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <ResultHero tone={hero.tone} mark={hero.mark} title={hero.title} note={hero.note ? `${campaignName}・${hero.note}` : campaignName} />
        </div>
        {lifecycle?.state === "live" && <Chip tone="warn" className="shrink-0">平台照常投放，不受影響</Chip>}
      </div>

      {rows.length > 0 && (
        <div className="rounded-xl border border-border bg-card px-6">
          {rows.map((row) => (
            <TodoRow
              key={row.key}
              no={iconSlot(row.emoji)}
              action={
                row.action?.kind === "link" ? (
                  <Button variant="outline" size="sm" asChild>
                    <Link to={row.action.href}>{row.action.label} →</Link>
                  </Button>
                ) : row.action?.kind === "resync" ? (
                  <Button variant="outline" size="sm" busy={busy} onClick={() => void recheck()}>重新檢查 →</Button>
                ) : row.auto ? (
                  <Chip tone="neutral">自動</Chip>
                ) : undefined
              }
            >
              <b className="font-semibold">{row.title}</b>
              <div className="text-[13px] text-muted-foreground">{row.subtitle}</div>
            </TodoRow>
          ))}
        </div>
      )}

      {!draft && days.length > 0 && (
        <div className="surface p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-[15px] font-semibold">{`${formatMD(days[0].day)}～${formatMD(days[days.length - 1].day)}`}</h2>
            <Link to={campaignHref} className="text-xs text-muted-foreground underline-offset-4 hover:underline">之前的紀錄仍可查看</Link>
          </div>
          <div className="mt-3">
            <ReadDays days={days} />
          </div>
        </div>
      )}

      {recheckRound > 0 && <RecheckOutcome key={recheckRound} brandId={brandId} campaignId={campaignId} onSettled={settleRecheck} />}
      {recheckRound === 0 && recheckResult && (
        recheckFailed
          ? <p role="alert" className="text-sm text-destructive">{recheckResult.text}</p>
          : <p role="status" className="text-sm text-muted-foreground">{recheckResult.text}</p>
      )}

      <ActionBar
        back={<Button variant="ghost" asChild><Link to={homeHref}>← 投放中心</Link></Button>}
        hint={draft ? undefined : hint}
      >
        {draft ? (
          <Button asChild><Link to={campaignHref}>回活動繼續準備 →</Link></Button>
        ) : ended ? (
          <>
            <Button variant="outline" busy={busy} onClick={() => void recheck()}>{busy ? "檢查中…" : "重新檢查"}</Button>
            <Button asChild><Link to={`${campaignHref}?tab=perf&close=1`}>結案這一期 →</Link></Button>
          </>
        ) : (
          <Button busy={busy} onClick={() => void recheck()}>{busy ? "檢查中…" : "重新檢查 →"}</Button>
        )}
      </ActionBar>
    </div>
  );
}
