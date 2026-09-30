import { Fragment, useState, type FocusEvent, type ReactNode } from "react";
import { Button } from "@/components/layout/ui/button";
import { formatCount } from "@/lib/format";
import type { AssumptionField, MoneyInput, SellWayMoney } from "@/lib/intakeProductApi";
import { cn } from "@/lib/utils";
import { Chip, RemoveButton } from "../steps/PolicyCard";

/** Prototype `table.sw` of `.harness/scratch/prototype/f41-onboarding/index.html` (`#/p4` 怎麼賣、賣多少 and the
 * `#/bundle` price table): one row per sell-way with its raw money inputs and the numbers the server derived from
 * them. Shared by product onboarding step 4 (`SellWaysStep`) and the bundle page.
 *
 * The table never computes a money value: 打平線, a derived 原價 / 成本 (「3 件單價相加」), the default 每筆上限 and the
 * offer chips all come from `money` (the server's view after the last save; null = not saved yet). A derived value
 * sits as the input's placeholder with its source line under it, so a left-empty input sends null (= derived) and a
 * derived number is never sent back as the user's value. */

/** What the user typed, as typed ("" = empty). `close_rate` is a percentage (20 = 20%). */
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

export interface SellWayTableRow {
  key: string;
  draft: MoneyDraft;
  /** The server's numbers after the last save; null = never saved (nothing derived yet). */
  money: SellWayMoney | null;
  /** The 賣法 column's name input (omit on a page without the 賣法／內容 columns). */
  name?: string;
  /** The 內容 cell. */
  content?: ReactNode;
  /** Show this row's reasons (after its first blur or a submit attempt). */
  showErrors?: boolean;
  /** × for a row that is not saved yet. */
  onRemove?: () => void;
}

const num = (raw: string): number | null => {
  const t = raw.trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
};

/** Server numbers as input text (399 → "399"; 0.2 close rate → "20"). */
export const inputText = (value: number | null | undefined): string => (value == null ? "" : String(value));
export const percentText = (rate: number | null | undefined): string =>
  rate == null ? "" : String(Number((rate * 100).toFixed(2)));

/** A saved row's inputs: only the values the user typed; a derived 原價 / 成本 and a default 每筆上限 / 落地頁 stay empty. */
export function draftFromMoney(money: SellWayMoney): MoneyDraft {
  return {
    price: inputText(money.price),
    list_price: money.list_price_derived ? "" : inputText(money.list_price),
    cost: money.cost_derived ? "" : inputText(money.cost),
    shipping: inputText(money.shipping),
    close_rate: percentText(money.close_rate),
    cap_per_sale: money.cap_is_default ? "" : inputText(money.cap_per_sale),
    landing_url: money.landing_is_default ? "" : money.landing_url,
    assumptions: [...money.assumptions],
  };
}

export const emptyDraft = (): MoneyDraft => ({
  price: "", list_price: "", cost: "", shipping: "", close_rate: "", cap_per_sale: "", landing_url: "", assumptions: [],
});

/** Why a row cannot be saved, per field (the server refuses the same: price > 0, no negatives, 成交率 in (0, 100%]). */
export function moneyErrors(draft: MoneyDraft, showCloseRate: boolean): Partial<Record<MoneyField, string>> {
  const out: Partial<Record<MoneyField, string>> = {};
  const price = num(draft.price);
  if (price === null || Number.isNaN(price) || price <= 0) out.price = "售價要大於 0";
  for (const field of ["list_price", "cost", "shipping", "cap_per_sale"] as const) {
    const n = num(draft[field]);
    if (Number.isNaN(n)) out[field] = "請填數字";
    else if (n !== null && n < 0) out[field] = "不能是負數";
  }
  if (showCloseRate) {
    const rate = num(draft.close_rate);
    if (Number.isNaN(rate) || (rate !== null && (rate <= 0 || rate > 100))) out.close_rate = "要在 0～100% 之間";
  }
  return out;
}

/** The PUT body's money part: raw inputs only; an empty field is null (= derived / break-even / product page). */
export function moneyInput(draft: MoneyDraft, showCloseRate: boolean): MoneyInput {
  const rate = num(draft.close_rate);
  const input: MoneyInput = {
    price: num(draft.price) ?? 0,
    list_price: num(draft.list_price),
    cost: num(draft.cost),
    shipping: num(draft.shipping),
    cap_per_sale: num(draft.cap_per_sale),
    landing_url: draft.landing_url.trim() || null,
    assumptions: draft.assumptions,
  };
  if (showCloseRate) input.close_rate = rate === null ? null : Number((rate / 100).toFixed(4));
  return input;
}

const amount = (value: number) => formatCount(Math.round(value));

