import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { formatCurrency } from "@/lib/format";
import { listCampaigns } from "@/lib/adsApi";
import {
  getQueue, getTriage, type CampaignDataStatus, type TriageItem, type TriageTargetView,
} from "@/lib/adsTriageApi";
import { useApiRead } from "@/lib/useApiRead";
import {
  ActionBar, Chip, GradeRules, ReadFailed, TargetRuler, Term, formatAmount, type RulerAd, type RulerCap,
} from "../patterns";
import { AbBlock } from "./AbBlock";
import { AdRowMenu, useReplaceRequests } from "./AdRowMenu";
import {
  ClosedGroup, GradeGroups, OPEN_BY_DEFAULT, adActions, groupOf, openCleanup, recordHref, trendNote, type GroupKey,
} from "./GradeGroups";

/** F28-I10, v10 F29-I13: campaign detail = the campaign's active ads graded against its one cap (prototype v10
 * `tabPerf()`, hash `camp/daily/perf`). The page keeps its own header and breadcrumb; the body is the full
 * `TargetRuler` card (+ the grade legend once), the automatic A/B block, the grade groups with each row's 「⋯」 menu
 * (換掉這一則／看紀錄) and, under 不在投的, the closed ads. The cap is read-only here — 去改上限 goes to the strategy tab.
 * Why numbers are missing is the campaign's one `data.status` (Contract D), never a per-section rule. Every read
 * fails on its own (`useApiRead` + `ReadFailed`): the campaign list (header), triage (ruler + groups), the brand
 * queue (only the rows' 在清理提議／去處理), the A/B pairs and the material list (only 換掉這一則). */

function capOf(target: TriageTargetView | undefined): RulerCap | null {
  if (!target || target.value === null || target.basis === null) return null;
  return { value: target.value, basis: target.basis };
}

const md = (iso: string) => `${iso.slice(5, 7)}/${iso.slice(8, 10)}`;

/** The window chip (prototype 「近 14 天 09/10–09/23」). Each ad's window may have been extended to reach the sample
 * gate (7／14／28 days, same end), so several lengths print as a range rather than one ad's window. */
export function windowLabel(items: TriageItem[]): string | null {
  if (!items.length) return null;
  const days = [...new Set(items.map((i) => i.window.days))].sort((a, b) => a - b);
  const start = items.map((i) => i.window.start).sort()[0];
  const end = items.map((i) => i.window.end).sort().at(-1) as string;
  const span = days.length === 1 ? `${days[0]}` : `${days[0]}–${days.at(-1)}`;
  return `近 ${span} 天 ${md(start)}–${md(end)}`;
}

/** The missing-days chip (prototype 「缺 09/17、09/18，這兩天不計」) from `data.status.missing_days`. */
export function missingDaysLabel(days: string[]): string | null {
  if (!days.length) return null;
  const sorted = [...days].sort();
  if (sorted.length <= 3) {
    const which = ["這天", "這兩天", "這三天"][sorted.length - 1];
    return `缺 ${sorted.map(md).join("、")}，${which}不計`;
  }
  return `缺 ${md(sorted[0])}–${md(sorted.at(-1) as string)} 間 ${sorted.length} 天，這些天不計`;
}

/** The one data-status chip of the ruler card: a partial window names its unread days; any other state that is not
 * whole is the backend's own sentence (without its closing 。). `ready` says nothing. */
export function dataStatusChip(status: CampaignDataStatus | null): string | null {
  if (!status || status.state === "ready") return null;
  if (status.state === "partial") return missingDaysLabel(status.missing_days) ?? status.label.replace(/。$/, "");
  return status.label.replace(/。$/, "");
}

function CapChip({ cap }: { cap: RulerCap | null }) {
  if (!cap) return <Chip tone="warn">沒設上限</Chip>;
  return cap.basis === "break_even"
    ? <Chip tone="warn">暫用打平 {formatAmount(cap.value)}</Chip>
    : <Chip tone="accent">上限 {formatAmount(cap.value)}</Chip>;
}

