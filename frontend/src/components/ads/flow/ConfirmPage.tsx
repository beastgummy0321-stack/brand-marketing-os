import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { formatCount } from "@/lib/format";
import {
  approveChangeSet,
  createChangeSet,
  decideChangeSet,
  getChangeControl,
  getMonthlyBudget,
  ChangeRequestRejected,
  type ChangeDraft,
  type ChangeItem,
  type ChangeSet,
  type MonthlyBudget,
} from "@/lib/adsChangeApi";
import { getQueue, type QueueItem, type QueuePayload, type QueueScale, type TriageItem } from "@/lib/adsTriageApi";
import { getAngles, type AnglesResponse, type AnglesStatus } from "@/lib/adsAnglesApi";
import { budgetMoney, currentBudgetMonth } from "../MonthlyBudgetPanel";
import { reviewRoundPath } from "../review/reviewFlow";
import { ActionBar, Chip, DecisionSheet, FlowHeader, KindMark, LearnCard, Meter, Segmented, TagToggle } from "../patterns";
import { CleanupEvidence } from "./CleanupEvidence";
import { NewAdEvidence } from "./NewAdEvidence";
import { Tile } from "./Tile";
import {
  buildBudgetDraftItem,
  buildCleanupDraftItems,
  buildPauseDraftItem,
  budgetTitle,
  campaignChangesPath,
  changeStepPath,
  cleanupTitle,
  isCleanupTriageItem,
  isMonthBudgetRejection,
  itemAngle,
  nextOpenQueueItem,
  pauseTitle,
  queueItemEntityId,
  stepFromChangeSet,
  toChangeInput,
  formatAmount,
  formatTargetAmount,
} from "./changeFlow";

const STEPS = [{ label: "確認提議" }, { label: "到平台完成" }, { label: "核對結果" }];
const STEP_PURPOSE = "核准後才到平台操作";

/** 暫停提議的證據卡：有 triage 就是完整量尺版；triage 已經不在佇列裡（entered by :setId 且
 * 廣告已離開佇列）就退回只有名稱與理由的版本（feature Decisions「Confirm (pause)」）。 */
function PauseEvidence({ triage, fallbackName, fallbackReason }: {
  triage: TriageItem | null; fallbackName: string; fallbackReason: string;
}) {
  if (!triage) {
    return (
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="flex items-center gap-4">
          <Tile url={null} />
          <div className="min-w-0 flex-1">
            <KindMark kind="stop">停損</KindMark>
            <p className="mt-1.5 truncate text-[15px] font-semibold">{fallbackName}</p>
          </div>
        </div>
        <p className="mt-3 text-sm text-muted-foreground">{fallbackReason}</p>
      </div>
    );
  }
  const line = triage.target.value === null ? null : triage.target.value * 3;
  const max = line === null ? null : line * 1.5;
  const countText = triage.current.result_count === null
    ? "累積中"
    : `${formatCount(triage.current.result_count)} 筆${triage.current.result_label}`;
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-center gap-4">
        <Tile url={triage.thumbnail_url} />
        <div className="min-w-0 flex-1">
          <KindMark kind="stop">停損</KindMark>
          <p className="mt-1.5 truncate text-[15px] font-semibold" title={triage.name ?? "（未命名廣告）"}>
            {triage.name ?? "（未命名廣告）"}
          </p>
        </div>
        <Chip tone="ok">✓ 不會新增花費</Chip>
      </div>
      <div className="mt-4 max-w-[560px]">
        <Meter
          value={triage.current.spend}
          max={max}
          marker={line}
          tone="danger"
          left={<>已花 <b className="text-foreground">{formatAmount(triage.current.spend)}</b>・{countText}・{triage.window.days} 天</>}
          right={<>停損線 {formatTargetAmount(line)}（目標 × 3）</>}
        />
      </div>
    </div>
  );
}

const ANGLE_MAX = 40;

/** 暫停提議的「這則主打什麼？」卡（Contract C/D，v7 原型 `confirmPage()` 的 `.learn`）：`angles`
 * 還在跑（LLM 任務排隊中，正常會走到的第一個狀態）畫骨架佔位；判斷完成就是三顆 TagToggle；判斷
 * 失敗（或 e2e 腳本化供應商不認得這個新工作類型，correction 9）只剩「＋ 自訂」——兩種狀態都能
 * 再點「＋ 自訂」換成手動輸入，不是互斥的兩套 UI。選到的內容（含自訂）就是要送出的 `angle`，
 * 不選就是 `undefined`（`buildPauseDraftItem` 對空字串／未選一律不送這個欄位）。 */
