import type { ReactNode } from "react";
import { Button } from "@/components/layout/ui/button";
import { cn } from "@/lib/utils";
import { swAmount } from "./SellWayTable";

/** 「裡面有什麼」 of a composed sell-way (prototype `contents()` + `picker()` of
 * `.harness/scratch/prototype/f45-sell-way-components/app.js`): rows 〈base sell-way〉 × qty, each with that base's own
 * 售價・成本 (the server's numbers of the base), the quantity box, ×, and the picker of this product's bases not in yet
 * (「＋新增基本賣法」 once all are in). Items reference a base by its row key, so renaming a base renames it here. */

export interface ContentItem {
  /** The base row's key on the step. */
  base: string;
  /** As typed. */
  qty: string;
}

export interface BaseOption {
  key: string;
  name: string;
  /** That base's own effective numbers (null = not known yet). */
  price: number | null;
  cost: number | null;
}

export const qtyOf = (raw: string): number | null => (/^\d+$/.test(raw.trim()) && Number(raw) > 0 ? Number(raw) : null);

/** Why the contents cannot be saved (the server refuses the same): none in, a bad quantity, or Σqty 1 (= the base). */
export function contentsError(items: ContentItem[], nameOf: (key: string) => string): string | null {
  if (items.length === 0) return "至少放一種賣法";
  if (items.some((it) => qtyOf(it.qty) === null)) return "數量要是正整數";
  if (items.length === 1 && qtyOf(items[0].qty) === 1) return `只放 1 份就跟「${nameOf(items[0].base)}」一樣；數量至少 2`;
  return null;
}

export function SellWayContents({ idPrefix, items, bases, picking, showErrors, onQty, onRemove, onAdd, onPicking, onNewBase }: {
  idPrefix: string;
  items: ContentItem[];
  /** This product's bases. */
  bases: BaseOption[];
  picking: boolean;
  showErrors: boolean;
  onQty: (index: number, qty: string) => void;
  onRemove: (index: number) => void;
  onAdd: (baseKey: string) => void;
  onPicking: (open: boolean) => void;
  onNewBase: () => void;
}) {
  const byKey = new Map(bases.map((b) => [b.key, b]));
  const nameOf = (key: string) => byKey.get(key)?.name.trim() || "新的基本賣法";
  const one = items.length === 1 && qtyOf(items[0].qty) === 1;
  const remaining = bases.filter((b) => !items.some((it) => it.base === b.key));
  return (
    <div data-slot="sell-way-contents">
      <ul aria-label="裡面有什麼" className="flex flex-col gap-2">
        {items.map((it, i) => {
          const base = byKey.get(it.base);
          const name = nameOf(it.base);
          const bad = qtyOf(it.qty) === null && (showErrors || it.qty.trim() !== "");
          return (
            <li key={it.base}>
              <div className="flex items-center gap-2.5 rounded-[10px] border border-border bg-card px-3 py-2 max-[480px]:flex-wrap">
                <Tile size={32} />
                <div className="min-w-0 flex-1 max-[480px]:basis-[calc(100%-90px)]">
                  <b className="block font-semibold [overflow-wrap:anywhere]">{name}</b>
                  <div className="text-[11.5px] text-muted-foreground">
                    售價 {base?.price != null ? swAmount(base.price) : "還沒填"}・成本{" "}
                    {base?.cost != null ? swAmount(base.cost) : <span className="font-medium text-warning">還沒填</span>}
                  </div>
                </div>
                <span className={cn(
                  "inline-flex w-[92px] shrink-0 items-center rounded-lg border bg-card px-2.5 focus-within:border-primary focus-within:shadow-[0_0_0_3px_var(--color-accent)] max-[480px]:ml-[42px]",
                  bad ? "border-danger" : "border-input",
                )}>
                  <span aria-hidden="true" className="text-muted-foreground">×</span>
                  <input id={`${idPrefix}-q${i}`} inputMode="numeric" autoComplete="off" aria-label={`${name}的數量`} aria-invalid={bad ? true : undefined}
                    value={it.qty} placeholder="數量" onChange={(e) => onQty(i, e.target.value)}
                    className="w-full min-w-0 border-0 bg-transparent px-1.5 py-2 text-[15px] font-semibold tabular-nums outline-none focus-visible:outline-none" />
                </span>
                <button type="button" aria-label={`拿掉${name}`} onClick={() => onRemove(i)}
                  className="rounded-md p-1.5 text-lg leading-none text-muted-foreground hover:bg-muted hover:text-danger">×</button>
              </div>
              {bad && <Err>數量要是正整數</Err>}
            </li>
          );
        })}
      </ul>
      {one && <Err>只放 1 份就跟「{nameOf(items[0].base)}」一樣；數量至少 2</Err>}
      {showErrors && items.length === 0 && <Err>至少放一種賣法</Err>}
      {picking ? (
        <div data-slot="sell-way-picker" className="mt-2 rounded-[10px] bg-muted/60 p-3">
          <div className="mb-2 flex items-center justify-between gap-2 text-xs font-semibold text-muted-foreground">
            <span>選一種基本賣法，再填數量</span>
            {items.length > 0 && <Button type="button" variant="link" className="h-auto p-0 text-xs" onClick={() => onPicking(false)}>收起</Button>}
          </div>
          {remaining.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {remaining.map((b) => (
                <button key={b.key} type="button" onClick={() => onAdd(b.key)}
                  className="flex items-center gap-2 rounded-[10px] border border-dashed border-input bg-card px-3 py-[7px] text-left text-[13px] hover:border-primary">
                  <Tile size={24} />
                  <span className="flex flex-col leading-[1.35]">
                    <b className="font-semibold">{b.name.trim() || "新的基本賣法"}</b>
                    <span className="text-[11.5px] text-muted-foreground">售價 {b.price != null ? swAmount(b.price) : "還沒填"}</span>
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted-foreground">
              這個商品的基本賣法都放進來了
              <Button type="button" variant="link" className="h-auto p-0 text-[13px]" onClick={onNewBase}>＋新增基本賣法</Button>
            </div>
          )}
        </div>
      ) : (
        <Button type="button" variant="link" className="mt-2.5 h-auto p-0 text-[13px]" onClick={() => onPicking(true)}>＋再放一種賣法</Button>
      )}
    </div>
  );
}

/** Prototype `.th`: the product tile (step 4 has no photo in its payload). */
export function Tile({ size }: { size: number }) {
  return <span aria-hidden="true" style={{ width: size, height: size }} className="inline-block shrink-0 rounded-lg bg-gradient-to-br from-muted to-input" />;
}

function Err({ children }: { children: ReactNode }) {
  return <p role="alert" className="mt-1 text-[11.5px] text-danger">{children}</p>;
}