function RulerCard({ items, status, strategyHref, onAdClick }: {
  items: TriageItem[]; status: CampaignDataStatus | null; strategyHref: string; onAdClick: (id: string) => void;
}) {
  const target = items[0].target;
  const cap = capOf(target);
  const breakEven = target.break_even ?? null;
  const ads: RulerAd[] = items.map((item) => ({
    id: item.entity_id,
    name: item.name ?? "（未命名廣告）",
    grade: item.grade,
    gradeLabel: item.grade_label,
    costPerResult: item.current.cost_per_result,
    spend: item.current.spend,
    thumbnailUrl: item.thumbnail_url,
    note: trendNote(item),
  }));
  const title = !cap
    ? <>在投 {items.length} 則，沒設<Term k="cap">上限</Term></>
    : cap.basis === "break_even"
      ? <>在投 {items.length} 則對照暫用<Term k="break_even" value={breakEven}>打平線</Term> {formatAmount(cap.value)}</>
      : <>在投 {items.length} 則對照<Term k="cap">上限</Term> {formatAmount(cap.value)}</>;
  // Prototype `beCap`: the dashed 打平 mark is drawn only beside an own cap that differs from it; this line names it.
  const beLine = cap && cap.basis === "own" && breakEven !== null && Math.abs(breakEven - cap.value) > 0.01;
  const statusChip = dataStatusChip(status);
  const windowChip = windowLabel(items);
  return (
    <section className="surface px-[22px] py-5" aria-label="對照上限">
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold">{title}</h2>
        <div className="flex flex-wrap items-center gap-2.5">
          {statusChip && <Chip tone="warn" data-state={status!.state}>{statusChip}</Chip>}
          {windowChip && <Chip>{windowChip}</Chip>}
          <Button asChild variant="link" size="sm" className="h-auto px-0">
            <Link to={strategyHref}>{cap ? "去改上限" : "去設上限"}</Link>
          </Button>
        </div>
      </div>
      <TargetRuler ads={ads} cap={cap} breakEven={breakEven} size="full" onAdClick={onAdClick} />
      {beLine && (
        <div className="mt-0.5 text-[11.5px] text-muted-foreground">
          橘色虛線：<Term k="break_even" value={breakEven}>打平線</Term> {formatAmount(breakEven)}
        </div>
      )}
      {cap && <GradeRules breakEven={breakEven} />}
    </section>
  );
}

