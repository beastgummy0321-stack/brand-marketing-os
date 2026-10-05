import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Skeleton } from "@/components/layout/Skeleton";
import { Button } from "@/components/layout/ui/button";
import type { CampaignDetail, CampaignLabels } from "@/lib/adsApi";
import { getQueue, getTriage, type CampaignDataStatus, type CloseoutQueueRow, type QueueItem, type QueuePayload } from "@/lib/adsTriageApi";
import { dayList, formatInstant, useOrgClock } from "@/lib/orgClock";
import { getCampaignStructure, type CampaignStructure, type CampaignWorkspace, type WorkspaceTotals } from "@/lib/adsWorkspaceApi";
import { useApiRead } from "@/lib/useApiRead";
import {
  ActionBar, Chip, DAY_SWATCH, DayTiles, Disclosure, GradeRules, GradeTermChip, KindMark, Legend, Meter,
  MoneyMeter, MoneyTag, ReadFailed, TargetRuler, Term, Thumb, TodoRow, figure as ruleFigure, formatAmount, gradeWord,
  sampleWords, unsoldLine, useAdsRules, watchLine, type RulerAd, type RulerCap,
} from "../patterns";
import { cleanupAction, proposalAction } from "../home/status";
import { decisionTitle } from "../home/QueueRow";
import type { StepTarget } from "../nextStep";
import { perSaleAmount } from "../patterns/csv";

/** v10 (F30-I07) the workspace overview (prototype `tabOverview()` + `kvNumbers()`), in three states from
 * `GET …/workspace`: a draft's 上架前還差什麼 checklist (上限、預算、素材 x／y、上架 n／N, k／4) with the ruler preview;
 * a data gap (missing days) with each ad's distance to a judgeable sample (from `GET …/structure`) and the missing
 * days; otherwise the next open decision of this campaign (or 「這個活動沒有要決定的事」), the four numbers of the last
 * 14 complete days (`totals`) and the in-flight ruler. Each extra read (structure, queue, the data-status reason) fails
 * on its own with `ReadFailed`; an unknown number prints as unknown, never 0. What the old overview showed and the
 * prototype does not lives in the caller's `advanced` fold.
 *
 * F47-I08 (Contract E, drill-10 S3): a campaign on the platform that has not spent yet (`delivery === "waiting"`) says
 * so in the ✓ next-step card (「已上架，等平台開始投放」 + when its first number can show up) and its money cells read
 * 「還沒開始花」, never 「未知」. A closed campaign never says 在投: 「已結案」 or 「已結案・平台上還開著 N 則」.
 *
 * F49 Contract Q: the next decision is this campaign's open decision row with the lowest served `position` (the home
 * board's order, never a local kind order); 「第 N 件（共 M 件）」 is that `position` and the queue's `decisions.open`. An
 * ended campaign's `closeout` row (Contract L／Q) is a decision too: its card names the end date and what is still
 * running, and the bar's 結案這一期 → opens the perf tab's close dialog (`?tab=perf&close=1`). An ended campaign skips the
 * data-gap view: the close dialog itself asks to re-read missing days first. The campaign's word is the served
 * `lifecycle.label`. */

const DEFAULT_LABELS: CampaignLabels = { conversion: "購買", count: "購買數", cpa: "每次購買成本" };
const CARD = "surface px-[22px] py-5";
const HEAD = "mb-3.5 flex flex-wrap items-center justify-between gap-3";
const H2 = "text-[15px] font-semibold";

const RANKED = new Set(["on_target", "watch", "over", "wasted"]);

export function capOf(c: CampaignDetail): RulerCap | null {
  return c.cap.value !== null && c.cap.basis !== null ? { value: c.cap.value, basis: c.cap.basis } : null;
}

/** The ads on the ruler: on a platform, graded, not being closed by an approved pause (prototype `adsOf`). */
export function rulerAds(structure: CampaignStructure): RulerAd[] {
  return structure.groups.flatMap((g) => g.ads)
    .filter((a) => a.entity_id !== null && a.grade !== null && !a.closing)
    .map((a) => ({
      id: a.entity_id as string, name: a.name, grade: a.grade!, gradeLabel: a.grade_label,
      costPerResult: a.cost_per_result, spend: a.spend, thumbnailUrl: a.thumbnail_url,
    }));
}