function PauseLearnCard({ status, candidates, angle, customOpen, disabled, onSelect, onOpenCustom, onCustomChange }: {
  status: AnglesStatus; candidates: string[]; angle: string; customOpen: boolean; disabled: boolean;
  onSelect: (value: string) => void; onOpenCustom: () => void; onCustomChange: (value: string) => void;
}) {
  const trimmed = angle.trim();
  return (
    <LearnCard
      title="這則主打什麼？"
      aside={trimmed
        ? <>暫停後記入品牌學習<br /><b className="text-foreground">「{trimmed}」對這群受眾無效</b></>
        : "選一個，暫停後記入品牌學習"}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        {status === "pending" && [0, 1, 2].map((i) => <Skeleton key={i} className="h-7 w-16 rounded-full" />)}
        {status === "ready" && candidates.map((c) => (
          <TagToggle key={c} on={!customOpen && angle === c} disabled={disabled} onClick={() => onSelect(c)}>{c}</TagToggle>
        ))}
        {status !== "pending" && (
          <TagToggle on={customOpen} disabled={disabled} onClick={onOpenCustom}>＋ 自訂</TagToggle>
        )}
      </div>
      {customOpen && (
        <Input
          className="mt-2 h-8 max-w-[220px] text-sm"
          aria-label="自訂主打"
          value={angle}
          maxLength={ANGLE_MAX}
          disabled={disabled}
          onChange={(e) => onCustomChange(e.target.value)}
          placeholder="輸入這則廣告主打什麼"
        />
      )}
    </LearnCard>
  );
}

function CopyEvidence({ item }: { item: ChangeItem }) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <div className="flex items-center gap-4">
        <Tile url={null} />
        <div className="min-w-0 flex-1">
          <Chip tone="accent">改文案・圖片不變</Chip>
          <p className="mt-1.5 truncate text-[15px] font-semibold">{item.target.name ?? "（未命名廣告）"}</p>
        </div>
        <Chip tone="ok">✓ 不會新增花費</Chip>
      </div>
      <div className="mt-4 grid grid-cols-1 items-center gap-3 md:grid-cols-[1fr_auto_1fr]">
        <div className="rounded-md bg-muted p-3 text-sm">
          <b className="block">{item.before.title ?? "—"}</b>
          <p className="mt-1 whitespace-pre-wrap text-muted-foreground">{item.before.body ?? "—"}</p>
        </div>
        <div aria-hidden="true" className="text-center text-xl text-muted-foreground">→</div>
        <div className="rounded-md bg-accent/60 p-3 text-sm">
          <b className="block">{item.after.title ?? "—"}</b>
          <p className="mt-1 whitespace-pre-wrap">{item.after.body ?? "—"}</p>
        </div>
      </div>
      <p className="mt-3 text-sm text-muted-foreground">原因：{item.reason}</p>
    </div>
  );
}

// 圖例色點跟長條分段同一組 token，跟 `home/BudgetCard.tsx::Swatch` 同一份色碼（design-system
// §2.1，v7 原型的 `.lg i`）——不 import 那支：`home/`／`flow/` 是同一個功能資料夾底下的兩顆小零
// 件，各自留一份比為了一顆兩行的 dot 特地打通兩邊耦合合理。
const SWATCH_TONE = { "chart-rest": "bg-chart-rest", border: "bg-border", success: "bg-success", primary: "bg-primary" } as const;
function Swatch({ tone }: { tone: keyof typeof SWATCH_TONE }) {
  return <span aria-hidden="true" className={`inline-block size-2 rounded-sm ${SWATCH_TONE[tone]}`} />;
}

/** 三段可用度長條＋圖例，跟 `home/BudgetCard.tsx` 同一份色碼與誠實未知邏輯（原型 `budgetBar()`）。
 * `extra`（這次加碼，F25-I03 `scale.month.extra_needed`）> 0 時多畫一段成功色，「可用」跟著扣掉
 * `extra`（原型 `available-extra`）——沒有 `extra` 的既有（非 scale）預算變更清單維持原本兩段。
 * 圖例固定印已花／預留／可用（`extra` 才印這次加碼），即使長條本身因為總額未知只能畫灰階，
 * 數字仍照實印（design-system §7「誠實的空狀態」，同 `home/BudgetCard.tsx` 的做法）。 */
