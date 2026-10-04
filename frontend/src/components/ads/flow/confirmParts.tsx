import { useId, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Skeleton } from "@/components/layout/Skeleton";
import { formatCount, formatCurrency } from "@/lib/format";
import type { ChangeItem, MonthlyBudget, OngoingOwner } from "@/lib/adsChangeApi";
import type { QueueScale, TriageItem } from "@/lib/adsTriageApi";
import type { AnglesStatus } from "@/lib/adsAnglesApi";
import type { ApiRead } from "@/lib/useApiRead";
import { Chip, GradeChip, KindMark, LearnCard, Meter, ReadFailed, TagToggle, Term, figure, rulerScale, unsoldLine, useAdsRules } from "../patterns";
import { Tile } from "./Tile";
import { formatAmount, formatTargetAmount } from "./changeFlow";
import { perSaleAmount } from "../patterns/csv";

/** The evidence and learn cards of the confirm step (`ConfirmPage`), split out so the page stays under the
 * 800-line cap (`architectureBoundaries.test.ts`). The cards are page-private except `BudgetFitCard`, which the
 * first-launch list (`publish/PublishList.tsx`, F41-I05) reuses so the month-budget card exists once. */

const nt = (value: number | null) => (value === null ? formatCurrency(null) : `NT$ ${perSaleAmount(value)}`);

/** The stop-loss meter (prototype F45 `evidence()`): with sales, the cost per sale against the cap; without, the
 * spend against the served 沒賣出 line (`unsoldLine`, F48 Contract R-API). The axis is the kit's cost axis around a
 * mark (`rulerScale`). No cap → captions only (the kit `Meter` draws no guessed bar); while the rules load the
 * no-sales meter shows the cap alone — no line is drawn from a copy of the rule. */
function PauseMeter({ triage }: { triage: TriageItem }) {
  const rules = useAdsRules();
  const cap = triage.target.value;
  const count = triage.current.result_count;
  const cost = triage.current.cost_per_result;
  const spend = triage.current.spend;
  if (count !== null && count > 0) {
    const max = cap === null || cost === null ? null : rulerScale(cap, [cost]).max;
    return (
      <Meter
        value={cost} max={max} marker={cap} tone="danger"
        left={<>每筆 <b className="text-foreground">{nt(cost)}</b></>}
        right={cap === null ? <><Term k="cap">上限</Term>還沒設定</> : <><Term k="cap">上限</Term> {nt(cap)}</>}
      />
    );
  }
  const line = cap === null || !rules ? null : unsoldLine(rules, cap);
  return (
    <Meter
      value={spend} max={line === null ? null : rulerScale(line, spend === null ? [] : [spend]).max} marker={line} tone="danger"
      left={<>已花 <b className="text-foreground">{nt(spend)}</b>・{count === null ? "成交累積中" : "還沒有成交"}</>}
      right={cap === null
        ? <><Term k="cap">上限</Term>還沒設定</>
        : line === null || !rules
          ? <><Term k="cap">上限</Term> {nt(cap)}</>
          : <>花到 {nt(line)} 還一筆都沒賣，就算「<Term k="wasted">{rules.labels.grade.wasted}</Term>」（上限 × {figure(rules.grade.unsold_spend_multiple)}）</>}
    />
  );
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0 rounded-[10px] bg-background px-3 py-2.5">
      <small className="block text-xs text-muted-foreground">{label}</small>
      <b className="numeric mt-0.5 block text-xl font-semibold tracking-tight">{children}</b>
    </div>
  );
}

/** 暫停提議的證據卡（F45-I06，prototype F45 `evidence()`）：這則廣告自己的花費／成交／每筆成本／評級、量尺與
 * 「這則廣告自己的數字・〈window〉」。`closed`（已經停了）把右上的「✓ 不會新增花費」換成「已暫停・…」並淡化縮圖。
 * triage 讀不到（:setId 進來、廣告已離開佇列）就退回只有名稱與理由的版本（feature Decisions「Confirm (pause)」）。
 * F48 Contract R：`reason` 是後端從這則自己的評級與數字組出的句子（草稿已存的、或 `pause_view.reason_text`），
 * 照印；`null` 不印。 */