export function CampaignDetailPage({ brandId, campaignId }: { brandId: string; campaignId: string }) {
  const [searchParams] = useSearchParams();
  const highlightAdParam = searchParams.get("ad");
  const navigate = useNavigate();

  const campaigns = useApiRead(() => listCampaigns(brandId), [brandId]);
  const triage = useApiRead((signal) => getTriage(brandId, campaignId, signal), [brandId, campaignId]);
  const queue = useApiRead((signal) => getQueue(brandId, signal).then((q) => q.items), [brandId]);
  const requests = useReplaceRequests(brandId, campaignId);

  const [openGroups, setOpenGroups] = useState<Set<GroupKey>>(() => new Set(OPEN_BY_DEFAULT));
  const [closedOpen, setClosedOpen] = useState(false);
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const rowRefs = useRef(new Map<string, HTMLDivElement>());

  const items = triage.status === "ready" ? triage.data.items : null;

  // `?ad=<entity_id>`: open that ad's group and highlight its row, once per id; an unknown id is ignored.
  const [handledAdParam, setHandledAdParam] = useState<string | null>(null);
  useEffect(() => {
    if (!items || !highlightAdParam || highlightAdParam === handledAdParam) return;
    const item = items.find((i) => i.entity_id === highlightAdParam);
    if (!item) return;
    setOpenGroups((prev) => new Set(prev).add(groupOf(item)));
    setHighlightId(item.entity_id);
    setHandledAdParam(highlightAdParam);
  }, [items, highlightAdParam, handledAdParam]);

  // Scroll to the highlighted row once per id — folding other groups later never scrolls back.
  const scrolledToRef = useRef<string | null>(null);
  useEffect(() => {
    if (!highlightId || scrolledToRef.current === highlightId) return;
    rowRefs.current.get(highlightId)?.scrollIntoView({ behavior: "smooth", block: "center" });
    scrolledToRef.current = highlightId;
  }, [highlightId, openGroups]);

  const homeHref = `/brands/${brandId}/ads`;
  const workspaceHref = `/brands/${brandId}/ads/campaigns/${campaignId}`;
  const strategyHref = `${workspaceHref}?tab=strategy`;

  const queueItems = queue.status === "ready" ? queue.data : null;
  const actions = useMemo(
    () => adActions(brandId, campaignId, workspaceHref, items ?? [], queueItems ?? []),
    [brandId, campaignId, workspaceHref, items, queueItems],
  );
  const cleanup = queueItems ? openCleanup(brandId, campaignId, queueItems) : null;

  if (campaigns.status !== "ready") {
    return (
      <div className="flex max-w-[1260px] flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "活動" }]} />
        {campaigns.status === "loading"
          ? <><Skeleton className="h-9 w-80" /><Skeleton className="h-60 w-full" /></>
          : <ReadFailed what={`活動清單讀不到：${campaigns.error}`} onRetry={campaigns.reload} />}
      </div>
    );
  }
  const campaign = campaigns.data.find((c) => c.id === campaignId) ?? null;
  if (campaign === null) {
    return (
      <div className="flex max-w-[1260px] flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "活動" }]} />
        <EmptyState title="找不到活動" description="找不到這個 Campaign。" onAction={campaigns.reload} actionLabel="重新讀取" />
      </div>
    );
  }

  const budgetTotal = campaign.budget_progress.total;
  const budgetChip = campaign.origin === "imported"
    ? <Chip>平台預算</Chip>
    : budgetTotal !== null ? <Chip>總預算 {formatCurrency(budgetTotal)}</Chip> : <Chip tone="warn">預算待核實</Chip>;
  const closed = triage.status === "ready" ? triage.data.closed : null;
  const status = triage.status === "ready" ? triage.data.data?.status ?? null : null;
  const active = items !== null && items.length > 0 ? items : null;
  const breakEven = active?.[0].target.break_even ?? null;

  return (
    // Prototype v10 `.page{max-width:1260px}`.
    <div className="flex max-w-[1260px] flex-col gap-4">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: campaign.name }]} />

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold [overflow-wrap:anywhere]">{campaign.name}</h1>
          {items && (
            <p className="mt-1 text-[15px] text-muted-foreground">
              只判讀投放中的 {items.length} 則；已關閉的廣告保留紀錄，不列入判斷
            </p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {/* An imported objective can be a whole sentence: only it truncates, 「・N 則」 always shows. */}
            <Chip className="max-w-[14rem] items-center">
              <span className="min-w-0 truncate" title={campaign.objective || undefined}>{campaign.objective || "尚待確認"}</span>
              {items && <span className="shrink-0">・{items.length} 則</span>}
            </Chip>
            {active && <CapChip cap={capOf(active[0].target)} />}
            {budgetChip}
          </div>
        </div>
        <Button variant="ghost" asChild>
          <Link to={workspaceHref}>全部資料 ›</Link>
        </Button>
      </div>

      {triage.status === "loading" && <Skeleton className="h-60 w-full" />}
      {triage.status === "error" && (
        <ReadFailed what={`成效讀不到：${triage.error}`} onRetry={triage.reload} />
      )}
      {items && closed && items.length === 0 && closed.total === 0 && (
        <div className="surface p-5" data-testid="no-ads">
          <p className="text-sm text-muted-foreground">
            {status && status.state !== "ready" ? status.label : "沒有廣告資料，這個活動還沒有可以判斷的內容。"}
          </p>
        </div>
      )}
      {active && (
        <>
          <RulerCard
            items={active}
            status={status}
            strategyHref={strategyHref}
            onAdClick={(id) => { const a = actions.get(id); if (a) navigate(a.href); }}
          />
          {campaign.origin !== "imported" && <AbBlock brandId={brandId} campaignId={campaignId} breakEven={breakEven} />}
          {queue.status === "error" && (
            <ReadFailed what={`決策進度讀不到（${queue.error}）；成績照常可看，哪幾則在清理提議或要處理暫時看不到。`} onRetry={queue.reload} />
          )}
          {requests.read.status === "error" && (
            <ReadFailed what={`素材需求讀不到（${requests.read.error}）；哪幾則已開「換掉這一則」暫時看不到。`} onRetry={requests.read.reload} />
          )}
          <GradeGroups
            items={active}
            cap={capOf(active[0].target)?.value ?? null}
            breakEven={breakEven}
            dataReason={status && status.state !== "ready" ? status.label : null}
            actions={actions}
            extras={(item) => ({
              menu: (
                <AdRowMenu
                  name={item.name ?? "（未命名廣告）"} entityId={item.entity_id}
                  recordHref={recordHref(workspaceHref, item.entity_id)} requests={requests}
                />
              ),
              requestOpen: Boolean(requests.requestOf(item.entity_id)),
              error: requests.errorOf(item.entity_id),
            })}
            openGroups={openGroups}
            onToggle={(key, open) => setOpenGroups((prev) => {
              const next = new Set(prev);
              if (open) next.add(key);
              else next.delete(key);
              return next;
            })}
            highlightId={highlightId}
            registerRow={(id, el) => {
              if (el) rowRefs.current.set(id, el);
              else rowRefs.current.delete(id);
            }}
          />
        </>
      )}
      {closed && closed.total > 0 && <ClosedGroup closed={closed} open={closedOpen} onToggle={setClosedOpen} />}

      <ActionBar back={{ label: "總覽", to: workspaceHref }}>
        {cleanup && <Button asChild><Link to={cleanup.href}>看清理提議 →</Link></Button>}
      </ActionBar>
    </div>
  );
}