function MiniBudgetBar({ budget, extra = 0 }: { budget: MonthlyBudget; extra?: number }) {
  const { amount, known_spend, ongoing_estimate, available, currency } = budget;
  const known = amount !== null && amount > 0 && known_spend !== null && ongoing_estimate !== null && available !== null;
  const pct = (v: number) => Math.max(0, Math.min(100, (v / (amount as number)) * 100));
  const availableAfterExtra = available === null ? null : available - extra;
  return (
    <div className="mt-2 space-y-1.5">
      <div className="flex h-2 w-full overflow-hidden rounded-full bg-muted" aria-hidden="true">
        {known && (
          <>
            <div className="bg-chart-rest" style={{ width: `${pct(known_spend as number)}%` }} />
            <div className="bg-border" style={{ width: `${pct(ongoing_estimate as number)}%` }} />
            {extra > 0 && <div className="bg-success" style={{ width: `${pct(extra)}%` }} />}
            <div className="bg-primary" style={{ width: `${pct(Math.max(0, availableAfterExtra as number))}%` }} />
          </>
        )}
      </div>
      <div className="numeric flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><Swatch tone="chart-rest" />已花 {budgetMoney(known_spend, currency)}</span>
        <span className="inline-flex items-center gap-1.5"><Swatch tone="border" />預留 {budgetMoney(ongoing_estimate, currency)}</span>
        {extra > 0 && <span className="inline-flex items-center gap-1.5"><Swatch tone="success" />這次加碼 {budgetMoney(extra, currency)}</span>}
        <span className="inline-flex items-center gap-1.5"><Swatch tone="primary" />可用 {budgetMoney(availableAfterExtra, currency)}</span>
      </div>
    </div>
  );
}

/** 加預算提議的證據卡（F25-I03，v7 原型 `confirmPage()` 的 budget 分支）。`scale` 有值（propose
 * 網址進來，或 `:setId` 進來但這個提議的擁有者還在佇列裡）畫完整版：同組則數、購買成本量尺、
 * 主力廣告穩定 2 期、本月預算放得下（含這次加碼段）；`scale` 是 `null`（提議的擁有者已經離開
 * 佇列，同 `PauseEvidence` 的 fallback）就退回只有名稱／金額／原因的版本——`item` 這時才派上用場
 * （`scale` 有值時一律讀 `scale`/`triage` 這組即時資料，不讀凍結在 `item.before/after` 的舊值，
 * 這樣第一次進頁面、`item` 都還沒建立時也能完整顯示提議內容）。 */
function BudgetEvidence({ item, scale, bestAdThumbnailUrl, brandId }: {
  item: ChangeItem | undefined; scale: QueueScale | null; bestAdThumbnailUrl: string | null; brandId: string;
}) {
  const [budget, setBudget] = useState<MonthlyBudget | null>(null);
  const [budgetError, setBudgetError] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getMonthlyBudget(brandId, currentBudgetMonth())
      .then((b) => { if (!cancelled) setBudget(b); })
      .catch(() => { if (!cancelled) setBudgetError(true); });
    return () => { cancelled = true; };
  }, [brandId]);
  const before = scale ? scale.from : item?.before.daily_amount ?? null;
  const after = scale ? scale.to : item?.after.daily_amount ?? null;
  const pct = before !== null && after !== null && before > 0 ? Math.round(((after - before) / before) * 100) : null;
  const extra = scale?.month.extra_needed ?? 0;
  const targetValue = scale?.target.value ?? null;
  const meterMax = targetValue !== null && targetValue > 0 ? targetValue * 1.5 : null;
  return (
    <>
      <div className="rounded-xl border border-border bg-card p-5">
        <div className="flex items-center gap-4">
          <Tile icon={<span aria-hidden="true" className="text-2xl">💰</span>} />
          <div className="min-w-0 flex-1">
            <KindMark kind="up">可加預算</KindMark>
            <p className="mt-1.5 truncate text-[15px] font-semibold">
              {scale
                ? `${scale.owner.name ?? "未命名投放組"}・同組 ${scale.owner.ads_count} 則一起受影響`
                : (item?.target.name ?? "（未命名投放組）")}
            </p>
          </div>
          <div className="text-right">
            <p className="text-xs text-muted-foreground">每日預算</p>
            <p className="numeric flex items-center gap-2 text-lg font-semibold">
              <span>{formatTargetAmount(before)} → {formatTargetAmount(after)}</span>
              {pct !== null && <Chip tone="ok">{pct > 0 ? "+" : ""}{pct}%</Chip>}
            </p>
          </div>
        </div>
        {scale && (
          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
            <Meter
              value={scale.cost_per_result}
              max={meterMax}
              marker={targetValue}
              tone="success"
              left={<>{scale.target.result_label}成本 {formatAmount(scale.cost_per_result)}</>}
              right={<>目標 {formatTargetAmount(targetValue)}</>}
            />
            <div className="flex items-center gap-2">
              <Tile url={bestAdThumbnailUrl} size="sm" />
              <span className="text-sm">主力穩定 2 個觀察期</span>
            </div>
            <div className="flex items-center text-sm text-muted-foreground">加碼後等 3–5 天再看</div>
          </div>
        )}
        {!scale && <p className="mt-3 text-sm text-muted-foreground">原因：{item?.reason}</p>}
      </div>
      <div className="rounded-xl border border-border bg-card p-5">
        <h2 className="text-sm font-medium">本月預算放得下</h2>
        {budgetError && <p className="mt-2 text-sm text-warning">月預算暫時讀取不到，不影響上面的核准內容。</p>}
        {!budgetError && !budget && <p className="mt-2 text-sm text-muted-foreground">正在整理月預算…</p>}
        {budget && <MiniBudgetBar budget={budget} extra={extra} />}
      </div>
    </>
  );
}

