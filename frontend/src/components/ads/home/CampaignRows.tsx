import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Skeleton } from "@/components/layout/Skeleton";
import type { HomeCampaign, HomeCap, HomeHandoff, HomeOverview } from "@/lib/adsHomeApi";
import type { CampaignDataState } from "@/lib/adsTriageApi";
import { Chip, MoneyMeter, MoneyTag, formatAmount } from "../patterns";
import { cn } from "@/lib/utils";
import { formatInstant, useOrgClock } from "@/lib/orgClock";
import { wholeYuan } from "./MonthMoney";
import { monthDay } from "./NextDates";

/** v10 home campaign rows (prototype v10 `homeCamps()`, `.ct`): every campaign that is not closed — live, ended and
 * imported first by this month's spend, then drafts by start date (order from `GET …/home`). The campaign name opens
 * its workspace; beside it the served `lifecycle.label` (F49 Contract L). The row's action is the one next step
 * (打開／重新連線／結案這一期／繼續準備). 「在投」 is the served `running` count and is said only while the campaign is
 * live; an ended one shows its closeout step instead. An approved change still waiting on the platform side shows as
 * a chip to the 變更與核對 tab (`handoff`); why a campaign's numbers are missing or partial is the row's own
 * `data_status.label`, never re-derived here. */

const GRID = "grid grid-cols-[minmax(0,2.2fr)_minmax(0,1.2fr)_minmax(0,1.6fr)_minmax(0,.8fr)_120px] items-center gap-4 px-6";
/** Data states whose fix is on the connections page (the row's action becomes 重新連線). */
const RECONNECT = new Set<CampaignDataState>(["partial", "failed", "auth_expired", "disconnected"]);
/** Data states that qualify the row's numbers: said once beside the name. `ready` needs nothing; `no_rows` is said
 * where the spend would be. */
const NOTED = new Set<CampaignDataState>(["partial", "syncing", "never", "failed", "auth_expired", "disconnected"]);

function capLabel(cap: HomeCap | null): string | null {
  if (!cap) return null;
  return `${cap.basis === "break_even" ? "暫用打平" : "上限"} ${formatAmount(cap.value)}`;
}

/** The backend's one sentence, without its closing 。 inside a chip. */
function sentence(label: string): string {
  return label.replace(/。$/, "");
}

/** The row's missing-data chip: a partial month names its unread days (prototype 「9/17、9/18 沒抓到資料」, a long gap
 * prints its size) from `data_status.missing_days`; every other state is the backend's own sentence. */