const yuan = (v: number | null) => (formatAmount(v) === null ? "未知" : `${formatAmount(v)} 元`);
const perSale = (v: number | null) => (perSaleAmount(v) === null ? "未知" : `${perSaleAmount(v)} 元`);
const md = (iso: string) => `${iso.slice(5, 7)}/${iso.slice(8, 10)}`;

type Go = (target: StepTarget) => void;

export function OverviewBody({ brandId, campaign: c, workspace: ws, canPublish, onGo, advanced }: {
  brandId: string;
  campaign: CampaignDetail;
  workspace: CampaignWorkspace;
  /** The campaign can open the publish page (app-built, not published yet). */
  canPublish: boolean;
  onGo: Go;
  /** The folded 「進階：更多活動資訊」 content. */
  advanced: ReactNode;
}) {
  const draft = ws.draft;
  const gap = draft === null && (ws.missing_days?.length ?? 0) > 0 && c.lifecycle?.state !== "ended";
  const fold = <Disclosure label="進階：更多活動資訊">{advanced}</Disclosure>;
  if (draft) return <DraftOverview brandId={brandId} campaign={c} workspace={ws} draft={draft} canPublish={canPublish} onGo={onGo} fold={fold} />;
  if (gap) return <GapOverview brandId={brandId} campaign={c} workspace={ws} fold={fold} />;
  return <LiveOverview brandId={brandId} campaign={c} workspace={ws} fold={fold} />;
}

// ---------------------------------------------------------------------------------------------------------------
// draft
// ---------------------------------------------------------------------------------------------------------------

