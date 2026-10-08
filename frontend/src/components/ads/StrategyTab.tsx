import { isRejected } from "@/lib/http";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Textarea } from "@/components/layout/ui/textarea";
import { EmptyState } from "@/components/layout/EmptyState";
import { SidePanel } from "@/components/layout/SidePanel";
import { useWorkspace } from "@/components/layout/WorkspaceContext";
import type { CoordinateLearnings } from "@/lib/adsLearningsApi";
import { formatDay, orgDateOf, resolveOrgTimezone } from "@/lib/orgClock";
import {
  adoptStrategy,
  generateStrategy,
  getCampaign,
  patchCampaign,
  selectScenario,
  setAllocation,
  type CampaignDetail,
  type ResplitRow,
  type SelectScenarioResult,
  type StrategyCoordinateLearning,
  type StrategyFact,
  type StrategyRole,
} from "@/lib/adsApi";
import { ActionBar, AllocationBar, Chip, Disclosure, GradeChip, formatAmount, LearningEvidenceCard, LearningEvidenceSource } from "./patterns";
import type { LearningEvidence } from "@/lib/adsLearningEvidence";
import { StrategyEvidence } from "./strategy/StrategyEvidence";
import { usedEvidence, unavailableCitations, unusedEvidence } from "./strategy/evidenceProjection";
import { perSaleAmount } from "./patterns/csv";
import { nextStep, type StepTarget } from "./nextStep";
import { CapBlock } from "./strategy/CapBlock";
import { BudgetScenarios, selectableScenario, type OverCapPending } from "./strategy/BudgetScenarios";
import { StrategyAssignmentSummary, StrategyCommitments } from "./strategy/StrategyCommitments";
import { LaunchSettingsCard } from "./publish/LaunchSettingsCard";
import { GroupSummary } from "./learnings/GroupSummary";
import { LearningsTable } from "./learnings/LearningsTable";

const ROLE_LABEL: Record<StrategyRole, string> = { new: "新客", retarget: "再行銷", explore: "探索" };
const errorText = (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback);
/** F50 Contract J (R7 B4): how often a running planner call is re-read. */
const BUSY_POLL_MS = 3000;

/** Prototype F41 ② `.lrn` (「用到的學習」): each ad of the last closed period the planner read — grade chip with its cost
 * per result, 「ad」（campaign）, then one chip per coordinate by its label (the API never sends a raw key here). */