type DecisionKind = "rejected" | "deferred";
type QuickPick = "3" | "7" | "custom";

/** 確認提議頁（F22-I02，v7 原型 `confirmPage()`＋拒絕／暫緩 sheet；budget 分支 F25-I03）。兩條
 * 路由共用同一支元件：`entityId`（propose route）還沒有 change set，草稿只在第一次核准／拒絕／
 * 暫緩時才建立（feature Decisions「Agent choice — the draft is created lazily」，never on page
 * load）；`setId`（changes route）已經有 change set，直接讀。`proposeKind` 只在 `entityId` 進來、
 * 還沒有 change set 時分辨這是暫停提議還是加預算提議（`item` 這時還不存在，不能靠
 * `item.kind` 分支）——`setId` 進來時一律讀 `changeSet` 自己的 kind，不受這個參數影響。任何非
 * confirm 的步驟都由這裡導去正確步驟（`changeFlow.ts::stepFromChangeSet`），也同時把 propose
 * 網址收斂成正典的 changes 網址。 */
export function ConfirmPage({ brandId, campaignId, entityId, setId, proposeKind = "pause" }: {
  brandId: string; campaignId: string; entityId?: string; setId?: string; proposeKind?: "pause" | "budget" | "cleanup";
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const homeHref = `/brands/${brandId}/ads`;

  const [queue, setQueue] = useState<QueuePayload | null>(null);
  const [changeSet, setChangeSet] = useState<ChangeSet | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // F27-I15 Contract F: `propose/cleanup/:campaignId` never carries an `entityId` (the campaign
  // id is already a prop) — a third branch alongside the existing budget/pause ones.
  const [operationId] = useState(() => {
    if (entityId && proposeKind === "budget") return `triage-budget:${entityId}:${crypto.randomUUID()}`;
    if (proposeKind === "cleanup") return `triage-cleanup:${campaignId}:${crypto.randomUUID()}`;
    return `triage-pause:${entityId ?? ""}:${crypto.randomUUID()}`;
  });
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const [sheetOpen, setSheetOpen] = useState(false);
  const [decisionKind, setDecisionKind] = useState<DecisionKind>("deferred");
  const [reason, setReason] = useState("想再觀察幾天");
  const [quickPick, setQuickPick] = useState<QuickPick>("7");
  const [customDate, setCustomDate] = useState("");
  const [sheetError, setSheetError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    const tasks: Promise<unknown>[] = [
      getQueue(brandId).then((q) => { if (!cancelled) setQueue(q); }).catch(() => {}),
    ];
    if (setId) {
      tasks.push(
        getChangeControl(brandId, campaignId)
          .then((data) => { if (!cancelled) setChangeSet(data.change_sets.find((s) => s.id === setId) ?? null); })
          .catch((err) => { if (!cancelled) setLoadError(err instanceof Error ? err.message : "讀取這份變更清單失敗，請稍後再試。"); }),
      );
    }
    Promise.all(tasks).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [brandId, campaignId, setId, reloadKey]);

  const triageItem: QueueItem | null = useMemo(() => {
    if (!queue) return null;
    if (entityId) {
      // F25-I03：加預算的 propose 網址帶的是 `scale.owner.id`（投放組／活動），不是廣告的
      // `triage.entity_id`——兩種 id 空間不同，不能沿用暫停提議那顆比對式（feature Decisions
      // 「Confirm page budget propose mode」：route 讀 `scale.owner.id === entityId`）。
      if (proposeKind === "budget") {
        return queue.items.find((i) => i.kind_key === "scale_budget" && i.scale?.owner.id === entityId) ?? null;
      }
      return queue.items.find((i) => i.triage.entity_id === entityId) ?? null;
    }
    // F27-I15 Contract F: the cleanup propose route has no `entityId` — its own identity is the
    // campaign, matched through the queue's `cleanup` row directly (`item.cleanup.campaign_id`,
    // same field `changeFlow.ts::queueItemEntityId` reads for this `kind_key`).
    if (!setId && proposeKind === "cleanup") {
      return queue.items.find((i) => isCleanupTriageItem(i) && i.cleanup?.campaign_id === campaignId) ?? null;
    }
    const targetId = changeSet?.items[0]?.target_id;
    return queue.items.find((i) =>
      (changeSet && i.proposal?.change_set_id === changeSet.id) || i.triage.entity_id === targetId || i.scale?.owner.id === targetId,
    ) ?? null;
  }, [queue, entityId, proposeKind, changeSet, setId, campaignId]);
  const position = queue && triageItem ? { pos: queue.items.indexOf(triageItem) + 1, total: queue.items.length } : null;
  // F27-I15 Contract F: recognised only through the queue's own `cleanup` row — see
  // `isCleanupTriageItem`'s own doc comment (`changeFlow.ts`) for why this isn't a shape guess.
  const cleanupSet = isCleanupTriageItem(triageItem);
  const isCleanupPropose = !entityId && !setId && proposeKind === "cleanup";

  // F27-I16: `closed`／`item`／`kind`／`blocked` used to be computed after the loading／error
  // guards below (they only ever needed `changeSet`, never the guards' own state) — moved up here
  // so the angle-fetching hooks right after them can read `kind`／`closed` too, without a hook
  // ending up after a conditional `return` (React's hook-order rule; `useEffect` can't move below
  // the guards instead).
  const { closed } = changeSet ? stepFromChangeSet(changeSet) : { closed: false };
  const item = changeSet && changeSet.items.length === 1 ? changeSet.items[0] : undefined;
  // `item` 在 propose 模式、change set 還沒建立前是 `undefined`（草稿延遲建立），這時 kind 由
  // 路由本身的 `proposeKind` 決定，不能沿用舊的「沒有 item 就當 pause」（F25-I03 之前唯一的
  // propose kind 只有 pause，這裡是新加的分支）。F27-I15：cleanup 是多項清單，沒有單一 `item`
  // 可讀，`cleanupSet`（佇列比對，不是內容猜測）優先於這整套 `item`／`proposeKind` 判斷。
  const kind = cleanupSet ? "cleanup" : item ? item.kind : entityId ? proposeKind : "pause";
  const blocked = changeSet !== null && !cleanupSet
    && (changeSet.items.length !== 1 || !["pause", "copy", "budget", "new_ad"].includes(kind));

  // Contract C / correction 9: 「一則廣告一次 copy hash 一顆 LLM call，暫停提議頁一開就打」——
  // `entityId`（propose 網址）或既有草稿的 `item.target_id` 都是同一則廣告的 id；`!closed` 只是
  // 不在已經拒絕／暫緩、不會再送出的清單上浪費呼叫（核准之後這頁本來就會被 `stepFromChangeSet`
  // 導去 handoff／verify，不會停留在這裡）。
  const pauseEntityId = kind === "pause" ? (entityId ?? item?.target_id ?? triageItem?.triage.entity_id ?? null) : null;
  const [angleData, setAngleData] = useState<AnglesResponse | null>(null);
  const [angleChoice, setAngleChoice] = useState("");
  const [angleCustomOpen, setAngleCustomOpen] = useState(false);
  useEffect(() => {
    setAngleChoice(itemAngle(item) ?? "");
    setAngleCustomOpen(false);
    setAngleData(null);
    if (kind !== "pause" || closed || !pauseEntityId) return;
    let cancelled = false;
    getAngles(brandId, campaignId, pauseEntityId)
      .then((res) => { if (!cancelled) setAngleData(res); })
      .catch(() => { if (!cancelled) setAngleData({ status: "failed", candidates: [], error: null }); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `item` narrowed to `item?.id`：整個
    // `item` 物件每次 `getChangeControl` 重新讀取都是新的參照，只有身分（id）真的換了才需要重置
    // 選取狀態或重打一次 `getAngles`。
  }, [kind, closed, pauseEntityId, brandId, campaignId, item?.id]);

  // feature Decisions「Step from a change set」：非 confirm 步驟的清單，或還沒對到正典
  // changes/:setId 網址的 propose 頁，都在這裡收斂——I03/I04 加了 handoff/verify 頁之後這裡
  // 才會真的把人送到那兩頁；這批只加了 propose 與 confirm 兩條路由。
  useEffect(() => {
    if (!changeSet) return;
    const { step } = stepFromChangeSet(changeSet);
    const canonical = changeStepPath(brandId, campaignId, changeSet.id, step);
    if (canonical !== location.pathname) navigate(canonical, { replace: true });
  }, [changeSet, brandId, campaignId, location.pathname, navigate]);

  function errorMessage(err: unknown): string {
    return err instanceof Error ? err.message : "發生未知錯誤，請稍後再試。";
  }

  /** 拿到可以動作的 change set：`changeSet` 已經有就直接用；propose 模式第一次寫入時，
   * 先看佇列列有沒有既有提議（`proposal.change_set_id`），有就重用，沒有才建立新草稿
   * （feature Decisions「first reuse proposal.change_set_id when the queue row has one」）。
   * 草稿內容依 `proposeKind` 分支：budget 一定要有 `triageItem.scale`（propose 網址只會比對到
   * `kind_key==="scale_budget"` 的列，見上面 `triageItem` 的 `useMemo`），沒有就是資料還沒讀到。 */
  async function ensureWorkingSet(): Promise<ChangeSet> {
    if (changeSet) return changeSet;
    const existingId = triageItem?.proposal?.change_set_id;
    if (existingId) {
      const data = await getChangeControl(brandId, campaignId);
      const found = data.change_sets.find((s) => s.id === existingId);
      if (found) return found;
    }
    if (proposeKind === "budget") {
      const scale = triageItem?.scale;
      if (!scale) throw new Error("這個投放組的資料還沒讀到，請重新整理後再試。");
      return createChangeSet(brandId, campaignId, {
        operation_id: operationId,
        title: budgetTitle(scale.owner.name),
        month: currentBudgetMonth(),
        items: [buildBudgetDraftItem(scale.owner.id, scale.to)],
      });
    }
    if (proposeKind === "cleanup") {
      const cleanup = triageItem?.cleanup;
      if (!cleanup) throw new Error("這個活動的清理資料還沒讀到，請重新整理後再試。");
      // F27-I15 Contract F / coordinator correction: the backend only accepts `source: "cleanup"`
      // on create once F27-I25 lands its own `ChangeDraft.source?`/`CreateRequest.source` widening
      // (out of this issue's touch, `frontend/src/lib/adsChangeApi.ts`). Widen the type locally at
      // the call site rather than editing that file or stopping — `createChangeSet` just
      // `JSON.stringify`s `body` as-is, so the extra key reaches the backend regardless of the
      // narrower `ChangeDraft` type.
      return createChangeSet(brandId, campaignId, {
        operation_id: operationId,
        title: cleanupTitle(cleanup.campaign_name),
        month: currentBudgetMonth(),
        items: buildCleanupDraftItems(cleanup.ads),
        source: "cleanup",
      } as ChangeDraft & { source: "cleanup" });
    }
    if (!triageItem) throw new Error("這則廣告的資料還沒讀到，請重新整理後再試。");
    // Contract C: whatever the user picked (a candidate tag or the custom input) at the moment of
    // this first write — `undefined` reason keeps `buildPauseDraftItem`'s own default.
    return createChangeSet(brandId, campaignId, {
      operation_id: operationId,
      title: pauseTitle(triageItem.triage.name),
      month: currentBudgetMonth(),
      items: [buildPauseDraftItem(triageItem.triage.entity_id, undefined, angleChoice)],
    });
  }

  async function approveWithRebuild(target: ChangeSet, rebuilt: boolean): Promise<ChangeSet> {
    try {
      return await approveChangeSet(brandId, campaignId, target);
    } catch (err) {
      // feature Decisions「When approve answers 409 because the premise changed」：只重建一次，
      // 用新的 operation_id 帶 supersedes_id 再核准一次；再失敗就照一般錯誤處理，不無限重試。
      // 月預算放不下的 409（`isMonthBudgetRejection`）不是「前提變了」，是「這個月的餘額真的不夠」
      // ——重建一份一樣內容的草稿再核准一次只會得到同一個錯誤，還多留一份沒用的草稿；這種 409
      // 直接把後端訊息顯示出來，不重建（feature Decisions「a 409 from approve about the month
      // budget shows the backend message and does NOT rebuild」）。
      if (err instanceof ChangeRequestRejected && !rebuilt && !isMonthBudgetRejection(err.message)) {
        // F27-I15: a cleanup set's rebuild must carry `source: "cleanup"` again — otherwise the
        // rebuilt draft would silently stop being the campaign's cleanup proposal (Contract F's
        // own `_matching_cleanup_set` only matches on `plan_json.source`).
        const rebuiltSet = await createChangeSet(brandId, campaignId, {
          operation_id: crypto.randomUUID(),
          title: target.title,
          month: target.month,
          items: target.items.map(toChangeInput),
          supersedes_id: target.id,
          ...(cleanupSet ? { source: "cleanup" as const } : {}),
        } as ChangeDraft & { source?: "cleanup" });
        setChangeSet(rebuiltSet);
        return approveWithRebuild(rebuiltSet, true);
      }
      throw err;
    }
  }

  async function handleApprove() {
    if (busy) return;
    setBusy(true);
    setActionError(null);
    try {
      const target = await ensureWorkingSet();
      const updated = await approveWithRebuild(target, false);
      setChangeSet(updated);
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  function openSheet() {
    setDecisionKind("deferred");
    setReason("想再觀察幾天");
    setQuickPick("7");
    setCustomDate("");
    setSheetError(null);
    setSheetOpen(true);
  }

  function revisitAt(): Date | null {
    if (decisionKind !== "deferred") return null;
    if (quickPick === "custom") {
      if (!customDate) return null;
      const d = new Date(customDate);
      return Number.isNaN(d.getTime()) ? null : d;
    }
    const d = new Date();
    d.setDate(d.getDate() + (quickPick === "3" ? 3 : 7));
    return d;
  }
  const revisit = revisitAt();
  const revisitValid = decisionKind !== "deferred" || (revisit !== null && revisit.getTime() > Date.now());

  async function handleSaveDecision() {
    if (busy) return;
    const trimmedReason = reason.trim();
    if (!trimmedReason) { setSheetError("請填寫原因。"); return; }
    if (!revisitValid) { setSheetError("請選一個之後的時間。"); return; }
    setBusy(true);
    setSheetError(null);
    setActionError(null);
    try {
      const target = await ensureWorkingSet();
      const updated = await decideChangeSet(brandId, campaignId, target.id, {
        decision: decisionKind,
        reason: trimmedReason,
        ...(decisionKind === "deferred" ? { revisit_at: revisit!.toISOString() } : {}),
      });
      setChangeSet(updated);
      setSheetOpen(false);
    } catch (err) {
      setSheetError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "確認" }]} />
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-28 w-full max-w-[560px]" />
      </div>
    );
  }
  if (loadError) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "確認" }]} />
        <EmptyState title="讀取失敗" description={loadError} onAction={() => setReloadKey((k) => k + 1)} actionLabel="重新讀取" />
      </div>
    );
  }
  if ((entityId || isCleanupPropose) && !triageItem) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "確認" }]} />
        <EmptyState
          title={proposeKind === "budget" ? "找不到這個投放組的加預算提議" : isCleanupPropose ? "找不到這個活動的清理提議" : "找不到這則廣告的停損提議"}
          description="可能已經處理過，或資料剛好還沒同步到投放中心。"
          actionHref={homeHref}
          actionLabel="回投放中心"
          actionInternal
        />
      </div>
    );
  }
  if (setId && !changeSet) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "確認" }]} />
        <EmptyState
          title="找不到這份變更清單"
          description="網址可能過期，或這份清單已經被另一份取代。"
          actionHref={homeHref}
          actionLabel="回投放中心"
          actionInternal
        />
      </div>
    );
  }

  if (blocked && changeSet) {
    return (
      <div className="flex flex-col gap-4">
        <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "確認" }]} />
        <EmptyState
          title="這份清單有多項變更"
          description="請到活動的「變更與核對」查看完整內容並逐項處理。"
          actionHref={campaignChangesPath(brandId, campaignId)}
          actionLabel="前往變更與核對"
          actionInternal
        />
      </div>
    );
  }

  const title = kind === "copy" ? "確認變更"
    : kind === "budget" ? "提議：加預算"
    : kind === "new_ad" ? "確認新廣告提議"
    : kind === "cleanup" ? "提議：清理這個活動的廣告"
    : "提議：暫停這則廣告";
  const approveLabel = kind === "copy" ? "核准，接著到平台操作"
    : kind === "budget" ? "核准加碼，接著到平台操作"
    : kind === "new_ad" ? "核准新廣告，接著到平台操作"
    : kind === "cleanup" ? "核准清理，接著到平台操作"
    : "核准暫停，接著到平台操作";
  const closedLabel = changeSet
    ? (changeSet.status === "superseded" ? "已由新清單取代" : `${changeSet.status === "rejected" ? "已拒絕" : "已暫緩"}・${changeSet.reason ?? ""}`)
    : "";
  // 「下一件」（F25-I03）：跟 VerifyPage 共用同一顆判斷，不各自算各自的（feature Decisions
  // 「下一件」）。目前這件的識別碼：propose 網址就是 `entityId` 本身；`setId` 網址（含已關閉的
  // 清單）從比對到的 `triageItem` 反推。
  const currentEntityId = entityId ?? (triageItem ? queueItemEntityId(triageItem) : undefined);
  const nextAction = closed ? nextOpenQueueItem(queue, currentEntityId) : null;
  // 改文案清單、還沒關閉（草稿）、承接自某一輪檢討：返回鍵改成「修改內容」回那一輪的改文案頁
  // （v7 原型 `confirmPage()` 的 `back:i.kind==="copy"?["修改內容",...]`）；已關閉或核准之後的清單
  // （`stepFromChangeSet` 這裡不會再回傳 confirm 步驟）都留原本的「投放中心」（issue Done 3）。
  const editCopyHref = !closed && kind === "copy" && changeSet?.review_id
    ? reviewRoundPath(brandId, campaignId, changeSet.review_id, "copy")
    : null;

  return (
    <div className="flex min-h-[calc(100dvh-108px)] flex-col gap-4 xl:min-h-[calc(100dvh-120px)]">
      <Breadcrumb items={[{ label: "投放中心", href: homeHref }, { label: "確認" }]} />
      <FlowHeader
        steps={STEPS}
        current={0}
        title={title}
        purpose={STEP_PURPOSE}
        aside={closed ? <Chip tone="neutral">{closedLabel}</Chip> : undefined}
        context={triageItem ? (
          <>
            <Badge variant="outline" className="max-w-[14rem] shrink" title={triageItem.triage.campaign_name}>
              <span className="block w-full min-w-0 truncate">{triageItem.triage.campaign_name}</span>
            </Badge>
            {position && <span>第 {position.pos} 件／共 {position.total} 件</span>}
          </>
        ) : undefined}
      />

      {kind === "pause" && (
        <PauseEvidence
          triage={triageItem?.triage ?? null}
          fallbackName={item?.target.name ?? "（未命名廣告）"}
          fallbackReason={item?.reason ?? ""}
        />
      )}
      {kind === "copy" && item && <CopyEvidence item={item} />}
      {kind === "budget" && (
        <BudgetEvidence
          item={item}
          scale={triageItem?.scale ?? null}
          bestAdThumbnailUrl={triageItem?.triage.thumbnail_url ?? null}
          brandId={brandId}
        />
      )}
      {kind === "new_ad" && item && <NewAdEvidence item={item} />}
      {kind === "cleanup" && (
        <CleanupEvidence
          cleanup={triageItem?.cleanup ?? null}
          items={changeSet?.items ?? []}
          campaignName={triageItem?.triage.campaign_name ?? null}
        />
      )}

      {/* Contract C/D: only while there's still a decision to make — once closed (rejected／
          暫緩), the angle chosen (or not) is already fixed and nothing more will be recorded. */}
      {kind === "pause" && !closed && (
        <PauseLearnCard
          status={angleData?.status ?? "pending"}
          candidates={angleData?.candidates ?? []}
          angle={angleChoice}
          customOpen={angleCustomOpen}
          disabled={busy}
          onSelect={(c) => { setAngleChoice(c); setAngleCustomOpen(false); }}
          onOpenCustom={() => { setAngleCustomOpen(true); setAngleChoice(""); }}
          onCustomChange={(v) => setAngleChoice(v.slice(0, ANGLE_MAX))}
        />
      )}

      {actionError && <p role="alert" className="text-sm text-destructive">{actionError}</p>}

      <div className="flex-1" />
      <ActionBar
        back={<Button variant="ghost" asChild><Link to={editCopyHref ?? homeHref}>← {editCopyHref ? "修改內容" : "投放中心"}</Link></Button>}
        hint={!closed ? "核准不會改動平台" : undefined}
      >
        {!closed && (
          <Button variant="outline" disabled={busy} onClick={openSheet}>拒絕／暫緩</Button>
        )}
        {!closed ? (
          <Button disabled={busy} onClick={() => void handleApprove()}>{busy ? "處理中…" : `${approveLabel} →`}</Button>
        ) : nextAction ? (
          <Button asChild><Link to={nextAction.href}>下一件 →</Link></Button>
        ) : null}
      </ActionBar>

      {sheetOpen && (
        <DecisionSheet
          actions={<>
            <Button variant="outline" disabled={busy} onClick={() => setSheetOpen(false)}>取消</Button>
            <Button disabled={busy} onClick={() => void handleSaveDecision()}>{busy ? "保存中…" : "保存"}</Button>
          </>}
        >
          <Segmented
            label="決定"
            options={[{ value: "deferred", label: "暫緩" }, { value: "rejected", label: "拒絕" }]}
            value={decisionKind}
            onChange={setDecisionKind}
          />
          <label className="flex min-w-[200px] flex-1 flex-col gap-1 text-sm">
            原因
            <Input value={reason} onChange={(e) => setReason(e.target.value)} disabled={busy} />
          </label>
          {decisionKind === "deferred" && (
            <label className="flex flex-col gap-1 text-sm">
              何時重看
              <div className="flex items-center gap-2">
                <Segmented
                  label="何時重看"
                  options={[{ value: "3", label: "3 天後" }, { value: "7", label: "7 天後" }, { value: "custom", label: "自訂" }]}
                  value={quickPick}
                  onChange={setQuickPick}
                />
                {quickPick === "custom" && (
                  <Input type="date" aria-label="重看日期" value={customDate} onChange={(e) => setCustomDate(e.target.value)} disabled={busy} />
                )}
              </div>
            </label>
          )}
          {sheetError && <p role="alert" className="w-full text-xs text-destructive">{sheetError}</p>}
        </DecisionSheet>
      )}
    </div>
  );
}