function DraftOverview({ brandId, campaign: c, workspace: ws, draft, canPublish, onGo, fold }: {
  brandId: string; campaign: CampaignDetail; workspace: CampaignWorkspace; draft: NonNullable<CampaignWorkspace["draft"]>;
  canPublish: boolean; onGo: Go; fold: ReactNode;
}) {
  const cap = capOf(c);
  const approved = ws.stage.key === "launch" || draft.launch_total > 0;
  const slotsDone = draft.slots_total > 0 && draft.slots_ready >= draft.slots_total;
  const launchDone = draft.launch_total > 0 && draft.launch_checked >= draft.launch_total;
  const publish: StepTarget = canPublish ? "publish" : "assets";
  const steps: { label: string; detail: string; done: boolean; target: StepTarget }[] = [
    { label: "上限", done: draft.cap_set, target: "strategy",
      detail: draft.cap_set && c.cap.value !== null ? `每賣一筆最多 ${formatAmount(c.cap.value)} 元${c.cap.basis === "break_even" ? "（暫用打平）" : ""}` : "還沒設定" },
    { label: "預算", done: draft.budget_set, target: "strategy",
      detail: draft.budget_set ? (c.budget_planned !== null ? `NT$${formatAmount(c.budget_planned)}` : "已選") : "還沒選" },
    { label: "素材", done: slotsDone, target: "assets", detail: `${draft.slots_ready}／${draft.slots_total} 格` },
    { label: "上架", done: launchDone, target: publish,
      detail: draft.launch_total > 0 ? `${draft.launch_checked}／${draft.launch_total} 已核對` : "還沒開始" },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  const primary = !draft.cap_set ? { label: "去設上限", target: "strategy" as StepTarget }
    : !draft.budget_set ? { label: "去選預算", target: "strategy" as StepTarget }
    : approved ? { label: "繼續：到平台完成", target: publish }
    : { label: "確認上架清單", target: publish };
  // F43-I16: cost lives on the knowledge product's 賣法與價格 step (onboarding step 4), not the old detail tab.
  const productHref = c.cap.knowledge_product_id ? `/brands/${brandId}/products/${c.cap.knowledge_product_id}/onboarding?step=4` : `/brands/${brandId}/products`;

  return (
    <div className="flex flex-col gap-4">
      <section className={CARD} aria-labelledby="ov-draft">
        <div className={`${HEAD} mb-1`}>
          <h2 id="ov-draft" className={H2}>上架前還差什麼</h2>
          <Chip>{doneCount}／4 完成</Chip>
        </div>
        {steps.map((s, i) => (
          <TodoRow key={s.label} no={i + 1} done={s.done}
            action={<Button variant="outline" size="sm" onClick={() => onGo(s.target)}>{s.done ? "查看" : "去處理"} →</Button>}>
            <b className="font-semibold">{s.label}</b>
            <div className="text-sm text-muted-foreground">{s.detail}</div>
          </TodoRow>
        ))}
      </section>
      <section className={CARD} aria-labelledby="ov-preview">
        <div className={HEAD}>
          <h2 id="ov-preview" className={H2}>對照上限預覽</h2>
          <span className="text-sm text-muted-foreground">上架後廣告會落在這條尺上</span>
        </div>
        <TargetRuler ads={[]} cap={cap} breakEven={c.cap.break_even} size="mid" tray={false} />
        {cap && <GradeRules breakEven={c.cap.break_even} />}
        {!cap && c.cap.break_even === null && (
          <Button asChild variant="link" size="sm" className="mt-3 h-auto px-0"><Link to={productHref}>去填商品成本</Link></Button>
        )}
      </section>
      {fold}
      <ActionBar back={{ label: "投放中心", to: `/brands/${brandId}/ads` }}>
        <Button onClick={() => onGo(primary.target)}>{primary.label} →</Button>
      </ActionBar>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------
// data gap
// ---------------------------------------------------------------------------------------------------------------

/** Every day from the first to the last of `days` and of the totals window (ISO dates, no time zone arithmetic). */
export function dayRange(days: string[], totals: WorkspaceTotals | null): string[] {
  const all = [...days, ...(totals ? [totals.start, totals.end] : [])].sort();
  if (!all.length) return [];
  return dayList(all[0], all[all.length - 1], 62);
}

const WHICH = ["這天", "這兩天", "這三天"];

function GapOverview({ brandId, campaign: c, workspace: ws, fold }: {
  brandId: string; campaign: CampaignDetail; workspace: CampaignWorkspace; fold: ReactNode;
}) {
  const structure = useApiRead((signal) => getCampaignStructure(brandId, c.id, signal), [brandId, c.id]);
  const triage = useApiRead((signal) => getTriage(brandId, c.id, signal), [brandId, c.id]);
  const status: CampaignDataStatus | null = triage.status === "ready" ? triage.data.data?.status ?? null : null;
  const missing = [...(ws.missing_days ?? [])].sort();
  const cap = capOf(c);
  const T = cap?.value ?? null;
  const breakEven = c.cap.break_even;
  const ads = structure.status === "ready"
    ? structure.data.groups.flatMap((g) => g.ads).filter((a) => a.entity_id !== null && !a.closing)
    : [];
  const reason = status && status.state !== "ready" && status.state !== "partial" ? status.label.replace(/。$/, "") : null;
  const rules = useAdsRules();
  // The served 沒賣出 spend line is the distance a known zero has to cover before it can be judged (F48 Contract R-API).
  const gate = T !== null && rules ? unsoldLine(rules, T) : null;
  const auth = status?.state === "auth_expired" || status?.state === "disconnected";

  return (
    <div className="flex flex-col gap-4">
      <section className={CARD} aria-labelledby="ov-gap">
        <div className={`${HEAD} mb-1`}>
          <h2 id="ov-gap" className={H2}>每則廣告離可以判斷還差多少</h2>
          {T === null ? <Chip tone="warn">沒設上限</Chip>
            : gate !== null && rules ? <Chip>門檻：花到 {formatAmount(gate)} 元（上限 × {ruleFigure(rules.grade.unsold_spend_multiple)}）</Chip> : null}
        </div>
        {structure.status === "loading" && <Skeleton className="h-40 w-full" />}
        {structure.status === "error" && <ReadFailed what={`每則廣告的花費讀不到：${structure.error}`} onRetry={structure.reload} />}
        {structure.status === "ready" && ads.length === 0 && <p className="py-3 text-sm text-muted-foreground">還沒有在平台上的廣告</p>}
        {ads.map((a) => {
          const graded = a.grade !== null && RANKED.has(a.grade);
          const pct = a.spend !== null && gate ? Math.min(100, Math.round((a.spend / gate) * 100)) : null;
          const sample = graded ? sampleWords(rules, a.sample) : [];
          return (
            <div key={a.entity_id} className="grid grid-cols-[40px_minmax(0,1fr)_minmax(160px,240px)_130px] items-center gap-3.5 border-t border-border py-[11px] first:border-t-0">
              <Thumb url={a.thumbnail_url} size={40} />
              <div className="min-w-0 font-medium [overflow-wrap:anywhere]">{a.name}</div>
              <div>
                {a.grade === "wasted" ? (
                  // 沒賣出 has no cost per sale: the row shows what it spent against the served 沒賣出 line (same meter as
                  // the next-decision 沒賣出 figure), never 「每筆 未知」.
                  <Meter value={a.spend} max={Math.max((gate ?? 0) * 1.4, (a.spend ?? 0) * 1.1)} marker={gate} tone="danger"
                    left={`花了 ${yuan(a.spend)}，0 筆`}
                    right={gate !== null ? <span className="whitespace-nowrap">門檻 {formatAmount(gate)}</span> : null} />
                ) : graded && T !== null ? (
                  <Meter value={a.cost_per_result} max={T * 1.6} marker={T}
                    tone={a.grade === "on_target" ? "success" : a.grade === "watch" ? "warning" : "danger"}
                    left={<>每筆 {perSale(a.cost_per_result)}<MoneyTag cost={a.cost_per_result} breakEven={breakEven} /></>}
                    right={<span className="whitespace-nowrap">上限 {formatAmount(T)}</span>} />
                ) : (
                  <>
                    <MoneyMeter value={a.spend} max={gate} />
                    <div className="numeric mt-1 flex justify-between gap-2 text-[11.5px] text-muted-foreground">
                      <span>已花 {yuan(a.spend)}</span><span>{pct === null ? "" : `${pct}%`}</span>
                    </div>
                  </>
                )}
              </div>
              <div className="flex flex-wrap items-center justify-end gap-1">
                <GradeTermChip grade={a.grade} label={a.grade_label} reasonCode={a.reason_code} />
                {sample.map((word) => <Chip key={word} data-part="sample">{word}</Chip>)}
              </div>
            </div>
          );
        })}
        {cap && <GradeRules breakEven={breakEven} />}
      </section>
      <section className={CARD} aria-labelledby="ov-days">
        <div className={HEAD}>
          <h2 id="ov-days" className={H2}>資料缺漏</h2>
          {reason && <Chip tone="warn">{reason}</Chip>}
        </div>
        {triage.status === "error" && <div className="mb-3"><ReadFailed what={`缺資料的原因讀不到：${triage.error}`} onRetry={triage.reload} /></div>}
        <DayTiles days={dayRange(missing, ws.totals)} missing={new Set(missing)} size={34} />
        <Legend className="mt-2.5" items={[
          { label: "有資料", swatch: "bg-primary" },
          { label: `缺資料，${WHICH[missing.length - 1] ?? "這些天"}不計`, swatch: DAY_SWATCH.missing },
        ]} />
      </section>
      {fold}
      <ActionBar back={{ label: "投放中心", to: `/brands/${brandId}/ads` }}>
        <Button asChild><Link to={`/brands/${brandId}/ads/connections`}>{auth ? "去資料連線補授權" : "去資料連線"} →</Link></Button>
      </ActionBar>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------
// live
// ---------------------------------------------------------------------------------------------------------------

/** Where this decision's one step goes, with the same helpers as the home rows and the flows. Only decision rows reach
 * here (Contract Q: `scale_budget` and `insufficient_data` are notices, never the next decision). */
export function decisionAction(brandId: string, item: QueueItem): { label: string; href: string | null } {
  const campaignId = item.triage.campaign_id;
  switch (item.kind_key) {
    case "cleanup": {
      const a = cleanupAction(brandId, item.cleanup?.campaign_id ?? campaignId, item.proposal, item.action_url);
      return a ? { label: item.proposal === null ? "看提議" : a.label, href: a.href } : { label: "看提議", href: null };
    }
    case "worse": return proposalAction(brandId, campaignId, item.triage.entity_id, item.proposal, "review");
    default: return { label: "去處理", href: item.action_url };
  }
}

/** One open decision of this campaign: an ad-level row or the campaign's closeout row, at its served `position`. */
export type OpenDecision =
  | { type: "ad"; position: number; item: QueueItem }
  | { type: "closeout"; position: number; row: CloseoutQueueRow };

/** This campaign's open decisions in the served board order (`position`; done rows and notices carry none). */
export function openDecisions(queue: QueuePayload, campaignId: string): OpenDecision[] {
  const ads: OpenDecision[] = queue.items
    .filter((q) => (q.campaign_id ?? q.triage.campaign_id) === campaignId && q.decision === true && typeof q.position === "number")
    .map((item) => ({ type: "ad", position: item.position as number, item }));
  const closeouts: OpenDecision[] = (queue.closeouts ?? [])
    .filter((r) => r.campaign_id === campaignId && r.decision && typeof r.position === "number")
    .map((row) => ({ type: "closeout", position: row.position as number, row }));
  return [...ads, ...closeouts].sort((a, b) => a.position - b.position);
}

function LiveOverview({ brandId, campaign: c, workspace: ws, fold }: {
  brandId: string; campaign: CampaignDetail; workspace: CampaignWorkspace; fold: ReactNode;
}) {
  const { timezone } = useOrgClock();
  const structure = useApiRead((signal) => getCampaignStructure(brandId, c.id, signal), [brandId, c.id]);
  const queue = useApiRead((signal) => getQueue(brandId, signal), [brandId]);
  const open = queue.status === "ready" ? openDecisions(queue.data, c.id) : [];
  const first = open[0] ?? null;
  const total = queue.status === "ready" ? queue.data.decisions?.open ?? null : null;
  const action = first === null ? null
    : first.type === "closeout" ? { label: "結案這一期", href: first.row.action_url }
    : decisionAction(brandId, first.item);
  const cap = capOf(c);
  const ads = structure.status === "ready" ? rulerAds(structure.data) : null;
  const perfHref = `/brands/${brandId}/ads/campaigns/${c.id}?tab=perf`;
  const closed = c.lifecycle?.state === "closed";
  const waiting = ws.delivery === "waiting";
  const rulerTitle = closed ? "廣告對照上限" : ads ? `在投 ${ads.length} 則對照上限` : "在投廣告對照上限";

  return (
    <div className="flex flex-col gap-4">
      {queue.status === "loading" ? <Skeleton className="h-28 w-full" />
        : queue.status === "error" ? <ReadFailed what={`要決定的事讀不到：${queue.error}。數字與上限照常可看。`} onRetry={queue.reload} />
        : first ? (
          <section className={CARD} aria-labelledby="ov-next">
            <div className={HEAD}>
              <h2 id="ov-next" className={H2}>下一步</h2>
              <span className="text-sm text-muted-foreground">今天要決定的第 {first.position} 件{total !== null && `（共 ${total} 件）`}</span>
            </div>
            {first.type === "closeout"
              ? <CloseoutDecision row={first.row} campaign={c} />
              : <NextDecision item={first.item} ads={ads} cap={cap} breakEven={c.cap.break_even} workspace={ws} />}
          </section>
        ) : (
          <section className={`${CARD} flex items-center gap-4`} aria-label="下一步">
            <div className="grid size-[52px] shrink-0 place-items-center rounded-full bg-success text-2xl text-white" aria-hidden="true">✓</div>
            <div className="min-w-0 flex-1">
              <b className="text-[17px]">{waiting ? "已上架，等平台開始投放" : "這個活動沒有要決定的事"}</b>
              <div className="text-sm text-muted-foreground">{waiting
                ? `平台開始花錢後，下次同步${ws.next_sync_at ? `（${formatInstant(ws.next_sync_at, timezone, "hm")}）` : ""}會出現第一筆數字。`
                : ws.next_sync_at ? `下次同步 ${formatInstant(ws.next_sync_at, timezone, "hm")} 後重新判讀` : "下次同步後重新判讀"}</div>
            </div>
          </section>
        )}
      <KvNumbers campaign={c} workspace={ws} />
      <section className={CARD} aria-labelledby="ov-ruler">
        <div className={HEAD}>
          <h2 id="ov-ruler" className={H2}>{rulerTitle}</h2>
          <Button asChild variant="link" size="sm" className="h-auto px-0"><Link to={perfHref}>看成效 →</Link></Button>
        </div>
        {structure.status === "loading" && <Skeleton className="h-24 w-full" />}
        {structure.status === "error" && <ReadFailed what={`每則廣告的成績讀不到：${structure.error}`} onRetry={structure.reload} />}
        {ads && <TargetRuler ads={ads} cap={cap} breakEven={c.cap.break_even} size="mid" />}
        {ads && cap && <GradeRules breakEven={c.cap.break_even} />}
      </section>
      {fold}
      <ActionBar back={{ label: "投放中心", to: `/brands/${brandId}/ads` }}>
        {action?.href && <Button asChild><Link to={action.href}>{action.label} →</Link></Button>}
      </ActionBar>
    </div>
  );
}

/** The decision's mark (prototype `qRow` `.kind`): the cleanup's ✂ 清理, a worse ad's grade move, 補素材. */
function markOf(item: QueueItem, rules: ReturnType<typeof useAdsRules>): { kind: "cut" | "worse" | "fresh"; label: string } | null {
  switch (item.kind_key) {
    case "cleanup": return { kind: "cut", label: "清理" };
    case "worse": {
      const move = item.triage.grade_move;
      return { kind: "worse", label: move && rules ? `從${gradeWord(rules, move.from)}變${gradeWord(rules, move.to)}` : "每筆變多了" };
    }
    case "refresh_creative": return { kind: "fresh", label: "補素材" };
    default: return null;
  }
}

/** An ended campaign's closeout row (F49 Contract Q): its served sentence, the end date, and what the platform still
 * runs at the last read (`closeout.running`). The step itself is the bar's 結案這一期 →. */
function CloseoutDecision({ row, campaign: c }: { row: CloseoutQueueRow; campaign: CampaignDetail }) {
  const { end_date: end, running } = row.closeout;
  const { timezone } = useOrgClock();
  const still = running.read_at === null ? "平台上的廣告還沒讀過"
    : running.count > 0 ? `平台上還在投 ${running.count} 則（${formatInstant(running.read_at, timezone, "md_hm")} 讀取）`
    : "平台上已沒有在投的廣告";
  return (
    <div className="grid grid-cols-[48px_minmax(0,1fr)_minmax(180px,240px)] items-center gap-4" data-testid="closeout-decision">
      <span className="grid size-12 place-items-center rounded-[10px] bg-zone-over text-xl text-danger" aria-hidden="true">■</span>
      <div className="min-w-0">
        {c.lifecycle && <KindMark kind="stop">{c.lifecycle.label}</KindMark>}
        <div className="mt-1.5 font-semibold [overflow-wrap:anywhere]">{row.message}</div>
      </div>
      <div className="numeric flex flex-col gap-0.5 text-[12.5px] text-muted-foreground">
        <span>{end ? `${md(end)} 結束` : "結束日未知"}</span>
        <span>{still}</span>
      </div>
    </div>
  );
}

/** Prototype `qRow(q, …, bare)`: the decision's mark and title, and its figure on the right. */
function NextDecision({ item, ads, cap, breakEven, workspace: ws }: {
  item: QueueItem; ads: RulerAd[] | null; cap: RulerCap | null; breakEven: number | null; workspace: CampaignWorkspace;
}) {
  const rules = useAdsRules();
  const mark = markOf(item, rules);
  let figure: ReactNode = null;
  if (item.kind_key === "cleanup" && ads) {
    figure = (
      <>
        <TargetRuler ads={ads} cap={cap} size="mini" tray={false} highlight={{ mode: "close", ids: (item.cleanup?.ads ?? []).map((a) => a.entity_id) }} />
        <div className="numeric mt-1 flex justify-between gap-2 text-[11.5px] text-muted-foreground">
          <span>{ws.daily_budget !== null && ws.can_support !== null ? `每日 ${formatAmount(ws.daily_budget)} 撐得起 ${ws.can_support} 則` : ""}</span>
          <span>在投 {ws.active_ads}</span>
        </div>
      </>
    );
  } else if (item.kind_key === "worse" && ads) {
    figure = (
      <>
        <TargetRuler ads={ads} cap={cap} size="mini" tray={false} highlight={{ mode: "self", ids: [item.triage.entity_id] }} />
        <div className="numeric mt-1 flex justify-between gap-2 text-[11.5px] text-muted-foreground">
          <span>每筆 {perSale(item.triage.current.cost_per_result)}<MoneyTag cost={item.triage.current.cost_per_result} breakEven={breakEven} /></span>
        </div>
      </>
    );
  }
  return (
    <div className="grid grid-cols-[48px_minmax(0,1fr)_minmax(180px,240px)] items-center gap-4">
      {item.kind_key === "cleanup"
        ? <span className="grid size-12 place-items-center rounded-[10px] bg-accent text-xl text-accent-foreground" aria-hidden="true">✂</span>
        : <Thumb url={item.triage.thumbnail_url} size={48} />}
      <div className="min-w-0">
        {mark && <KindMark kind={mark.kind}>{mark.label}</KindMark>}
        <div className="mt-1.5 font-semibold [overflow-wrap:anywhere]">{decisionTitle(item)}</div>
      </div>
      <div>{figure}</div>
    </div>
  );
}

/** Prototype `kvNumbers()`: the last 14 complete days (`totals`, one window) and what the budget carries. */
function KvNumbers({ campaign: c, workspace: ws }: { campaign: CampaignDetail; workspace: CampaignWorkspace }) {
  const labels = c.labels ?? DEFAULT_LABELS;
  const t = ws.totals;
  const cap = capOf(c);
  const rules = useAdsRules();
  const who = c.name.split("・")[0] || c.name;
  const closed = c.lifecycle?.state === "closed";
  // On the platform, nothing spent yet: an unknown money cell is 「還沒開始花」, not 「未知」 (Contract E).
  const notSpent = ws.delivery === "waiting" ? "還沒開始花" : "未知";
  const money = (v: number | null, format: (v: number | null) => string | null = formatAmount) => {
    const text = format(v);
    if (text === null) return notSpent;
    return !t?.currency || t.currency === "TWD" ? `${text} 元` : `${t.currency} ${text}`;
  };
  const cost = t?.cost_per_result ?? null;
  const results = t?.results ?? null;
  const spend = t?.spend ?? null;
  const roas = c.cap.price !== null && results !== null && spend !== null && spend > 0
    ? Math.round(((c.cap.price * results) / spend) * 100) / 100 : null;
  const unknownCost = spend === null || results === null ? notSpent : results === 0 ? "還沒有成交" : notSpent;
  const cell = "min-w-0 border-l border-border px-5 first:border-l-0 first:pl-0";
  const label = "block text-xs text-muted-foreground";
  const big = "my-0.5 block text-[22px] font-semibold tracking-tight";
  return (
    <section className={CARD} aria-label="近 14 天數字">
      <div className="grid grid-cols-4">
        <div className={cell}>
          <span className={label}>近 14 天花費</span>
          <b className={big}>{money(spend)}</b>
          <span className={label}>{t ? `${md(t.start)} – ${md(t.end)}` : "還沒有可讀的區間"}</span>
        </div>
        <div className={cell}>
          <span className={label}>{labels.conversion}</span>
          <b className={big}>{results === null ? "未知" : `${formatAmount(results)} 筆`}</b>
          <span className={label}>平台回報</span>
        </div>
        <div className={cell}>
          <span className={label}>{labels.conversion === "購買" ? "每賣一筆花多少" : labels.cpa}</span>
          <b className={big}>{cost === null ? <span className="text-base text-muted-foreground">{unknownCost}</span> : money(cost, perSaleAmount)}</b>
          {cost !== null && <MoneyTag cost={cost} breakEven={c.cap.break_even} />}
          {cost !== null && cap && rules && (
            <Meter value={cost} max={cap.value * 1.6} marker={cap.value}
              tone={cost <= cap.value ? "success" : cost <= watchLine(rules, cap.value) ? "warning" : "danger"} />
          )}
          <span className={label}>
            {cap ? <>{who}{cap.basis === "break_even" ? "暫用" : "的"}<Term k={cap.basis === "break_even" ? "break_even" : "cap"} value={c.cap.break_even}>{cap.basis === "break_even" ? "打平線" : "上限"}</Term> {formatAmount(cap.value)}</> : "沒設上限"}
            {roas !== null && `・ROAS 參考 ${formatAmount(roas)}`}
          </span>
        </div>
        {closed ? (
          <div className={cell}>
            <span className={label}>狀態</span>
            <b className="my-0.5 block text-[17px] font-semibold tracking-tight">
              {c.lifecycle?.label}{ws.active_ads > 0 && `・平台上還開著 ${ws.active_ads} 則`}
            </b>
          </div>
        ) : (
          <div className={cell}>
            <span className={label}>{ws.can_support !== null ? "在投／撐得起" : "在投"}</span>
            <b className={big}>{ws.can_support !== null ? `${ws.active_ads}／${ws.can_support} 則` : `${ws.active_ads} 則`}</b>
            <span className={label}>{ws.daily_budget !== null ? `每日 ${formatAmount(ws.daily_budget)}` : "每日預算未知"}</span>
          </div>
        )}
      </div>
    </section>
  );
}