const CELL = "border-t border-border px-2 py-1.5 align-top";
const INPUT =
  "w-full rounded-md border border-input bg-card px-2 py-1.5 text-[13px] tabular-nums placeholder:text-muted-foreground focus:border-primary focus:shadow-[0_0_0_3px_var(--color-accent)] focus:outline-none";

export function SellWayTable({ rows, showCloseRate, onDraft, onName, onRowBlur, nameColumns = true, footer = true }: {
  rows: SellWayTableRow[];
  showCloseRate: boolean;
  onDraft: (key: string, patch: Partial<MoneyDraft>) => void;
  onName?: (key: string, name: string) => void;
  /** Focus left a row (the step saves then); moving between the row's own inputs does not count. */
  onRowBlur?: (key: string) => void;
  /** 賣法 + 內容 columns (the bundle page has one unnamed row). */
  nameColumns?: boolean;
  /** The offers + 落地頁 line under each row. */
  footer?: boolean;
}) {
  const cols = (nameColumns ? 2 : 0) + 6 + (showCloseRate ? 1 : 0);
  const heads = [
    ...(nameColumns ? ["賣法", "內容"] : []),
    "售價", "原價", "成本", "運費成本",
    ...(showCloseRate ? ["成交率"] : []),
    "打平線", "每筆上限",
  ];
  return (
    <div className="-mx-1 overflow-x-auto px-1 pb-1">
      <table data-slot="sell-way-table" className="w-full border-collapse text-[13px]">
        <thead>
          <tr>
            {heads.map((h) => (
              <th key={h} scope="col" className="bg-transparent px-2 pt-0 pb-1.5 text-left text-[11.5px] font-medium whitespace-nowrap text-muted-foreground">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <SellWayRows
              key={row.key}
              row={row}
              cols={cols}
              showCloseRate={showCloseRate}
              nameColumns={nameColumns}
              footer={footer}
              onDraft={(patch) => onDraft(row.key, patch)}
              onName={onName && ((name) => onName(row.key, name))}
              onBlur={onRowBlur && (() => onRowBlur(row.key))}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SellWayRows({ row, cols, showCloseRate, nameColumns, footer, onDraft, onName, onBlur }: {
  row: SellWayTableRow;
  cols: number;
  showCloseRate: boolean;
  nameColumns: boolean;
  footer: boolean;
  onDraft: (patch: Partial<MoneyDraft>) => void;
  onName?: (name: string) => void;
  onBlur?: () => void;
}) {
  const { draft, money } = row;
  const errors = row.showErrors ? moneyErrors(draft, showCloseRate) : {};
  const label = row.name?.trim() || "新的賣法";
  /** Typing into a field drops its 「假設」 flag (F05 rule 3). */
  const edit = (field: MoneyField, value: string) => {
    const flag = field === "cost" ? "cost" : field === "shipping" ? "shipping" : field === "close_rate" ? "close_rate" : null;
    onDraft({ [field]: value, ...(flag && draft.assumptions.includes(flag) ? { assumptions: draft.assumptions.filter((a) => a !== flag) } : {}) });
  };
  const cap = num(draft.cap_per_sale);
  const capOver = cap !== null && !Number.isNaN(cap) && money?.break_even != null && cap > money.break_even;
  const field = (f: MoneyField, head: string, extra: { placeholder?: string; note?: string; warn?: string; suffix?: string } = {}) => {
    const error = errors[f];
    const assumed = (f === "cost" || f === "shipping" || f === "close_rate") && draft.assumptions.includes(f);
    return (
      <td className={cn(CELL, "w-[80px]")}>
        <div className="flex items-center gap-1">
          <input
            aria-label={`${label}的${head}`}
            aria-invalid={error ? true : undefined}
            inputMode="decimal"
            className={cn(INPUT, error && "border-danger", !error && extra.warn && "border-warning bg-zone-watch/40")}
            value={draft[f]}
            placeholder={extra.placeholder}
            onChange={(e) => edit(f, e.target.value)}
          />
          {extra.suffix && <span className="text-xs text-muted-foreground">{extra.suffix}</span>}
        </div>
        {error && <div role="alert" className="mt-0.5 text-[11.5px] text-danger">{error}</div>}
        {!error && extra.warn && <div className="mt-0.5 text-[11.5px] text-warning">{extra.warn}</div>}
        {!error && extra.note && <div className="mt-0.5 text-[11.5px] text-muted-foreground">{extra.note}</div>}
        {assumed && <WarnChip className="mt-1">假設</WarnChip>}
      </td>
    );
  };
  // A derived value is the placeholder of its empty input, with its source line under it.
  const listDerived = draft.list_price === "" && money?.list_price_derived && money.list_price !== null;
  const costDerived = draft.cost === "" && money?.cost_derived && money.cost !== null;
  const capDefault = draft.cap_per_sale === "" && money?.break_even != null;
  /** Focus left the row (its two lines), not just moved to another of its inputs. */
  const leave = (e: FocusEvent) => {
    const next = e.relatedTarget as HTMLElement | null;
    if (next?.closest(`[data-row="${CSS.escape(row.key)}"]`)) return;
    onBlur?.();
  };
  return (
    <>
      <tr data-row={row.key} onBlur={leave}>
        {nameColumns && (
          <>
            <td className={cn(CELL, "w-[106px]")}>
              <input
                aria-label="賣法名稱"
                className={cn(INPUT, "w-[92px]")}
                value={row.name ?? ""}
                placeholder="例如：六盒組"
                onChange={(e) => onName?.(e.target.value)}
              />
              {row.showErrors && !row.name?.trim() && <div role="alert" className="mt-0.5 text-[11.5px] text-danger">請填賣法名稱</div>}
            </td>
            <td className={cn(CELL, "min-w-[120px] text-muted-foreground")}>
              <div className="flex min-h-[31px] items-center gap-1">
                <div className="min-w-0 flex-1">{row.content}</div>
                {row.onRemove && <RemoveButton label={label} onClick={row.onRemove} />}
              </div>
            </td>
          </>
        )}
        {field("price", "售價")}
        {field("list_price", "原價", listDerived ? { placeholder: amount(money!.list_price!), note: money!.list_price_note } : {})}
        {field("cost", "成本", costDerived ? { placeholder: amount(money!.cost!), note: money!.cost_note } : {})}
        {field("shipping", "運費成本")}
        {showCloseRate && field("close_rate", "成交率", { suffix: "%" })}
        <td className={cn(CELL, "pt-3 whitespace-nowrap text-muted-foreground tabular-nums")} data-break-even>
          {money === null ? <span aria-label="還沒算">—</span> : money.break_even === null ? "未知" : amount(money.break_even)}
        </td>
        {field("cap_per_sale", "每筆上限", {
          placeholder: capDefault ? amount(money!.break_even!) : undefined,
          warn: capOver ? "高於打平線" : undefined,
        })}
      </tr>
      {footer && (
        <tr data-row={row.key} onBlur={leave}>
          {nameColumns && <td className="border-t border-border p-0" />}
          <td colSpan={cols - (nameColumns ? 1 : 0)} className="px-2 pt-0 pb-2">
            <RowFooter money={money} draft={draft} label={label} onLanding={(landing_url) => onDraft({ landing_url })} />
          </td>
        </tr>
      )}
    </>
  );
}

/** Under each row: the offers the server derived (「組合價 省 198」「滿 999 免運」) or 「沒有優惠」, then 「落地頁：商品頁」 +
 * 「換落地頁」 (an inline URL input; empty = back to the product page). */
function RowFooter({ money, draft, label, onLanding }: {
  money: SellWayMoney | null;
  draft: MoneyDraft;
  label: string;
  onLanding: (url: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const offers = money?.offer_labels ?? [];
  const own = draft.landing_url.trim();
  const noPage = !own && money !== null && money.landing_is_default && !money.landing_url;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {offers.length > 0
        ? offers.map((o) => <Fragment key={o}><Chip tone="ok">{o}</Chip></Fragment>)
        : <span className="text-xs text-muted-foreground">{money === null ? "" : "沒有優惠"}</span>}
      {editing ? (
        <input
          aria-label={`${label}的落地頁`}
          type="url"
          autoFocus
          className={cn(INPUT, "w-[320px] max-w-full")}
          placeholder="https://…（空著＝商品頁）"
          value={draft.landing_url}
          onChange={(e) => onLanding(e.target.value)}
          onBlur={() => setEditing(false)}
        />
      ) : (
        <>
          <span className="text-xs text-muted-foreground [overflow-wrap:anywhere]">
            落地頁：{own || (noPage ? "還沒設" : "商品頁")}
          </span>
          <Button type="button" variant="link" className="h-auto p-0 text-xs" aria-label={`換「${label}」的落地頁`} onClick={() => setEditing(true)}>
            換落地頁
          </Button>
        </>
      )}
    </div>
  );
}

/** Prototype `.chip.warn` (a value filled from a reference value). */
function WarnChip({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <span data-slot="chip" data-tone="warn" className={cn("inline-flex items-center rounded-full bg-zone-watch px-2 py-0.5 text-[11px] font-medium whitespace-nowrap text-warning", className)}>
      {children}
    </span>
  );
}
