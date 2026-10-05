import { formatCurrency } from "@/lib/format";
import type { ReactNode } from "react";
import { Button } from "@/components/layout/ui/button";
import { formatCount } from "@/lib/format";
import type { AssumptionField, MoneyInput, SellWayMoney, SellWayNumbers } from "@/lib/intakeProductApi";
import { typedValue } from "@/lib/typedNumber";
import { cn } from "@/lib/utils";

/** The money pieces shared by product onboarding step 4 (`SellWaysStep`) and the bundle page (`BundlePage`): the
 * raw-input draft helpers and F45's `PriceBlock` (prototype `.harness/scratch/prototype/f45-sell-way-components`).
 *
 * Nothing here computes a money value or keeps an input rule (F50 Contract I, decision 11): 打平, a derived 售價 / 原價
 * / 成本 (「推算：單盒 180 × 12」), the default 每筆上限, the assumed cost and the offer sentences all come from the
 * server's view after the last save / preview (null = none yet), and a refused field shows the server's sentence (its
 * `field_errors`) under it. A derived value sits as the input's placeholder with its source line under it, so a
 * left-empty input sends null (= derived) and a derived number is never sent back as the user's value. Every number is
 * sent as typed (`typedValue`; blank = null, never 0). */

/** What the user typed, as typed ("" = empty). `close_rate` is a percent (20 = 20%), the server's scale too. */
export interface MoneyDraft {
  price: string;
  list_price: string;
  cost: string;
  shipping: string;
  close_rate: string;
  cap_per_sale: string;
  /** "" = the default landing page (the product page). */
  landing_url: string;
  /** Fields filled from a reference value (「假設」); editing one clears its flag. */
  assumptions: AssumptionField[];
}

export type MoneyField = "price" | "list_price" | "cost" | "shipping" | "close_rate" | "cap_per_sale";

/** The server's refusals of one row, keyed by field as the PUT names them without the row prefix (`price`,
 * `close_rate`, `landing_url`, `components`, `components.0.qty`, …). */
export type RowErrors = Partial<Record<string, string>>;

/** Server numbers as input text (399 → "399"; a 20 % close rate → "20": the same scale both ways). */
export const inputText = (value: number | null | undefined): string => (value == null ? "" : String(value));

/** A saved row's inputs: only the values the user typed; a derived 售價 / 原價 / 成本 and a default 每筆上限 / 落地頁
 * stay empty (an empty input sends null = derived, so a derived number is never saved back as typed). */
export function draftFromMoney(money: SellWayMoney | SellWayNumbers): MoneyDraft {
  return {
    price: "price_derived" in money && money.price_derived ? "" : inputText(money.price),
    list_price: money.list_price_derived ? "" : inputText(money.list_price),
    cost: money.cost_derived ? "" : inputText(money.cost),
    shipping: inputText(money.shipping),
    close_rate: inputText(money.close_rate),
    cap_per_sale: money.cap_is_default ? "" : inputText(money.cap_per_sale),
    landing_url: money.landing_is_default ? "" : money.landing_url,
    assumptions: [...money.assumptions],
  };
}

export const emptyDraft = (): MoneyDraft => ({
  price: "", list_price: "", cost: "", shipping: "", close_rate: "", cap_per_sale: "", landing_url: "", assumptions: [],
});

/** The PUT body's money part, as typed: an empty field is null (= derived / break-even / product page; a base's empty
 * price is the server's to refuse). 成交率 goes as the typed percent. */
export function stepMoneyInput(draft: MoneyDraft, showCloseRate: boolean): MoneyInput {
  const input: MoneyInput = {
    price: typedValue(draft.price),
    list_price: typedValue(draft.list_price),
    cost: typedValue(draft.cost),
    shipping: typedValue(draft.shipping),
    cap_per_sale: typedValue(draft.cap_per_sale),
    landing_url: draft.landing_url.trim() || null,
    assumptions: draft.assumptions,
  };
  if (showCloseRate) input.close_rate = typedValue(draft.close_rate);
  return input;
}

