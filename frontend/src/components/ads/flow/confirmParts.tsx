import { useId } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Skeleton } from "@/components/layout/Skeleton";
import { formatCount } from "@/lib/format";
import type { ChangeItem, MonthlyBudget, OngoingOwner } from "@/lib/adsChangeApi";
import type { QueueScale, TriageItem } from "@/lib/adsTriageApi";
import type { AnglesStatus } from "@/lib/adsAnglesApi";
import type { ApiRead } from "@/lib/useApiRead";
import { Chip, KindMark, LearnCard, Meter, ReadFailed, TagToggle, Term } from "../patterns";
import { Tile } from "./Tile";
import { formatAmount, formatTargetAmount } from "./changeFlow";

/** The evidence and learn cards of the confirm step (`ConfirmPage`), split out so the page stays under the
 * 800-line cap (`architectureBoundaries.test.ts`). The cards are page-private except `BudgetFitCard`, which the
 * first-launch list (`publish/PublishList.tsx`, F41-I05) reuses so the month-budget card exists once. */

/** 暫停提議的證據卡：有 triage 就是完整量尺版；triage 已經不在佇列裡（entered by :setId 且
 * 廣告已離開佇列）就退回只有名稱與理由的版本（feature Decisions「Confirm (pause)」）。 */
export function PauseEvidence({ triage, fallbackName, fallbackReason }: {
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
          right={line === null
            ? <><Term k="cap">上限</Term>還沒設定</>
            : <>花到 {formatTargetAmount(line)} 還一筆都沒賣，就算「<Term k="wasted">沒賣出</Term>」（上限 × 3）</>}
        />
      </div>
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
function BudgetBar({ budget, extra = 0, launch = false }: { budget: MonthlyBudget; extra?: number; launch?: boolean }) {
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
        {extra > 0 && <span className="inline-flex items-center gap-1.5"><Swatch tone={extraTone} />{launch ? "這期要花" : "這次要花"} {money(extra)}</span>}
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
 * 「提高 N 月月預算」（`budgetHref`）與「改這期總預算」（`launch.strategyHref`）；沒給時 `ConfirmPage` 照舊。 */
export function BudgetFitCard({ read, month, extra = 0, premiseChanged, busy, onRecheck, budgetHref, launch }: {
  read: ApiRead<MonthlyBudget | null>; month: string; extra?: number;
  premiseChanged: boolean; busy: boolean; onRecheck: () => void; budgetHref: string;
  launch?: { strategyHref: string };
}) {
  const id = useId();
  const budget = read.data;
  const n = monthOf(budget?.month ?? month);
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
            <span className="text-muted-foreground">（月預算 {money(budget.amount)} − 已花 {money(budget.known_spend)} − <ReserveTerm /> {money(reserved)}），這期要花 {money(extra)}</span>
          </p>
          <BudgetBar budget={budget} extra={extra} launch />
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
          <BudgetBar budget={budget} extra={extra} launch={launch !== undefined} />
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
 * 主力廣告穩定 2 期、本月預算放得下（含這次加碼段）；`scale` 是 `null`（提議的擁有者已經離開
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
              right={<>上限 {formatTargetAmount(targetValue)}</>}
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
      <BudgetFitCard {...fit} extra={extra} />
    </>
  );
}