function dataChipText(status: HomeCampaign["data_status"]): string {
  if (status.state === "partial" && status.missing_days.length) {
    const md = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`;
    const days = status.missing_days;
    return days.length <= 3 ? `${days.map(md).join("、")} 沒抓到資料` : `${days.length} 天沒抓到資料`;
  }
  return sentence(status.label);
}

/** Prototype `handoffChip(c)`: 「等你到 Meta 完成」 while an approved item is not done on the platform, 「等核對」 while
 * the readback has not confirmed it; both open the campaign's 變更與核對 tab. */
function HandoffChip({ brandId, campaignId, handoff }: { brandId: string; campaignId: string; handoff: HomeHandoff | null }) {
  if (!handoff) return null;
  const check = handoff.state === "check";
  return (
    <Button asChild variant="link" className="h-auto p-0 no-underline hover:no-underline">
      <Link to={`/brands/${brandId}/ads/campaigns/${campaignId}?tab=changes`}>
        <Chip tone={check ? "warn" : "accent"}>{check ? "等核對" : "等你到 Meta 完成"} →</Chip>
      </Link>
    </Button>
  );
}

/** 「10/3 14:20」 on the org clock (a structure read's time; F50 Contract K). */
function readTime(iso: string, timezone: string): string {
  return `${formatInstant(iso, timezone, "md")} ${formatInstant(iso, timezone, "hm")}`;
}

/** The campaign's served lifecycle word as a chip (nothing while a read predates it). */
function LifecycleChip({ c }: { c: HomeCampaign }) {
  if (!c.lifecycle) return null;
  return <Chip tone={c.lifecycle.state === "ended" ? "warn" : "neutral"} data-state={c.lifecycle.state}>{c.lifecycle.label}</Chip>;
}

/** 「在投 N 則」 from the served `running` (drill-11 E5: a count read before the user's last report says when it was
 * read; ads whose platform status is unknown are said apart, never folded into 0). */
function runningText(c: HomeCampaign, timezone: string): string {
  const running = c.running ?? { count: c.active_ads, unknown: 0, read_at: null, stale: false };
  const parts = [`在投 ${running.count} 則`];
  if (running.unknown > 0) parts.push(`另有 ${running.unknown} 則狀態不明`);
  if (running.stale) parts.push(running.read_at ? `上次讀取 ${readTime(running.read_at, timezone)}` : "還沒讀到平台上的廣告");
  return parts.join("・");
}

/** The month's empty rows: no campaign in progress; the ones closed this month are named, never 「還沒有活動」. */
function EmptyRows({ brandId, closed }: { brandId: string; closed: number }) {
  if (closed <= 0) return <p className="border-t border-border px-6 py-3.5 text-sm text-muted-foreground">還沒有活動</p>;
  return (
    <p className="border-t border-border px-6 py-3.5 text-sm text-muted-foreground">
      這個月沒有進行中的活動・
      <Link to={`/brands/${brandId}/ads/campaigns`} className="font-medium text-primary hover:underline">已結案 {closed} 個</Link>
    </p>
  );
}

export function CampaignRows({ brandId, state, onRetry }: {
  brandId: string;
  state: { status: "loading" } | { status: "error" } | { status: "ready"; home: HomeOverview };
  onRetry: () => void;
}) {
  const campaigns = state.status === "ready" ? state.home.campaigns : null;
  return (
    <section aria-label="活動" data-testid="campaign-grid" className="surface py-2">
      <div className={cn(GRID, "py-2.5 text-xs text-muted-foreground")}>
        <span>活動</span><span>花了多少</span><span>每賣一筆花多少（線＝這個活動的上限）</span><span>購買</span>
        <span className="text-right">
          <Button asChild variant="link" className="h-auto p-0 text-xs"><Link to={`/brands/${brandId}/ads/campaigns`}>全部活動 →</Link></Button>
        </span>
      </div>
      {state.status === "loading" && [0, 1].map((k) => (
        <div key={k} className="border-t border-border px-6 py-3.5"><Skeleton className="h-9 w-full" /></div>
      ))}
      {(state.status === "error" || (state.status === "ready" && campaigns === null)) && (
        <div className="flex flex-wrap items-center gap-3 border-t border-border px-6 py-3.5">
          <p role="alert" className="text-sm text-muted-foreground">活動暫時讀取不到</p>
          <Button variant="outline" size="sm" onClick={onRetry}>重新讀取</Button>
        </div>
      )}
      {state.status === "ready" && campaigns && campaigns.length === 0 && (
        <EmptyRows brandId={brandId} closed={state.home.closed_this_month ?? 0} />
      )}
      {state.status === "ready" && campaigns?.map((c) => (
        c.draft ? <DraftRow key={c.campaign_id} brandId={brandId} c={c} /> : <LiveRow key={c.campaign_id} brandId={brandId} c={c} spent={state.home.spent} />
      ))}
    </section>
  );
}

function NameLink({ brandId, c }: { brandId: string; c: HomeCampaign }) {
  return (
    <Button asChild variant="link" className="h-auto min-w-0 shrink justify-start p-0 text-left text-sm font-semibold whitespace-normal text-foreground [overflow-wrap:anywhere]">
      <Link to={`/brands/${brandId}/ads/campaigns/${c.campaign_id}`}>{c.name}</Link>
    </Button>
  );
}

function LiveRow({ brandId, c, spent }: { brandId: string; c: HomeCampaign; spent: number | null }) {
  const { timezone } = useOrgClock();
  const status = c.data_status;
  const reconnect = RECONNECT.has(status.state);
  const tl = capLabel(c.cap);
  const cap = c.cap && c.cap.basis ? { value: c.cap.value, basis: c.cap.basis } : null;
  // An ended campaign's next step is its closeout (the same link as its queue row), not another look at the numbers.
  const closeout = c.lifecycle?.state === "ended" && c.lifecycle.can_close;
  const running = c.running?.count ?? c.active_ads;
  return (
    <div className={cn(GRID, "border-t border-border py-3.5")}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <NameLink brandId={brandId} c={c} />
          <LifecycleChip c={c} />
          <HandoffChip brandId={brandId} campaignId={c.campaign_id} handoff={c.handoff} />
          {NOTED.has(status.state) && <Chip tone="warn" data-state={status.state}>{dataChipText(status)}</Chip>}
        </div>
        {c.lifecycle && c.lifecycle.state !== "live" ? (
          running > 0 && <div className="numeric text-sm text-muted-foreground">平台上還開著 {running} 則</div>
        ) : (
          <div className="numeric text-sm text-muted-foreground">
            {runningText(c, timezone)}・每日 {c.daily_budget === null ? "未知" : formatAmount(c.daily_budget)}
          </div>
        )}
      </div>
      <div>
        <MoneyMeter value={c.month_spend} max={spent} tone="primary" />
        <div className="numeric mt-1 text-sm text-muted-foreground">
          {c.month_spend !== null
            ? `${formatAmount(Math.round(c.month_spend))} 元`
            : status.state === "no_rows" ? sentence(status.label) : "沒有花費紀錄"}
        </div>
      </div>
      <div>
        <MoneyMeter value={c.cost_per_purchase} cap={cap} max={600} />
        <div className="numeric mt-1 text-sm">
          {c.cost_per_purchase === null
            ? <span className="font-medium text-muted-foreground/80">{c.purchases === 0 ? "還沒有購買" : "算不出來"}</span>
            : <>
                <b>{wholeYuan(c.cost_per_purchase)}</b> <span className="text-muted-foreground">／{tl ?? "沒設上限"}</span>
                <MoneyTag cost={c.cost_per_purchase} breakEven={c.cap?.break_even ?? null} />
              </>}
        </div>
      </div>
      <div className="numeric font-semibold">{c.purchases === null ? "—" : formatAmount(c.purchases)}</div>
      <div className="text-right">
        <Button asChild variant="link" className="h-auto p-0">
          {closeout
            ? <Link to={`/brands/${brandId}/ads/campaigns/${c.campaign_id}?tab=perf&close=1`}>結案這一期 →</Link>
            : reconnect
            ? <Link to={`/brands/${brandId}/ads/connections`}>重新連線 →</Link>
            : <Link to={`/brands/${brandId}/ads/campaigns/${c.campaign_id}`}>打開 →</Link>}
        </Button>
      </div>
    </div>
  );
}

function DraftRow({ brandId, c }: { brandId: string; c: HomeCampaign }) {
  const d = c.draft!;
  const miss = Math.max(0, d.ads_total - d.ads_ready);
  const todo = [d.cap_missing ? "設上限" : "", miss ? `補 ${miss} 張圖` : ""].filter(Boolean);
  const start = d.start_date ? `${monthDay(d.start_date)} 開始` : "還沒定開始日";
  const tl = capLabel(c.cap);
  const href = `/brands/${brandId}/ads/campaigns/${c.campaign_id}${d.cap_missing ? "?tab=strategy" : ""}`;
  return (
    <div className={cn(GRID, "border-t border-border bg-background/50 py-3.5")}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <NameLink brandId={brandId} c={c} />
          <LifecycleChip c={c} />
          <HandoffChip brandId={brandId} campaignId={c.campaign_id} handoff={c.handoff} />
        </div>
        <div className="text-sm text-muted-foreground">{start}{todo.length ? `・還要${todo.join("、")}` : "・可以上架了"}</div>
      </div>
      <div className="text-[13px] text-muted-foreground">{d.approved ? "上架中" : "還沒上架"}</div>
      <div className="text-[13px] text-muted-foreground">{tl ?? "還沒設上限"}</div>
      <div className="text-muted-foreground">—</div>
      <div className="text-right">
        <Button asChild variant="link" className="h-auto p-0"><Link to={href}>繼續準備 →</Link></Button>
      </div>
    </div>
  );
}