/** After a save: a cost the server assumed (「空著的成本填參考值」, flagged `cost` with an empty input) becomes the
 * input's value; a flag the server dropped (nothing to assume from) goes. Any other draft is kept as typed. */
export function adoptAssumedCost(draft: MoneyDraft, money: SellWayMoney | SellWayNumbers): MoneyDraft {
  if (draft.cost !== "" || !draft.assumptions.includes("cost")) return draft;
  if (money.assumptions.includes("cost") && money.cost != null && !money.cost_derived) {
    return { ...draft, cost: inputText(money.cost) };
  }
  return { ...draft, assumptions: draft.assumptions.filter((a) => a !== "cost") };
}

const amount = (value: number) => formatCount(Math.round(value));

// ---- F45 price block (prototype `priceBlock()` + `result()` of `.harness/scratch/prototype/f45-sell-way-components`) ----

const TONE = {
  accent: "bg-secondary text-secondary-foreground",
  warn: "bg-zone-watch text-warning",
  ok: "bg-zone-ok text-success",
  neutral: "bg-muted text-muted-foreground",
} as const;

/** Prototype `.chip` (`.v` accent = 推算 / 組合賣法, `.warn`, `.ok`; `.sent` = an offer sentence that may wrap). */
export function SwChip({ tone, sentence, className, children }: { tone: keyof typeof TONE; sentence?: boolean; className?: string; children: ReactNode }) {
  return (
    <span
      data-slot="chip"
      data-tone={tone}
      className={cn(
        "inline-flex w-fit shrink-0 items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        sentence ? "rounded-lg py-[3px] leading-[1.45] [overflow-wrap:anywhere]" : "whitespace-nowrap",
        TONE[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** 「推算」: a number the server derived from the bases (F45: labelled everywhere it shows). */
export const EstChip = ({ className }: { className?: string }) => <SwChip tone="accent" className={cn("px-[7px] py-0 text-[11px]", className)}>推算</SwChip>;

/** A server amount as the prototype prints it (`fmt`). */
export const swAmount = (value: number) => amount(value);

/** The editor's 售價／原價／成本／運費成本 (+ 成交率 in %), 「這個賣法免運」, 打平 with the offers, and the folded 每筆上限 /
 * 落地頁. Every number shown here is the server's (`numbers`, the last save; null = not saved yet): a derived value is
 * the placeholder of its empty input with its 「推算：…」 line; nothing is computed on the page. `errors` are the
 * server's refusals of this row (shown under each field; the parent decides when to pass them). */
export function PriceBlock({ idPrefix, shape, draft, numbers, free, showCloseRate, errors, pending, landingPlaceholder, onDraft, onFree, onFillCost, fillCostWhere }: {
  idPrefix: string;
  shape: "base" | "composed";
  draft: MoneyDraft;
  numbers: SellWayNumbers | null;
  free: boolean;
  showCloseRate: boolean;
  errors: RowErrors;
  /** Why 打平 cannot be computed yet, from the form itself (「先填數量」); null = ask the server's numbers. */
  pending: string | null;
  /** The folded 落地頁 field's placeholder (the product page); omit = no landing field in the fold. */
  landingPlaceholder?: string;
  onDraft: (patch: Partial<MoneyDraft>) => void;
  onFree: (on: boolean) => void;
  /** 「去填〈base〉的成本 →」 under an underivable cost. */
  onFillCost?: (part: { sell_way_id: string; name: string }) => void;
  /** Without a jump (the base belongs to another product, bundle page): where to fill it, 「到「〈商品〉」的賣法填」. */
  fillCostWhere?: (part: { sell_way_id: string; name: string }) => string;
}) {
  const n = numbers;
  const missing = draft.cost === "" && shape === "composed" ? n?.cost_missing ?? [] : [];
  const edit = (field: MoneyField, value: string) => {
    const flag = field === "cost" || field === "shipping" || field === "close_rate" ? field : null;
    onDraft({ [field]: value, ...(flag && draft.assumptions.includes(flag) ? { assumptions: draft.assumptions.filter((a) => a !== flag) } : {}) });
  };
  const field = (f: MoneyField, head: string) => {
    let placeholder = "";
    let note: ReactNode = null;
    let warn = false;
    const empty = draft[f] === "";
    if (f === "price" && empty && n?.price_derived && n.price !== null) {
      placeholder = amount(n.price);
      note = <Note tone="est">{n.price_note}</Note>;
    } else if (f === "list_price" && empty && n?.list_price_derived && n.list_price !== null) {
      placeholder = amount(n.list_price);
      note = <Note tone="est">{n.list_price_note}</Note>;
    } else if (f === "list_price" && empty && shape === "base") {
      placeholder = "選填";
    } else if (f === "cost" && empty && n?.cost_derived && n.cost !== null) {
      placeholder = amount(n.cost);
      note = <Note tone="est">{n.cost_note}</Note>;
    } else if (f === "cost" && missing.length > 0) {
      placeholder = "—";
      warn = true;
      note = <Note tone="warn">{missing.map((m) => m.name).join("、")}還沒填成本，推算不出來</Note>;
    } else if (f === "cost" && !empty && n?.cost_estimate != null && n.cost != null && !n.cost_derived && n.cost_estimate !== n.cost) {
      note = <Note>照內容推算是 {amount(n.cost_estimate)}</Note>;
    } else if (f === "cost" && empty && shape === "base") {
      placeholder = "還沒填";
      warn = true;
    } else if (f === "shipping" && empty) {
      placeholder = "0";
    }
    const assumed = (f === "cost" || f === "shipping" || f === "close_rate") && draft.assumptions.includes(f);
    const error = errors[f];
    const id = `${idPrefix}-${f}`;
    return (
      <div key={f} className="min-w-0">
        <label htmlFor={id} className="mb-1 block text-xs text-muted-foreground">{head}</label>
        <MoneyBox id={id} value={draft[f]} placeholder={placeholder} tone={error ? "error" : warn ? "warn" : null} suffix={f === "close_rate" ? "%" : undefined}
          currency={f !== "close_rate"} onChange={(v) => edit(f, v)} />
        {error ? <Note tone="error">{error}</Note> : note}
        {assumed && <SwChip tone="warn" className="mt-1">假設</SwChip>}
      </div>
    );
  };
  /** The saved cap of this row (the server's number; the typed text until the next save). */
  const ownCap = n && !n.cap_is_default ? n.cap_per_sale : null;
  const capTyped = draft.cap_per_sale.trim();
  const capOver = capTyped !== "" && ownCap != null && n?.break_even != null && ownCap > n.break_even;
  const capDefault = n?.break_even != null ? amount(Math.max(n.break_even, 0)) : null;
  const capSum = capTyped !== ""
    ? `每筆上限 ${ownCap != null ? amount(ownCap) : capTyped}`
    : capDefault !== null ? `每筆上限＝打平 ${capDefault}` : "每筆上限＝打平";
  const landSum = landingPlaceholder !== undefined ? `・落地頁：${draft.landing_url.trim() ? "自訂" : "商品頁"}` : "";
  return (
    <div data-slot="price-block">
      <div className={cn("grid gap-x-3.5 gap-y-3 max-[760px]:grid-cols-2", showCloseRate ? "grid-cols-5" : "grid-cols-4")}>
        {field("price", "售價")}
        {field("list_price", "原價")}
        {field("cost", "成本")}
        {field("shipping", "運費成本")}
        {showCloseRate && field("close_rate", "成交率")}
      </div>
      <label className="mt-3.5 inline-flex cursor-pointer items-center gap-2 text-[13.5px]">
        <input type="checkbox" className="size-4 accent-primary" checked={free} onChange={(e) => onFree(e.target.checked)} />
        這個賣法免運
      </label>
      <Result numbers={n} shape={shape} pending={pending} missing={missing} showCloseRate={showCloseRate} onFillCost={onFillCost} fillCostWhere={fillCostWhere} />
      <details className="group mt-3 rounded-[10px] border border-border bg-card" open={errors.cap_per_sale || errors.landing_url ? true : undefined}>
        <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-4 py-[11px] font-medium text-muted-foreground [&::-webkit-details-marker]:hidden">
          <span aria-hidden="true" className="inline-block text-base leading-none transition-transform group-open:rotate-90">›</span>
          進階：每筆上限{landingPlaceholder !== undefined ? "、落地頁" : ""}
          <span className="ml-auto text-xs font-normal">{capSum}{landSum}</span>
        </summary>
        <div className="grid grid-cols-2 gap-4 px-4 pb-4 max-[760px]:grid-cols-1">
          <div>
            <label htmlFor={`${idPrefix}-cap_per_sale`} className="mb-1 block text-xs text-muted-foreground">每筆上限（空著＝打平）</label>
            <MoneyBox id={`${idPrefix}-cap_per_sale`} value={draft.cap_per_sale} placeholder={capDefault ?? ""} className="max-w-[220px]"
              tone={errors.cap_per_sale ? "error" : capOver ? "warn" : null} onChange={(v) => edit("cap_per_sale", v)} />
            {errors.cap_per_sale ? <Note tone="error">{errors.cap_per_sale}</Note> : capOver && <Note tone="warn">高於打平</Note>}
          </div>
          {landingPlaceholder !== undefined && (
            <div>
              <label htmlFor={`${idPrefix}-landing`} className="mb-1 block text-xs text-muted-foreground">落地頁（空著＝商品頁）</label>
              <input id={`${idPrefix}-landing`} type="url" className={cn(INPUT_LG, errors.landing_url && "border-danger")} value={draft.landing_url}
                placeholder={landingPlaceholder} aria-invalid={errors.landing_url ? true : undefined}
                onChange={(e) => onDraft({ landing_url: e.target.value })} />
              {errors.landing_url && <Note tone="error">{errors.landing_url}</Note>}
            </div>
          )}
        </div>
      </details>
    </div>
  );
}

const INPUT_LG =
  "w-full rounded-lg border border-input bg-card px-3 py-[9px] text-sm focus:border-primary focus:shadow-[0_0_0_3px_var(--color-accent)] focus:outline-none focus-visible:outline-none";

/** Prototype `.money`: NT$ inside the box, a large tabular number; a derived placeholder reads in the accent colour. */
function MoneyBox({ id, value, placeholder, tone, currency = true, suffix, className, onChange }: {
  id: string;
  value: string;
  placeholder: string;
  tone: "warn" | "error" | null;
  currency?: boolean;
  suffix?: string;
  className?: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className={cn(
      "flex w-full items-center rounded-lg border bg-card px-2.5 focus-within:border-primary focus-within:shadow-[0_0_0_3px_var(--color-accent)]",
      tone === "error" ? "border-danger" : tone === "warn" ? "border-warning/60 bg-zone-watch/30" : "border-input",
      className,
    )}>
      {currency && <span aria-hidden="true" className="text-[12.5px] text-muted-foreground">NT$</span>}
      <input id={id} inputMode="decimal" autoComplete="off" aria-invalid={tone === "error" ? true : undefined} value={value} placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="w-full min-w-0 border-0 bg-transparent px-1.5 py-2 text-[15px] font-semibold tabular-nums outline-none placeholder:font-semibold placeholder:text-primary/65 focus-visible:outline-none" />
      {suffix && <span aria-hidden="true" className="text-xs text-muted-foreground">{suffix}</span>}
    </div>
  );
}

function Note({ tone, children }: { tone?: "est" | "warn" | "error"; children: ReactNode }) {
  return (
    <div role={tone === "error" ? "alert" : undefined} className={cn(
      "mt-1 text-[11.5px] leading-[1.45] [overflow-wrap:anywhere]",
      tone === "est" ? "text-accent-foreground" : tone === "warn" ? "font-medium text-warning" : tone === "error" ? "text-danger" : "text-muted-foreground",
    )}>
      {children}
    </div>
  );
}

/** Prototype `result()`: 打平 (the server's break-even, 推算 when it uses a derived number; 「賣一筆就虧」 at or below 0;
 * 「還算不出來：…」 with the reason and, for a base without a cost, the jump to it) and 「廣告裡的優惠」 (the sell-way's own
 * offer sentences). */
function Result({ numbers: n, shape, pending, missing, showCloseRate, onFillCost, fillCostWhere }: {
  numbers: SellWayNumbers | null;
  shape: "base" | "composed";
  pending: string | null;
  missing: { sell_way_id: string; name: string }[];
  showCloseRate: boolean;
  onFillCost?: (part: { sell_way_id: string; name: string }) => void;
  fillCostWhere?: (part: { sell_way_id: string; name: string }) => string;
}) {
  let be: ReactNode;
  if (pending) {
    be = <Unknown>還算不出來：{pending}</Unknown>;
  } else if (n?.break_even != null) {
    const priceEst = n.price_derived ? "（推算）" : "";
    const costEst = n.cost_derived ? "（推算）" : "";
    const rate = showCloseRate && n.close_rate != null ? ` × 成交率 ${n.close_rate}%` : "";
    be = (
      <>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <b className="text-base font-[650] tabular-nums">每筆最多花 {formatCurrency(Math.max(n.break_even, 0))}</b>
          {n.break_even_derived && <EstChip />}
        </div>
        <div className="text-[11.5px] text-muted-foreground">
          {rate && "（"}售價 {n.price === null ? "不明" : amount(n.price)}{priceEst} − 成本 {n.cost === null ? "不明" : amount(n.cost)}{costEst} − 運費成本 {n.shipping === null ? "不明" : amount(n.shipping)}{rate && `）${rate}`}
        </div>
        {n.break_even <= 0 && (
          <div className="text-[11.5px] font-medium text-warning">
            {showCloseRate ? "這個價錢賣一筆就虧" : `這個價錢賣一筆就虧 ${formatCurrency(-n.break_even)}`}，廣告花多少都不划算
          </div>
        )}
      </>
    );
  } else if (missing.length > 0) {
    const first = missing[0];
    be = (
      <>
        <Unknown>還算不出來：{missing.map((m) => m.name).join("、")}還沒填成本</Unknown>
        {onFillCost ? (
          <div className="text-[11.5px]">
            <Button type="button" variant="link" className="h-auto p-0 text-[13px]" onClick={() => onFillCost(first)}>去填{first.name}的成本 →</Button>
          </div>
        ) : fillCostWhere && <div className="text-[11.5px] text-muted-foreground">{fillCostWhere(first)}</div>}
      </>
    );
  } else if (!n) {
    be = <Unknown>還算不出來：存了才算</Unknown>;
  } else if (n.price === null) {
    be = <Unknown>還算不出來：先填售價{shape === "base" ? "" : "或放進賣法"}</Unknown>;
  } else {
    be = <Unknown>還算不出來：還沒填成本</Unknown>;
  }
  const offers = n?.offer_sentences ?? [];
  return (
    <div data-slot="sell-way-result" className="mt-3 rounded-[10px] border border-secondary bg-accent/45 px-3.5 py-1">
      <div className="grid grid-cols-[96px_minmax(0,1fr)] items-start gap-x-3 gap-y-1 py-2.5 max-[760px]:grid-cols-1">
        <span className="pt-0.5 text-[12.5px] text-muted-foreground">打平</span>
        <div data-break-even className="flex flex-col gap-1">{be}</div>
      </div>
      <div className="grid grid-cols-[96px_minmax(0,1fr)] items-start gap-x-3 gap-y-1 border-t border-secondary py-2.5 max-[760px]:grid-cols-1">
        <span className="pt-0.5 text-[12.5px] text-muted-foreground">廣告裡的優惠</span>
        <div data-slot="offer-sentences" className="flex flex-wrap gap-1.5">
          {offers.length > 0
            ? offers.map((o) => <SwChip key={o} tone="ok" sentence>「{o}」</SwChip>)
            : <span className="text-[12.5px] whitespace-nowrap text-muted-foreground">沒有優惠</span>}
        </div>
      </div>
    </div>
  );
}

function Unknown({ children }: { children: ReactNode }) {
  return <b className="font-semibold text-muted-foreground/80">{children}</b>;
}
