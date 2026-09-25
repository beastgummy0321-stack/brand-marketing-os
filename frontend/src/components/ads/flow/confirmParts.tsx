import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import { Skeleton } from "@/components/layout/Skeleton";
import { formatCount } from "@/lib/format";
import { getMonthlyBudget, type ChangeItem, type MonthlyBudget } from "@/lib/adsChangeApi";
import type { QueueScale, TriageItem } from "@/lib/adsTriageApi";
import type { AnglesStatus } from "@/lib/adsAnglesApi";
import { useApiRead } from "@/lib/useApiRead";
import { budgetMoney, currentBudgetMonth } from "../MonthlyBudgetPanel";
import { Chip, KindMark, LearnCard, Meter, ReadFailed, TagToggle, Term } from "../patterns";
import { Tile } from "./Tile";
import { formatAmount, formatTargetAmount } from "./changeFlow";

/** The evidence and learn cards of the confirm step (`ConfirmPage`), split out so the page stays under the
 * 800-line cap (`architectureBoundaries.test.ts`). Each card is page-private; nothing else imports them. */

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
export function BudgetEvidence({ item, scale, bestAdThumbnailUrl, brandId }: {
  item: ChangeItem | undefined; scale: QueueScale | null; bestAdThumbnailUrl: string | null; brandId: string;
}) {
  const budgetRead = useApiRead((signal) => getMonthlyBudget(brandId, currentBudgetMonth(), signal), [brandId]);
  const budget = budgetRead.data;
  const budgetError = budgetRead.status === "error";
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
      <div className="rounded-xl border border-border bg-card p-5">
        <h2 className="text-sm font-medium">本月預算放得下</h2>
        {budgetError && (
          <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-warning">
            月預算暫時讀取不到，不影響上面的核准內容。
            <Button variant="outline" size="sm" onClick={budgetRead.reload}>重試</Button>
          </p>
        )}
        {!budgetError && !budget && <p className="mt-2 text-sm text-muted-foreground">正在整理月預算…</p>}
        {budget && <MiniBudgetBar budget={budget} extra={extra} />}
      </div>
    </>
  );
}