export function PauseEvidence({ triage, fallbackName, reason, closed = null, windowLine = null }: {
  triage: TriageItem | null; fallbackName: string; reason: string | null;
  /** The 已暫停 chip text when the ad is already closed; `null` = still running. */
  closed?: string | null;
  /** 「〈MM/DD〉～〈MM/DD〉・N 天」 — the ad's own window. */
  windowLine?: string | null;
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
        {reason && <p className="mt-3 text-sm text-muted-foreground">{reason}</p>}
      </div>
    );
  }
  const m = triage.current;
  const purchase = (m.result_kind ?? triage.target.result_kind) === "purchase";
  const countLabel = purchase ? "成交" : triage.target.result_label;
  return (
    <div className="rounded-xl border border-border bg-card px-[22px] py-5" data-state={closed ? "closed" : "active"}>
      <div className="flex flex-wrap items-center gap-3">
        <div className={closed ? "opacity-70 grayscale-[.6]" : undefined}><Tile url={triage.thumbnail_url} /></div>
        <div className="min-w-0 flex-1">
          <KindMark kind="stop">停損</KindMark>
          <p className="mt-1.5 text-[15px] font-semibold [overflow-wrap:anywhere]">{triage.name ?? "（未命名廣告）"}</p>
        </div>
        {closed ? <Chip>{closed}</Chip> : <Chip tone="ok">✓ 不會新增花費</Chip>}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        <Stat label="花費">{nt(m.spend)}</Stat>
        <Stat label={countLabel}>{m.result_count === null ? "累積中" : `${formatCount(m.result_count)} 筆`}</Stat>
        <Stat label="每筆成本">{m.result_count ? nt(m.cost_per_result) : "—"}</Stat>
        <Stat label="評級"><GradeChip grade={triage.grade} label={triage.grade_label} className="px-3 py-[3px] align-middle text-[13px]" /></Stat>
      </div>
      <div className="mt-3.5 max-w-[560px]"><PauseMeter triage={triage} /></div>
      {windowLine && <p className="mt-3 text-xs text-muted-foreground">這則廣告自己的數字・{windowLine}</p>}
      {reason && <p className="mt-2 text-sm">原因：{reason}</p>}
    </div>
  );
}

/** Contract P `gone` (prototype F45 `pausePage()` not found): why there is nothing to pause, and one exit. */
export function PauseGone({ name, lastRead, homeHref }: { name: string | null; lastRead: string | null; homeHref: string }) {
  return (
    <div data-state="not_found" className="surface flex flex-col items-center gap-2.5 px-6 py-12 text-center">
      <div aria-hidden="true" className="grid size-[52px] place-items-center rounded-[14px] bg-muted text-[22px] text-muted-foreground">?</div>
      <h2 className="text-[15px] font-semibold">找不到這則廣告</h2>
      <p className="max-w-[420px] text-[12.5px] text-muted-foreground">
        {name ? `「${name}」` : "這則廣告"}在平台上已經刪除，系統讀不到它，沒有東西可以暫停。{lastRead ? `（最後一次讀到是 ${lastRead}）` : ""}
      </p>
      <Button asChild><Link to={homeHref}>回投放中心</Link></Button>
    </div>
  );
}

export const ANGLE_MAX = 40;

/** 暫停提議的「這則主打什麼？」卡（Contract C/D，v7 原型 `confirmPage()` 的 `.learn`）：`angles`
 * 還在跑（LLM 任務排隊中，正常會走到的第一個狀態）畫骨架佔位；判斷完成就是三顆 TagToggle；判斷
 * 失敗（或 e2e 腳本化供應商不認得這個新工作類型，correction 9）只剩「＋ 自訂」——兩種狀態都能
 * 再點「＋ 自訂」換成手動輸入，不是互斥的兩套 UI。選到的內容（含自訂）就是要送出的 `angle`，
 * 不選就是 `undefined`（`buildPauseDraftItem` 對空字串／未選一律不送這個欄位）。`onRetry` 只在「讀取本身失敗」
 * （Contract K，不是後端判斷失敗）時給：多一塊 `ReadFailed` 可重試，「＋ 自訂」照樣可用。 */
