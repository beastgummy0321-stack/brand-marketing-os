import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import { formatCurrency } from "@/lib/format";
import { listCampaigns, type CampaignCard as CampaignCardData } from "@/lib/adsApi";
import {
  getQueue, getTriage, type CampaignTriage, type QueueItem, type TriageItem, type TriageTargetView,
} from "@/lib/adsTriageApi";
import { Chip, TargetRuler, formatAmount, type RulerAd, type RulerCap } from "../patterns";
import {
  ClosedGroup, GradeGroups, OPEN_BY_DEFAULT, adActions, groupOf, trendNote, type GroupKey,
} from "./GradeGroups";

/** F28-I10: campaign detail = the campaign's active ads graded against its one cap (prototype v9 `tabPerf()`,
 * hashes `camp/daily/perf`, `camp/mid/perf`, demo `tgt:none`). The page keeps its own header and breadcrumb; the
 * body is the full `TargetRuler` card, the grade groups and the closed ads. The cap is read-only here — 去改上限
 * goes to the strategy tab, where it is edited (Feature F28 "Agent choices"). Three reads fail independently: the
 * campaign list (header), triage (ruler + groups) and the brand queue (only the rows' 在清理提議／去處理). */

type Load<T> = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: T };
const errorText = (err: unknown) => (err instanceof Error ? err.message : "讀取失敗，請稍後再試。");

function useLoad<T>(load: () => Promise<T>, deps: unknown[]): [Load<T>, () => void] {
  const [state, setState] = useState<Load<T>>({ status: "loading" });
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    load()
      .then((data) => { if (!cancelled) setState({ status: "ready", data }); })
      .catch((err: unknown) => { if (!cancelled) setState({ status: "error", message: errorText(err) }); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `load` is rebuilt every render; `deps` names its inputs.
  }, [...deps, reload]);
  return [state, () => setReload((v) => v + 1)];
}

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

/** The missing-days chip (prototype 「缺 09/17、09/18，這兩天不計」) from triage `data.missing_days`. */
export function missingDaysLabel(days: string[]): string | null {
  if (!days.length) return null;
  const sorted = [...days].sort();
  if (sorted.length <= 3) {
    const which = ["這天", "這兩天", "這三天"][sorted.length - 1];
    return `缺 ${sorted.map(md).join("、")}，${which}不計`;
  }
  return `缺 ${md(sorted[0])}–${md(sorted.at(-1) as string)} 間 ${sorted.length} 天，這些天不計`;
}

function CapChip({ cap }: { cap: RulerCap | null }) {
  if (!cap) return <Chip tone="warn">沒設上限</Chip>;
  return cap.basis === "break_even"
    ? <Chip tone="warn">暫用打平 {formatAmount(cap.value)}</Chip>
    : <Chip tone="accent">上限 {formatAmount(cap.value)}</Chip>;
}

function RulerCard({ items, missingDays, strategyHref, onAdClick }: {
  items: TriageItem[]; missingDays: string[]; strategyHref: string; onAdClick: (id: string) => void;
}) {
  const target = items[0].target;
  const cap = capOf(target);
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
  const title = cap
    ? `在投 ${items.length} 則對照${cap.basis === "break_even" ? "暫用打平" : "上限"} ${formatAmount(cap.value)}`
    : `在投 ${items.length} 則，沒設上限`;
  const missing = missingDaysLabel(missingDays);
  const windowChip = windowLabel(items);
  return (
    <section className="surface px-[22px] py-5" aria-label="對照上限">
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[15px] font-semibold">{title}</h2>
        <div className="flex flex-wrap items-center gap-2.5">
          {missing && <Chip tone="warn">{missing}</Chip>}
          {windowChip && <Chip>{windowChip}</Chip>}
          <Button asChild variant="link" size="sm" className="h-auto px-0">
            <Link to={strategyHref}>{cap ? "去改上限" : "去設上限"}</Link>
          </Button>
        </div>
      </div>
      <TargetRuler ads={ads} cap={cap} breakEven={target.break_even ?? null} size="full" onAdClick={onAdClick} />
    </section>
  );
}

function SectionError({ what, message, onRetry }: { what: string; message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-xl bg-warning/10 px-4 py-3 text-sm">
      <span className="flex-1 font-medium text-warning">{what}讀取失敗：{message}</span>
      <Button size="sm" variant="outline" onClick={onRetry}>重新讀取</Button>
    </div>
  );
}

export function CampaignDetailPage({ brandId, campaignId }: { brandId: string; campaignId: string }) {
  const [searchParams] = useSearchParams();
  const highlightAdParam = searchParams.get("ad");
  const navigate = useNavigate();

  const [campaigns, reloadCampaigns] = useLoad<CampaignCardData[]>(() => listCampaigns(brandId), [brandId]);
  const [triage, reloadTriage] = useLoad<CampaignTriage>(() => getTriage(brandId, campaignId), [brandId, campaignId]);
  const [queue, reloadQueue] = useLoad<QueueItem[]>(() => getQueue(brandId).then((q) => q.items), [brandId]);

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

  const actions = useMemo(
    () => adActions(brandId, campaignId, workspaceHref, items ?? [], queue.status === "ready" ? queue.data : []),
    [brandId, campaignId, workspaceHref, items, queue],
  );

  if (campaigns.status !== "ready") {
    return (
      <div className="flex max-w-[1260px] flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "活動" }]} />
        {campaigns.status === "loading"
          ? <><Skeleton className="h-9 w-80" /><Skeleton className="h-60 w-full" /></>
          : <EmptyState title="讀取失敗" description={campaigns.message} onAction={reloadCampaigns} actionLabel="重新讀取" />}
      </div>
    );
  }
  const campaign = campaigns.data.find((c) => c.id === campaignId) ?? null;
  if (campaign === null) {
    return (
      <div className="flex max-w-[1260px] flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "活動" }]} />
        <EmptyState title="讀取失敗" description="找不到這個 Campaign。" onAction={reloadCampaigns} actionLabel="重新讀取" />
      </div>
    );
  }

  const budgetTotal = campaign.budget_progress.total;
  const budgetChip = campaign.origin === "imported"
    ? <Chip>平台預算</Chip>
    : budgetTotal !== null ? <Chip>總預算 {formatCurrency(budgetTotal)}</Chip> : <Chip tone="warn">預算待核實</Chip>;
  const closed = triage.status === "ready" ? triage.data.closed : null;
  const active = items !== null && items.length > 0 ? items : null;

  return (
    // Prototype v9 `.page{max-width:1260px}`.
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
        <EmptyState title="讀取失敗" description={triage.message} onAction={reloadTriage} actionLabel="重新讀取" />
      )}
      {items && closed && items.length === 0 && closed.total === 0 && (
        <div className="surface p-5">
          <p className="text-sm text-muted-foreground">沒有廣告資料，這個活動還沒有可以判斷的內容。</p>
        </div>
      )}
      {active && (
        <>
          <RulerCard
            items={active}
            missingDays={triage.status === "ready" ? triage.data.data?.missing_days ?? [] : []}
            strategyHref={strategyHref}
            onAdClick={(id) => { const a = actions.get(id); if (a) navigate(a.href); }}
          />
          {queue.status === "error" && <SectionError what="決策進度" message={queue.message} onRetry={reloadQueue} />}
          <GradeGroups
            items={active}
            cap={capOf(active[0].target)?.value ?? null}
            actions={actions}
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
      {closed && closed.total > 0 && (
        <ClosedGroup closed={closed} workspaceHref={workspaceHref} open={closedOpen} onToggle={setClosedOpen} />
      )}
    </div>
  );
}