function CoordinateLearningRows({ rows }: { rows: StrategyCoordinateLearning[] }) {
  return (
    <ul>
      {rows.map((row, i) => (
        <li key={`${row.ad_name}-${i}`} data-slot="coordinate-learning" className="border-t border-border py-2.5 text-[13px] first:border-t-0">
          <div className="flex flex-wrap items-center gap-2">
            <GradeChip grade={row.grade} label={`${row.grade_label}・每筆 ${row.cost_per_result === null ? "—" : perSaleAmount(row.cost_per_result)}（幣別未提供）`} />
            <span className="min-w-0 [overflow-wrap:anywhere]">「{row.ad_name}」（{row.campaign_name}）</span>
          </div>
          {row.coordinates.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1.5">
              {row.coordinates.map((k) => <Chip key={k.dimension}>{k.dimension_label}：{k.label}</Chip>)}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

/** F46 (prototype f46-learnings `#/strategy`): what the planner was prompted with. A strategy made since F46 carries
 * `ranked_learnings` (Contract L) — the same ranking as 品牌智庫「投放學到的」: the per-group summary, then each closed
 * campaign's rows (compact) and a link to the full table. Older strategies keep their `coordinate_learnings` rows. */
function UsedLearnings({ brandId, ranked, rows }: {
  brandId: string;
  ranked: CoordinateLearnings | undefined;
  rows: StrategyCoordinateLearning[];
}) {
  if (!ranked) return <CoordinateLearningRows rows={rows} />;
  return (
    <div data-slot="ranked-learnings">
      <p className="mb-2.5 text-xs text-muted-foreground">和品牌智庫「投放學到的」同一份排名</p>
      {ranked.groups.length > 0 && <div className="mb-3.5"><GroupSummary groups={ranked.groups} /></div>}
      <div className="flex flex-col gap-2.5">
        {ranked.campaigns.map((campaign) => <div key={campaign.campaign_id}><p className="mb-1 text-xs text-muted-foreground">來源金額幣別：{campaign.currency ?? "尚未核實"}</p><LearningsTable campaign={campaign} compact /></div>)}
      </div>
      <Link
        to={`/brands/${encodeURIComponent(brandId)}/library?tab=ads-learnings`}
        className="mt-2.5 inline-block text-[13px] font-medium text-primary hover:underline"
      >
        到品牌智庫看完整表 →
      </Link>
    </div>
  );
}

/** F48 Contract S: the lead word of each program-built fact line (the line itself is the API's `text`). */
const FACT_LEAD: Record<StrategyFact["kind"], string> = {
  groups: "顧客群", offers: "優惠", numbers: "數字", capacity: "預算", learnings: "學習",
};

/** The facts the program built for this strategy, one row each: a muted lead word, then the served sentence. */
function StrategyFacts({ facts }: { facts: StrategyFact[] }) {
  return (
    <ul data-slot="strategy-facts" className="flex flex-col gap-1">
      {facts.map((fact, i) => (
        <li key={`${fact.kind}-${i}`} data-kind={fact.kind} className="flex gap-2.5 text-[13px]">
          <span className="w-12 shrink-0 text-muted-foreground">{FACT_LEAD[fact.kind] ?? fact.kind}</span>
          <span className="min-w-0 [overflow-wrap:anywhere]">{fact.text}</span>
        </li>
      ))}
    </ul>
  );
}

const hasUsedLearnings = (ranked: CoordinateLearnings | undefined, rows: StrategyCoordinateLearning[]) =>
  ranked ? ranked.campaigns.length > 0 : rows.length > 0;

/** `MM/DD` of a basis date: a plain `YYYY-MM-DD` as is, a timestamp on the organisation's calendar; never the raw
 * ISO string. Unreadable → null. */
function basisDay(value: string | null | undefined, timezone: string): string | null {
  return formatDay(orgDateOf(value, timezone), "mmdd") || null;
}

const MEDIA_LABEL ={ photo: "只排照片（單圖、輪播）", photo_video: "照片和影片" } as const;

/** Prototype F41 ② `used` (F42-I13): what the plan may say — one chip per registered offer 「label：sentence」, per
 * proof its label (the proof text in the chip's title and accessible name), and the media the brand makes. Nothing
 * registered → one muted chip; `media` null (never asked) → no media chip. */
function MaterialsRow({ materials }: { materials: NonNullable<CampaignDetail["materials"]> }) {
  const empty = materials.offers.length === 0 && materials.proof.length === 0;
  return (
    <div data-slot="materials-used" className="mb-3 flex flex-wrap items-center gap-1.5">
      <span className="text-[12.5px] text-muted-foreground">可用素材：</span>
      {materials.offers.map((o) => <Chip key={`offer-${o.key}`} data-kind="offer">{o.label}：{o.sentence}</Chip>)}
      {materials.proof.map((p) => (
        <Chip key={`proof-${p.key}`} data-kind="proof" title={p.text} aria-label={`${p.label}：${p.text}`}>{p.label}</Chip>
      ))}
      {empty && <Chip data-kind="none">沒有登記優惠與證據，廣告只講產品本身</Chip>}
      {materials.media && <Chip data-kind="media">{MEDIA_LABEL[materials.media]}</Chip>}
    </div>
  );
}

/** 策略 tab（F28-I09，prototype v9 `tabStrategy()`）：一個上限（`CapBlock`）→ 這一期的總預算（`BudgetScenarios`，
 * internal only）→ 預算怎麼分 → 兩個收合（為什麼這樣建議／進階設定），底部一條動作列。v10 (F30-I07): 進階設定 holds the
 * launch settings every ad set uses (`LaunchSettingsCard`, the prototype's advanced fields; read only once the launch
 * is approved or the campaign is on a platform), and a draft's bar says 「下一步：素材」. The page decides nothing
 * about money itself: scenarios, over-cap amounts and the cap all come from the API; the only local state is what the
 * user has picked and not saved yet. */
export function StrategyTab({
  brandId,
  campaign: c,
  onCampaignChange,
  onChangeTab,
  launchApproved = null,
  onLaunchSettingsSaved,
}: {
  brandId: string;
  campaign: CampaignDetail;
  onCampaignChange: (campaign: CampaignDetail) => void;
  onChangeTab: (target: StepTarget) => void;
  /** The workspace's word on the launch approval (`stage`); null while unknown — the settings then stay read only. */
  launchApproved?: boolean | null;
  /** A launch-settings save landed (the workspace re-reads its progress). */
  onLaunchSettingsSaved?: () => void;
}) {
  const imported = c.origin === "imported";
  const draft = !imported && (c.status === "draft" || c.status === "ready");
  const settingsLocked = !draft || launchApproved !== false;
  const readonlyReason = c.capabilities?.unavailable.strategy ?? "既有活動保留平台設定，不使用內部策略與預算操作。";
  const [goal, setGoal] = useState(c.goal_text ?? "");
  const [goalSaving, setGoalSaving] = useState(false);
  const [goalError, setGoalError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [pending, setPending] = useState<OverCapPending | null>(null);
  const [basisOpen, setBasisOpen] = useState(false);
  const [sourceEvidence, setSourceEvidence] = useState<LearningEvidence | null>(null);
  const [basisReading, setBasisReading] = useState(false);
  const [basisReadError, setBasisReadError] = useState<string | null>(null);
  const basisTitle = useRef<HTMLHeadingElement>(null);
  useEffect(() => { if (basisOpen) basisTitle.current?.focus(); }, [basisOpen, sourceEvidence?.id]);
  const [allocationPct, setAllocationPct] = useState<Record<string, string> | null>(null);
  const [allocationSaving, setAllocationSaving] = useState(false);
  const [allocationError, setAllocationError] = useState<string | null>(null);
  const [primaryBusy, setPrimaryBusy] = useState(false);
  const [primaryError, setPrimaryError] = useState<string | null>(null);
  const [rejectedRevision, setRejectedRevision] = useState<string | null>(null);
  const adoption = useRef<{ revision: string; operationId: string } | null>(null);
  // F48 decision 8: the ad sets the last saved total re-split (an adopted, still unbound plan); null otherwise.
  const [resplit, setResplit] = useState<ResplitRow[] | null>(null);
  // F50 Contract J (R7 B4): a planner call still running for this campaign (`c.busy`, served by the campaign read, or
  // a 409 `campaign_busy` to a press) keeps the tab in its 產生中…／處理中… state; the campaign is re-read every 3 s
  // until `busy` is null, and the fresh campaign reloads the tab. So a reload during 展開投放結構 never shows the
  // empty state, and a second press is not sent while the first still runs.
  const [busyRefused, setBusyRefused] = useState(false);
  const [busyTick, setBusyTick] = useState(0);
  const waiting = Boolean(c.busy) || busyRefused;
  const changeRef = useRef(onCampaignChange);
  useEffect(() => { changeRef.current = onCampaignChange; }, [onCampaignChange]);
  useEffect(() => {
    if (!waiting) return;
    let alive = true;
    const timer = setTimeout(() => {
      getCampaign(brandId, c.id).then(
        (fresh) => {
          if (!alive) return;
          if (!fresh.busy) { setBusyRefused(false); setGenerateError(null); setPrimaryError(null); }
          changeRef.current(fresh);
          setBusyTick((n) => n + 1);
        },
        () => { if (alive) setBusyTick((n) => n + 1); }, // a failed re-read tries again on the next tick
      );
    }, BUSY_POLL_MS);
    return () => { alive = false; clearTimeout(timer); };
  }, [waiting, brandId, c.id, busyTick]);
  const timezone = resolveOrgTimezone(useWorkspace().identity?.org?.timezone);

  const strategy = imported ? undefined : c.budget_basis_json.strategy;
  const basis = c.budget_basis_json.basis;
  const step = nextStep(c);
  const pickedCandidate = picked ? c.budget_basis_json.scenarios?.scenarios.find((r) => r.key === picked) : null;
  const pickedRow = selectableScenario(pickedCandidate) ? pickedCandidate ?? null : null;
  const decision = strategy?.decision;
  const stale = strategy?.rationale_state === "stale" || decision?.state === "modified" ||
    Boolean(decision?.revision && rejectedRevision === decision.revision) ||
    Boolean(decision?.feasibility.reasons.some((reason) => reason.code === "strategy_changed"));
  const decisionBlocker = stale ? "安排或預算已修改，原建議理由已失效。請重新產生策略。" :
    !decision?.revision || decision.state === "legacy_unbound" || decision.slots.length === 0 ? "請重新產生策略並確認每則廣告的安排。" :
    decision.feasibility.state === "blocked" ? "這份安排目前無法採用，請調整預算或重新產生策略。" : "";

  async function handleGenerate() {
    setGenerating(true);
    setGenerateError(null);
    try {
      onCampaignChange(await generateStrategy(brandId, c.id));
      setRejectedRevision(null);
      adoption.current = null;
      setBasisReadError(null);
    } catch (err) {
      // A 502 carries the served sentence with the refusal reason; a 409 `campaign_busy` its served sentence.
      setGenerateError(errorText(err, "產生策略失敗，請稍後再試。"));
      if (isRejected(err, "campaign_busy")) setBusyRefused(true);
    } finally {
      setGenerating(false);
    }
  }

  async function rereadBasis() {
    setBasisReading(true);
    setBasisReadError(null);
    try {
      onCampaignChange(await getCampaign(brandId, c.id));
    } catch (err) {
      setBasisReadError(errorText(err, "最新依據讀取失敗。"));
    } finally {
      setBasisReading(false);
    }
  }

  function closeBasis() {
    setBasisOpen(false);
    setSourceEvidence(null);
  }

  async function run(action: () => Promise<void>, fallback: string) {
    setPrimaryBusy(true);
    setPrimaryError(null);
    try {
      await action();
    } catch (err) {
      setPrimaryError(errorText(err, fallback));
      if (isRejected(err, "campaign_busy")) setBusyRefused(true);
      if (isRejected(err, "strategy_changed")) setRejectedRevision(decision?.revision ?? null);
    } finally {
      setPrimaryBusy(false);
    }
  }

  /** A saved total: the campaign as the API returned it, and the re-split it reports (a draft reports none). */
  function budgetSaved(result: SelectScenarioResult) {
    onCampaignChange(result.campaign);
    setResplit(result.resplit && result.resplit.length > 0 ? result.resplit : null);
  }

  const saveBudget = () => run(async () => {
    if (!picked || !selectableScenario(pickedRow)) return;
    budgetSaved(await selectScenario(brandId, c.id, { scenario_key: picked, custom_total: null }));
    setPicked(null);
  }, "儲存預算失敗，請稍後再試。");

  const adopt = () => run(async () => {
    const revision = strategy?.decision?.revision;
    if (!revision || decisionBlocker || allocationPct !== null || basisReading || basisReadError) throw new Error(decisionBlocker || basisReadError || "先套用或取消比例調整。");
    if (adoption.current?.revision !== revision) {
      adoption.current = { revision, operationId: crypto.randomUUID() };
    }
    onCampaignChange(await adoptStrategy(brandId, c.id, {
      expected_revision: revision, operation_id: adoption.current.operationId,
    }));
    adoption.current = null;
    onChangeTab("structure");
  }, "展開投放結構失敗，請稍後再試。");

  function startAllocationEdit() {
    if (!strategy) return;
    const initial: Record<string, string> = {};
    for (const item of strategy.allocation) initial[item.role] = String(item.pct);
    setAllocationPct(initial);
    setAllocationError(null);
  }

  const allocationSum = allocationPct ? Object.values(allocationPct).reduce((sum, v) => sum + (Number(v) || 0), 0) : 0; // ZERO_OK: blank local percentage inputs contribute zero to the draft sum, not a served result.

  async function handleAllocationApply() {
    if (!allocationPct) return;
    setAllocationSaving(true);
    setAllocationError(null);
    try {
      const payload = Object.entries(allocationPct).map(([role, pct]) => ({ role, pct: Number(pct) }));
      onCampaignChange(await setAllocation(brandId, c.id, payload));
      setAllocationPct(null);
    } catch (err) {
      setAllocationError(errorText(err, "調整預算分配失敗，請稍後再試。"));
    } finally {
      setAllocationSaving(false);
    }
  }

  // Bottom bar (prototype `setBar` in `tabStrategy()`): an open over-cap sheet blocks saving; an unsaved in-cap pick
  // is saved here; otherwise the workspace's one next step. Adopting needs a cap and a budget the user chose.
  let primary: { label: string; onClick?: () => void; disabled?: boolean } | null = null;
  let hint = "";
  if (pending) {
    primary = { label: "儲存預算", disabled: true };
    hint = "先在上方確認要不要超出預算上限";
  } else if (pickedRow && pickedRow.total !== null) {
    primary = { label: `儲存預算 ${formatAmount(pickedRow.total)}`, onClick: () => void saveBudget() };
  } else if (step.id === "strategy_adopt") {
    const blocker = c.cap.value === null || c.cap.value <= 0 ? "先設上限" :
      c.budget_planned === null || c.budget_planned <= 0 ? "先選一個預算" :
      decisionBlocker || (allocationPct !== null ? "先套用或取消比例調整" : "");
    primary = { label: "確認策略，查看投放結構 →", onClick: () => void adopt(), disabled: blocker !== "" };
    hint = blocker || "確認後會建立以上安排；不會操作廣告平台。";
  } else if (draft && step.id !== "strategy_generate") {
    // Prototype `tabStrategy()`: a draft goes on to its material; a campaign already on a platform has no next step here.
    primary = { label: "下一步：素材 →", onClick: () => onChangeTab("assets"), disabled: c.cap.value === null };
    hint = c.cap.value === null ? "先設上限" : "";
  }

  const allocationTotal = pickedRow?.total ?? c.budget_planned;
  // A row's 元 is the API's own `amount` (F48 Contract M: `budget.split`, after adoption the groups' daily × days),
  // shown only for the saved budget: generating fills `amount` from the recommended total before the user chose
  // anything, and an unsaved pick is not split until it is saved (percent only until then).
  const showAmounts = c.budget_planned !== null && pickedRow === null;
  const coordinateLearnings = basis?.coordinate_learnings ?? [];
  const rankedLearnings = basis?.ranked_learnings;
  const usedLearnings = hasUsedLearnings(rankedLearnings, coordinateLearnings);
  const missingHandoff = c.manual_handoff?.groups.filter((group) => group.missing.length > 0) ?? [];
  const beforeAdoption = step.id === "strategy_adopt";

  return (
    <div data-slot="strategy-screen" className="flex min-w-0 flex-col">
      <div data-slot="strategy-body" className="flex min-w-0 flex-col gap-5">
        {strategy && <>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div><h2 className="text-[25px] font-semibold">這期策略</h2><p className="mt-1 text-sm text-muted-foreground">確認受眾與訊息安排，再查看投放結構。</p></div>
            <Chip tone={stale ? "warn" : decision?.state === "adopted" ? "ok" : "accent"}>{stale ? "需更新" : decision?.state === "adopted" ? "已確認" : "待你確認"}</Chip>
          </div>
          <dl data-slot="strategy-summary" className="surface grid grid-cols-3 gap-5 px-[22px] py-5 text-sm">
            <div className="min-w-0"><dt className="text-xs text-muted-foreground">這期商品</dt><dd className="mt-1 font-semibold [overflow-wrap:anywhere]">{basis?.evidence_context?.scope_label ?? basis?.prices[0]?.sell_way_name ?? "商品名稱尚未提供"}</dd></div>
            <div className="min-w-0"><dt className="text-xs text-muted-foreground">目標</dt><dd className="mt-1 font-semibold [overflow-wrap:anywhere]">{c.objective}</dd></div>
            <div><dt className="text-xs text-muted-foreground">可參考歷史</dt><dd className="mt-1 font-semibold">{basis?.evidence_context ? `${formatAmount(basis.evidence_context.eligible_count)} 條可參考經驗` : "歷史適用性尚未核實"}</dd></div>
          </dl>
          {(basisReading || waiting) && <p role="status" className="text-sm text-muted-foreground">{basisReading ? "正在重新讀取依據，保留原內容與尚未儲存的輸入。" : "策略背景工作處理中，完成後會重新讀取。"}</p>}
          {basisReadError && <div role="alert" className="surface flex flex-wrap items-center justify-between gap-3 p-4"><div><p className="text-sm">最新依據讀不到，保留上次內容。</p><p className="mt-1 text-xs text-muted-foreground">{basisReadError}</p></div><Button variant="outline" busy={basisReading} onClick={() => void rereadBasis()}>重新讀取</Button></div>}
          {stale && <p role="status" className="text-sm text-warning">原策略需更新後再確認；目前預算與尚未儲存的輸入仍保留。</p>}
          {basis?.evidence_context?.items.some((row) => row.contrary_count > 0) && <p role="status" className="text-sm text-warning">依據含反向觀察，請連同來源與限制判讀。</p>}
        </>}
        {!strategy && <CapBlock brandId={brandId} campaign={c} onCampaignChange={onCampaignChange} />}

        {!imported && !strategy && (
          <EmptyState
            title="這個活動還沒有策略建議"
            description={generateError ?? "讓行銷駕駛艙依商品與品牌資料規劃第一版策略。"}
            actionLabel={generating || waiting ? "產生中…" : "產生策略"}
            onAction={handleGenerate}
            actionBusy={generating} actionDisabledReason={waiting ? "背景工作還在處理，完成後才能再產生策略" : undefined}
          />
        )}

        {strategy && (
          <>
            <div className="grid min-w-0 grid-cols-1 items-start gap-5 min-[1101px]:grid-cols-[minmax(0,1.35fr)_minmax(250px,.8fr)]">
            <section className="surface min-w-0 px-[22px] py-5" aria-labelledby="allocation-title">
              <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
                <h2 id="allocation-title" className="text-base font-semibold">這期怎麼安排</h2>
                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-sm text-muted-foreground">{allocationTotal !== null ? `以 ${formatAmount(allocationTotal)} 計` : "選好預算後算金額"}</span>
                  {beforeAdoption && allocationPct === null && (
                    <Button variant="link" size="sm" className="h-auto px-0" onClick={startAllocationEdit}>調整比例</Button>
                  )}
                </div>
              </div>
              {decisionBlocker && <div className="mb-3 rounded-md border border-border p-3 text-sm">
                <p>{decisionBlocker}</p>
                <ul className="mt-1 space-y-1 text-[13px] text-muted-foreground">
                  {decision?.feasibility.reasons.map((reason, i) => <li key={`${reason.code}-${i}`}>{reason.message}</li>)}
                </ul>
                {draft && <Button variant="outline" size="sm" className="mt-2" busy={generating}
                  disabledReason={waiting || primaryBusy || allocationSaving ? "背景工作還在處理，請稍候" : undefined}
                  onClick={() => void handleGenerate()}>重新產生策略</Button>}
                {generateError && <p role="alert" className="mt-2 text-danger">{generateError}</p>}
              </div>}
              {allocationPct === null ? (
                <>
                  {/* Prototype F41 ② `.why`: one row per role — swatch, label, 「N%・M 元」, and the planner's reason. */}
                  <ul>
                    {strategy.allocation.map((item) => {
                      const amount = showAmounts ? formatAmount(item.amount) : null;
                      return (
                        <li key={item.role} data-slot="allocation-row" data-role={item.role} className="grid min-w-0 grid-cols-[70px_minmax(0,1fr)_65px] items-start gap-3 border-t border-border py-[22px] first:border-t-0">
                          <div><Chip tone={item.role === "new" ? "accent" : "neutral"}>{item.label}</Chip></div>
                          <div className="min-w-0">
                            <StrategyCommitments decision={decision} role={item.role} stale={stale} />
                            {!stale && item.rationale?.trim() && <p className="mt-1 text-[13px] text-muted-foreground [overflow-wrap:anywhere]">{item.rationale}</p>}
                          </div>
                          <div className="numeric text-right"><span className="text-[23px] text-primary">{formatAmount(item.pct)}%</span>{amount !== null && <span className="mt-1 block text-xs text-muted-foreground">{amount} 元</span>}</div>
                        </li>
                      );
                    })}
                  </ul>
                </>
              ) : (
                <div className="flex flex-col gap-2">
                  {strategy.allocation.map((item) => (
                    <label key={item.role} className="flex items-center gap-3 text-sm">
                      <span className="w-16">{ROLE_LABEL[item.role]}</span>
                      <Input
                        type="number"
                        className="max-w-24"
                        value={allocationPct[item.role] ?? ""}
                        onChange={(e) => setAllocationPct({ ...allocationPct, [item.role]: e.target.value })}
                      />
                      <span className="text-muted-foreground">%</span>
                    </label>
                  ))}
                  <p className="text-sm">合計 {allocationSum}%{allocationSum !== 100 && <span className="ml-2 text-muted-foreground">三個角色加起來要剛好 100%</span>}</p>
                  {allocationError && <p role="alert" className="text-sm text-danger">{allocationError}</p>}
                  <div className="flex gap-2">
                    <Button size="sm" variant="outline" busy={allocationSaving} disabledReason={allocationSum !== 100 ? "先調整成完整的預算分配" : undefined} onClick={() => void handleAllocationApply()}>
                      {allocationSaving ? "套用中…" : "套用"}
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => setAllocationPct(null)} busy={allocationSaving}>取消</Button>
                  </div>
                </div>
              )}
            <div className="-mx-[22px] mt-2">
              <Disclosure label="這輪想確認什麼"><ul className="space-y-2 text-[13px]">{!stale && (strategy.learning_goals ?? []).map((line, i) => <li key={i}>{line}</li>)}</ul>{(stale || !strategy.learning_goals?.length) && <p className="text-[13px] text-muted-foreground">{stale ? "原測試方向需隨策略更新後再確認。" : "這份策略尚未列出測試方向。"}</p>}</Disclosure>
              <Disclosure label="還有哪些未知"><ul className="space-y-2 text-[13px]">{strategy.unknowns.map((line, i) => <li key={i}>{line}</li>)}</ul>{strategy.unknowns.length === 0 && <p className="text-[13px] text-muted-foreground">沒有另列未知；觀察仍不是效果保證。</p>}</Disclosure>
            </div>
            </section>
            <StrategyEvidence basis={basis} decision={decision} onBasis={() => setBasisOpen(true)} />
            </div>

            <CapBlock brandId={brandId} campaign={c} onCampaignChange={onCampaignChange} />
            <BudgetScenarios
              brandId={brandId}
              campaign={c}
              picked={picked}
              onPick={setPicked}
              pending={pending}
              onPending={setPending}
              onCampaignChange={onCampaignChange}
              onBudgetSaved={budgetSaved}
              resplit={resplit}
            />
          </>
        )}

        {missingHandoff.length > 0 && (
          <div className="surface flex flex-wrap items-start justify-between gap-3 p-4">
            <div>
              <p className="text-sm font-medium">人工上架設定仍有必填資料待補</p>
              {missingHandoff.map((group) => (
                <p key={group.id} className="text-xs text-muted-foreground">{group.name}：{group.missing.join("、")}</p>
              ))}
            </div>
            <Button variant="outline" onClick={() => onChangeTab("structure")}>前往投放結構補齊</Button>
          </div>
        )}

        {strategy && (
          <Disclosure label="為什麼這樣建議">
            <div className="flex flex-col gap-3 text-sm">
              <StrategyAssignmentSummary decision={decision} />
              {c.materials && <MaterialsRow materials={c.materials} />}
              <AllocationBar parts={strategy.allocation.map((item) => ({ key: item.role, label: item.label, pct: item.pct }))} legend={false} />
              {/* F48 Contract S: the program's facts first; the model's prose below them has no numbers of its own. */}
              {(strategy.facts ?? []).length > 0 && <StrategyFacts facts={strategy.facts ?? []} />}
              {strategy.allocation.filter((item) => decision?.slots.some((slot) => slot.role === item.role)).map((item) => <section key={item.role} aria-label={`${item.label}安排依據`}>
                <h3 className="text-[13px] font-semibold">{item.label}安排依據</h3>
                <StrategyCommitments decision={decision} role={item.role} stale={stale} details />
              </section>)}
              {stale && <p className="text-muted-foreground">原建議理由已失效；重新產生後再確認新安排。</p>}
              {!stale && strategy.why.length > 0 && <ul className="list-disc space-y-1 pl-5">{strategy.why.map((line, i) => <li key={i}>{line}</li>)}</ul>}
              {!stale && (strategy.learning_goals ?? []).length > 0 && (
                <div>
                  <div className="mb-1 font-medium">這輪想學到什麼</div>
                  <ul className="list-disc space-y-1 pl-5">{(strategy.learning_goals ?? []).map((line, i) => <li key={i}>{line}</li>)}</ul>
                </div>
              )}
              {!stale && strategy.unknowns.length > 0 && (
                <div>
                  <div className="mb-1 font-medium">目前最大的未知</div>
                  <ul className="list-disc space-y-1 pl-5">{strategy.unknowns.map((line, i) => <li key={i}>{line}</li>)}</ul>
                </div>
              )}
              {strategy.why.length === 0 && strategy.unknowns.length === 0 && (strategy.learning_goals ?? []).length === 0 && (
                <p className="text-muted-foreground">這一輪沒有列出原因</p>
              )}
              {usedLearnings && (
                // F46: the ranking the planner read (older strategies: F41's per-ad grade rows).
                <section aria-labelledby="coordinate-learnings-title">
                  <h3 id="coordinate-learnings-title" className="mb-1 text-[12.5px] font-semibold">原活動排名與觀察</h3>
                  <UsedLearnings brandId={brandId} ranked={rankedLearnings} rows={coordinateLearnings} />
                </section>
              )}
              {basis && (
                <Button variant="outline" size="sm" className="w-fit" onClick={() => setBasisOpen(true)}>
                  查看策略依據 <ArrowRight size={12} className="ml-1 inline" />
                </Button>
              )}
            </div>
          </Disclosure>
        )}

        <Disclosure label="進階設定">
          {imported ? (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-muted-foreground">{readonlyReason}</p>
              <label htmlFor="campaign-goal" className="text-sm font-medium">內部活動目標</label>
              <Textarea id="campaign-goal" value={goal} onChange={(event) => setGoal(event.target.value)} />
              <p className="text-xs text-muted-foreground">供工作區管理使用，不會更改平台投放目標。</p>
              <Button className="w-fit" busy={goalSaving} disabledReason={!goal.trim() ? "先填寫活動目標" : goal === c.goal_text ? "目標尚未修改" : undefined} onClick={async () => {
                setGoalSaving(true); setGoalError(null);
                try { onCampaignChange(await patchCampaign(brandId, c.id, { goal_text: goal.trim(), objective: goal.trim() })); }
                catch (error) { setGoalError(errorText(error, "儲存目標失敗。")); }
                finally { setGoalSaving(false); }
              }}>{goalSaving ? "儲存中…" : "儲存目標"}</Button>
              {goalError && <p role="alert" className="text-sm text-danger">{goalError}</p>}
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              <LaunchSettingsCard brandId={brandId} campaign={c} locked={settingsLocked}
                onSaved={() => onLaunchSettingsSaved?.()} onCampaignSaved={onCampaignChange} />
              <Button variant="link" size="sm" className="h-auto w-fit px-0" onClick={() => onChangeTab("structure")}>前往人工上架設定</Button>
            </div>
          )}
        </Disclosure>
      </div>

      <ActionBar
        back={<div className="flex flex-wrap items-center gap-2"><Button variant="ghost" onClick={() => onChangeTab("overview")}>← 總覽</Button><Button variant="outline" asChild><Link to={`/brands/${brandId}/library?tab=ads-learnings`}>查看品牌學習</Link></Button></div>}
        hint={primaryError ?? (primary?.disabled ? undefined : hint)}
      >
        {primary && (
          <Button busy={primaryBusy} disabledReason={basisReading ? "先完成依據讀取" : basisReadError && step.id === "strategy_adopt" ? "先讀取最新依據，才能確認這份策略" : waiting || generating ? "背景工作還在處理，請稍候" : primary.disabled ? hint : undefined} onClick={primary.onClick}>
            {primaryBusy || waiting ? "處理中…" : primary.label}
          </Button>
        )}
      </ActionBar>

      {basisOpen && basis && (
        // Prototype f46-learnings `#/strategy` `.sp`: 用到的學習 first, then the brand facts and prices it used.
        <SidePanel ariaLabel={sourceEvidence ? "經驗來源與適用範圍" : "策略依據"} onClose={closeBasis} widthClassName="w-[600px]">
          <div className="flex flex-col gap-5">
            <h3 ref={basisTitle} tabIndex={-1} className="text-lg font-semibold outline-none">{sourceEvidence ? "經驗來源與適用範圍" : "這份策略用了哪些依據"}</h3>
            {stale && <p className="text-sm text-warning">這是原策略引用的依據；需更新策略後核對適用條件。</p>}
            {sourceEvidence ? <><LearningEvidenceSource evidence={sourceEvidence} audienceLabel={decision?.slots.find((slot) => slot.customer_group_id !== null && slot.customer_group_id === sourceEvidence.scope.customer_group_id)?.display?.customer_group_label} /><Button variant="outline" className="w-fit" onClick={() => setSourceEvidence(null)}>返回策略依據</Button></> : <>
            <section>
              <h4 className="mb-2 text-sm font-semibold">用到的學習</h4>
              {usedEvidence(basis, decision).length === 0 && <p className="text-sm text-muted-foreground">這份安排尚未列出已核實的學習引用。</p>}
              {usedEvidence(basis, decision).map((row) => <LearningEvidenceCard key={row.id} evidence={row} onSource={setSourceEvidence} />)}
            </section>
            {unavailableCitations(basis, decision).length > 0 && <section>
              <h4 className="mb-2 text-sm font-semibold">已引用但目前不可用</h4>
              {unavailableCitations(basis, decision).map(row => <LearningEvidenceCard key={row.id} evidence={row} onSource={setSourceEvidence} />)}
            </section>}
            <section><h4 className="mb-2 text-sm font-semibold">未用於提案的資料</h4>{unusedEvidence(basis, decision).map((row) => <LearningEvidenceCard key={row.id} evidence={row} onSource={setSourceEvidence} />)}
              {basis.learnings.filter((row) => !row.evidence).map((row) => <div key={row.id} className="py-2 text-sm"><p>{row.text}</p><p className="text-xs text-muted-foreground">歷史適用性尚未核實</p></div>)}
            </section>
            {usedLearnings && <section><h4 className="mb-2 text-sm font-semibold">原活動排名與觀察</h4><UsedLearnings brandId={brandId} ranked={rankedLearnings} rows={coordinateLearnings} /></section>}
            <section>
              <h4 className="mb-2 text-sm font-semibold">品牌事實</h4>
              {basis.brand_facts.length === 0 ? (
                <p className="text-sm text-muted-foreground">沒有用到品牌事實。</p>
              ) : (
                <ul className="text-[13.5px]">
                  {basis.brand_facts.map((f) => {
                    const day = basisDay(f.updated_at, timezone);
                    return (
                      <li key={f.id} data-slot="basis-fact" className="flex justify-between gap-3 border-t border-border py-[5px] first:border-t-0">
                        <span className="min-w-0 [overflow-wrap:anywhere]">{f.label}</span>
                        <span className="whitespace-nowrap text-xs text-muted-foreground">{day ? `${day} 更新` : "更新日不明"}</span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
            <section>
              <h4 className="mb-2 text-sm font-semibold">商品價格</h4>
              {basis.prices.length === 0 ? (
                <p className="text-sm text-muted-foreground">沒有用到商品價格。</p>
              ) : (
                <ul className="text-[13.5px]">
                  {basis.prices.map((p) => {
                    const day = basisDay(p.effective_from, timezone);
                    return (
                      <li key={p.product_id} data-slot="basis-price" className="flex justify-between gap-3 border-t border-border py-[5px] first:border-t-0">
                        <span className="min-w-0 [overflow-wrap:anywhere]">
                          {p.sell_way_name} {p.price !== null ? `${formatAmount(p.price)}（幣別未提供）` : "價格尚未設定"}
                          {p.stale && <span className="ml-1 text-warning">價格可能過期</span>}
                        </span>
                        <span className="whitespace-nowrap text-xs text-muted-foreground">{day ? `${day} 起` : "起始日不明"}</span>
                      </li>
                    );
                  })}
                </ul>
              )}
              {basis.assumption_note && <p className="mt-2 text-sm text-warning">{basis.assumption_note}</p>}
            </section>
            {basis.evidence_context?.omitted ? <p className="text-xs text-muted-foreground">另有 {basis.evidence_context.omitted} 條紀錄未列出，請到品牌學習查看。</p> : null}
            <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={closeBasis}>返回策略</Button><Button variant="ghost" busy={basisReading} onClick={() => void rereadBasis()}>重新讀取依據</Button></div>
            </>}
          </div>
        </SidePanel>
      )}
    </div>
  );
}