export function PauseLearnCard({ status, candidates, angle, customOpen, disabled, onSelect, onOpenCustom, onCustomChange, onRetry }: {
  status: AnglesStatus; candidates: string[]; angle: string; customOpen: boolean; disabled: boolean;
  onSelect: (value: string) => void; onOpenCustom: () => void; onCustomChange: (value: string) => void;
  onRetry?: () => void;
}) {
  const trimmed = angle.trim();
  return (
    <LearnCard
      title="這則主打什麼？"
      aside={trimmed
        ? <>暫停後記入品牌學習<br /><b className="text-foreground">「{trimmed}」對這群受眾無效</b></>
        : "選一個，暫停後記入品牌學習"}
    >
      {onRetry && (
        <div className="mb-2">
          <ReadFailed what="AI 整理的主打讀不到；可以重試，或按「＋ 自訂」自己填" onRetry={onRetry} />
        </div>
      )}
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

export function CopyEvidence({ item }: { item: ChangeItem }) {
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
const SWATCH_TONE = { "chart-rest": "bg-chart-rest", border: "bg-border", success: "bg-success", danger: "bg-danger", primary: "bg-primary" } as const;
function Swatch({ tone }: { tone: keyof typeof SWATCH_TONE }) {
  return <span aria-hidden="true" className={`inline-block size-2 rounded-sm ${SWATCH_TONE[tone]}`} />;
}

/** `YYYY-MM` → the month number the copy names (「10 月」). */
function monthOf(month: string): number {
  return Number(month.split("-")[1]) || 0;
}
/** A month-budget amount as the prototype prints it (bare, thousands-separated); `null` is the honest unknown. */
function money(value: number | null): string {
  return value === null ? "尚待確認" : formatAmount(value);
}

/** The word 預留 with its definition on hover／focus／tap (prototype `term("reserve", "預留")`, same `.term` look
 * as `patterns/Term.tsx`). The shared glossary has no entry for it and `patterns/` is outside this page's scope,
 * so the one sentence lives here beside the only card that uses it. */
function ReserveTerm() {
  const id = useId();
  return (
    <span
      data-slot="term" tabIndex={0} aria-describedby={id}
      onKeyDown={(e) => { if (e.key === "Escape") e.currentTarget.blur(); }}
      className="group/term relative inline cursor-help border-b border-dotted border-current outline-offset-2"
    >
      預留
      <span
        role="tooltip" id={id}
        className="absolute top-[calc(100%+6px)] left-0 z-30 hidden w-max max-w-[min(260px,70vw)] rounded-lg bg-foreground px-[11px] py-2 text-left text-xs leading-normal font-normal tracking-normal whitespace-normal text-white group-hover/term:block group-focus/term:block"
      >
        還在跑的活動這個月剩下的天數要花的錢，先留著不算可用；跑完就還回來。
      </span>
    </span>
  );
}

/** F48 Contract M "month portion" (`change_control_launch.month_fit`'s `extra_basis`): the launch's days inside the
 * month and the campaign's whole-period total. */
export interface ExtraBasis { month: number; days: number; period_total: number | null }
/** The launch's spend words: 「{N} 月的 {days} 天要花 X（整期 Y）」 with a basis (no 整期 part without a total), else the
 * plain 「這期要花 X」 (an older backend). Every number is served; nothing is recomputed here. */
function extraSpendText(extra: number, basis: ExtraBasis | null): string {
  if (!basis) return `這期要花 ${money(extra)}`;
  const whole = basis.period_total === null ? "" : `（整期 ${money(basis.period_total)}）`;
  return `${basis.month} 月的 ${basis.days} 天要花 ${money(extra)}${whole}`;
}

const RESERVE_OWNERS_SHOWN = 3;
/** The 預留 explanation under the bar (issue Done 1): one clause per running budget owner, largest commitment
 * first, at most three named, the rest counted as 「等 N 項」. No owner → no line (nothing is reserved for). */
function reserveLine(owners: OngoingOwner[]): string | null {
  if (owners.length === 0) return null;
  const sorted = [...owners].sort((a, b) => b.commitment - a.commitment);
  const parts = sorted.slice(0, RESERVE_OWNERS_SHOWN)
    .map((o) => `${o.name ?? "未命名投放組"} 還有 ${o.days} 天沒跑完，每天 ${formatAmount(o.daily)}`);
  const more = sorted.length > RESERVE_OWNERS_SHOWN ? `等 ${sorted.length} 項` : "";
  return `預留＝${parts.join("；")}${more} 先留著；跑完就還回來。`;
}

/** 四段長條＋圖例（F40 原型 `budgetBar()`：已花／預留／這次要花／還剩），跟 `home/BudgetCard.tsx` 同一份
 * 色碼與誠實未知邏輯。預留＝`ongoing_estimate + reserved_increases`（後端 `preflight` 從 `available` 扣掉的
 * 兩筆）；`extra`（這次要花，F25-I03 `scale.month.extra_needed`）> 0 才多畫一段成功色並從還剩扣掉——
 * 沒有 `extra` 的既有（非 scale）預算變更清單維持三段。總額未知時長條只畫灰階，數字仍照實印
 * （design-system §7「誠實的空狀態」）。`launch`（F41-I05 第一次上架清單，原型 `#/publish` 的 `budgetBar()`）：
 * 這段叫「這期要花」，放不下時截到剩下的額度、改畫危險色，最後一格印「不夠 X」。 */
function BudgetBar({ budget, extra = 0, launch = false, extraText }: {
  budget: MonthlyBudget; extra?: number; launch?: boolean;
  /** The extra segment's legend words (`extraSpendText`); default 「這次要花 X」. */
  extraText?: string;
}) {
  const { amount, known_spend, ongoing_estimate, reserved_increases, available } = budget;
  const reserved = ongoing_estimate === null ? null : ongoing_estimate + reserved_increases;
  const known = amount !== null && amount > 0 && known_spend !== null && reserved !== null && available !== null;
  const pct = (v: number) => Math.max(0, Math.min(100, (v / (amount as number)) * 100));
  const left = available === null ? null : available - extra;
  const short = launch && left !== null && left < 0;
  const extraWidth = launch && available !== null ? Math.min(extra, Math.max(0, available)) : extra;
  const extraTone = short ? "danger" : "success";
  return (
    <div className="mt-2 space-y-1.5">
      <div className="flex h-2 w-full overflow-hidden rounded-full bg-muted" aria-hidden="true">
        {known && (
          <>
            <div className="bg-chart-rest" style={{ width: `${pct(known_spend as number)}%` }} />
            <div className="bg-border" style={{ width: `${pct(reserved as number)}%` }} />
            {extra > 0 && <div className={SWATCH_TONE[extraTone]} style={{ width: `${pct(extraWidth)}%` }} />}
            <div className="bg-primary" style={{ width: `${pct(Math.max(0, left as number))}%` }} />
          </>
        )}
      </div>
      <div className="numeric flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><Swatch tone="chart-rest" />已花 {money(known_spend)}</span>
        <span className="inline-flex items-center gap-1.5"><Swatch tone="border" /><ReserveTerm /> {money(reserved)}</span>
        {extra > 0 && <span className="inline-flex items-center gap-1.5"><Swatch tone={extraTone} />{extraText ?? `這次要花 ${money(extra)}`}</span>}
        <span className="inline-flex items-center gap-1.5"><Swatch tone="primary" />{short ? `不夠 ${money(-(left as number))}` : `還剩 ${money(left)}`}</span>
      </div>
    </div>
  );
}

/** 「本月預算放得下」卡的三個狀態（F40-I08，原型 `#/approve`）：(iii) `premiseChanged`——核准被 409 擋下、
 * 前提變了，標題＋「重新檢查」（重建草稿，`ConfirmPage` 的既有動作）；(ii) 這個月還沒設月預算——標題＋
 * 「設定 N 月月預算 →」連去月預算所在的投放中心首頁；(i) 放得下——算式標題（月預算 − 已花 − 預留）、
 * 四段長條、`ongoing_owners` 的預留說明。`uncertainties` 三態都照印在標題下（後端 `preflight` 的原句）。
 * 核准鈕該不該灰、旁邊的原因，由 `ConfirmPage` 從同一份 `read` 判斷（`approveBlock`），不在這裡另算一份。
 * `launch`（F41-I05，原型 `#/publish`）只給第一次上架清單：多一個 (iv) 放不下——「N 月只剩 X」、「這期要花 Y」、
 * 「提高 N 月月預算」（`budgetHref`）與「改這期總預算」（`launch.strategyHref`）；沒給時 `ConfirmPage` 照舊。
 * F48 Contract M：`launch.extraBasis`（後端 `month_fit.extra_basis`）在時，「這期要花 X」改印「{N} 月的 {days} 天要花 X
 * （整期 Y）」——數字照後端給的印，瀏覽器不換算。加預算頁的「這次要花」不變。 */
export function BudgetFitCard({ read, month, extra = 0, premiseChanged, busy, onRecheck, budgetHref, launch }: {
  read: ApiRead<MonthlyBudget | null>; month: string; extra?: number;
  premiseChanged: boolean; busy: boolean; onRecheck: () => void; budgetHref: string;
  launch?: { strategyHref: string; extraBasis?: ExtraBasis | null };
}) {
  const id = useId();
  const budget = read.data;
  const n = monthOf(budget?.month ?? month);
  const launchText = launch ? extraSpendText(extra, launch.extraBasis ?? null) : undefined;
  const fits = budget?.available !== null && budget?.available !== undefined && budget.available - extra >= 0;
  const state = premiseChanged ? "recheck" : budget && budget.amount === null ? "unset"
    : launch && budget && budget.available !== null && !fits ? "short" : "fit";
  const reserved = budget && budget.ongoing_estimate !== null ? budget.ongoing_estimate + budget.reserved_increases : null;
  const line = reserveLine(budget?.ongoing_owners ?? []);
  return (
    <section aria-labelledby={id} className="rounded-xl border border-border bg-card p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id={id} className="text-sm font-medium">本月預算放得下</h2>
        {state === "recheck" && <Chip tone="warn">要重新檢查</Chip>}
        {state === "unset" && <Chip tone="warn">還沒設月預算</Chip>}
        {state === "short" && <Chip tone="bad">放不下</Chip>}
        {state === "fit" && fits && <Chip tone="ok">放得下</Chip>}
      </div>
      {state === "short" && budget && launch && (
        <>
          <p className="mt-3 text-sm">
            <b>{n} 月只剩 {money(budget.available)}</b>
            <span className="text-muted-foreground">（月預算 {money(budget.amount)} − 已花 {money(budget.known_spend)} − <ReserveTerm /> {money(reserved)}），{launchText}</span>
          </p>
          <BudgetBar budget={budget} extra={extra} launch extraText={launchText} />
          {line && <p className="mt-1.5 text-xs text-muted-foreground">{line}</p>}
          <div className="mt-2.5 flex flex-wrap items-center gap-2.5">
            <Button variant="outline" size="sm" asChild><Link to={budgetHref}>提高 {n} 月月預算</Link></Button>
            <Button variant="ghost" size="sm" asChild><Link to={launch.strategyHref}>改這期總預算</Link></Button>
          </div>
        </>
      )}
      {state === "recheck" && (
        <div className="mt-3 flex flex-wrap items-center gap-3.5">
          <p className="text-sm"><b>計畫、素材或月份已改變</b><span className="text-muted-foreground">，這批內容要重新對一次</span></p>
          <Button variant="outline" disabled={busy} onClick={onRecheck}>{busy ? "檢查中…" : "重新檢查"}</Button>
        </div>
      )}
      {state === "unset" && (
        <div className="mt-3 flex flex-wrap items-center gap-3.5">
          <p className="text-sm"><b>{n} 月還沒設月預算</b><span className="text-muted-foreground">，算不出放不放得下</span></p>
          <Button asChild><Link to={budgetHref}>設定 {n} 月月預算 →</Link></Button>
        </div>
      )}
      {state === "fit" && read.status === "error" && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-warning">
          月預算暫時讀取不到，不影響上面的核准內容。
          <Button variant="outline" size="sm" onClick={read.reload}>重試</Button>
        </p>
      )}
      {state === "fit" && read.status !== "error" && !budget && <p className="mt-2 text-sm text-muted-foreground">正在整理月預算…</p>}
      {state === "fit" && budget && (
        <>
          <p className="mt-3 text-sm">
            <b>{n} 月還能花 {money(budget.available)}</b>
            <span className="text-muted-foreground">（月預算 {money(budget.amount)} − 已花 {money(budget.known_spend)} − <ReserveTerm /> {money(reserved)}）</span>
          </p>
          <BudgetBar budget={budget} extra={extra} launch={launch !== undefined} extraText={launchText} />
          {line && <p className="mt-1.5 text-xs text-muted-foreground">{line}</p>}
        </>
      )}
      {budget && budget.uncertainties.length > 0 && (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-muted-foreground">
          {budget.uncertainties.map((reason) => <li key={reason}>{reason}</li>)}
        </ul>
      )}
    </section>
  );
}

/** 加預算提議的證據卡（F25-I03，v7 原型 `confirmPage()` 的 budget 分支）。`scale` 有值（propose
 * 網址進來，或 `:setId` 進來但這個提議的擁有者還在佇列裡）畫完整版：同組則數、購買成本量尺、
 * 後端組好的加碼理由（`scale.reason_text`，F48 Contract R）、本月預算放得下（含這次加碼段）；`scale` 是 `null`（提議的擁有者已經離開
 * 佇列，同 `PauseEvidence` 的 fallback）就退回只有名稱／金額／原因的版本——`item` 這時才派上用場
 * （`scale` 有值時一律讀 `scale`/`triage` 這組即時資料，不讀凍結在 `item.before/after` 的舊值，
 * 這樣第一次進頁面、`item` 都還沒建立時也能完整顯示提議內容）。 */
export function BudgetEvidence({ item, scale, bestAdThumbnailUrl, fit }: {
  item: ChangeItem | undefined; scale: QueueScale | null; bestAdThumbnailUrl: string | null;
  /** F40-I08: the month-budget card's inputs; the read itself lives in `ConfirmPage` (it also gates 核准). */
  fit: Omit<Parameters<typeof BudgetFitCard>[0], "extra">;
}) {
  const before = scale ? scale.from : item?.before.daily_amount ?? null;
  const after = scale ? scale.to : item?.after.daily_amount ?? null;
  const pct = before !== null && after !== null && before > 0 ? Math.round(((after - before) / before) * 100) : null;
  const extra = scale?.month.extra_needed ?? 0;
  const targetValue = scale?.target.value ?? null;
  const cost = scale?.cost_per_result ?? null;
  const meterMax = targetValue !== null && targetValue > 0 ? rulerScale(targetValue, cost === null ? [] : [cost]).max : null;
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
              left={<>{scale.target.result_label}成本 {perSaleAmount(scale.cost_per_result) ?? "累積中"}</>}
              right={<>上限 {formatTargetAmount(targetValue)}</>}
            />
            <div className="flex items-center gap-2">
              <Tile url={bestAdThumbnailUrl} size="sm" />
              <span className="text-sm">{scale.reason_text ?? "—"}</span>
            </div>
            <div className="flex items-center text-sm text-muted-foreground">核准後會排一次檢查</div>
          </div>
        )}
        {!scale && <p className="mt-3 text-sm text-muted-foreground">原因：{item?.reason}</p>}
      </div>
      <BudgetFitCard {...fit} extra={extra} />
    </>
  );
}
