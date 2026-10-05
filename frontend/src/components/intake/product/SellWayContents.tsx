import type { ReactNode } from "react";
import { Button } from "@/components/layout/ui/button";
import { useAuthedImage } from "@/lib/useAuthedImage";
import { cn } from "@/lib/utils";
import { swAmount } from "./SellWayTable";

/** 「裡面有什麼」 of a composed sell-way (prototype `contents()` + `picker()` of
 * `.harness/scratch/prototype/f45-sell-way-components/app.js`): rows 〈base sell-way〉 × qty, each with that base's own
 * 售價・成本 (the server's numbers of the base), the quantity box, ×, and the picker of the bases not in yet.
 * Step 4 offers this product's bases (「＋新增基本賣法」 once all are in); the bundle page (`cross`) offers every
 * finished product's bases grouped by product, and each row names its product. Items reference a base by its key,
 * so renaming a base renames it here. */

export interface ContentItem {
  /** The base's key (step 4: its row key; bundle page: its sell-way id). */
  base: string;
  /** As typed. */
  qty: string;
}

export interface BaseOption {
  key: string;
  name: string;
  /** That base's own effective numbers (null = none; `cost` undefined = not known to the page yet, printed 「—」). */
  price: number | null;
  cost: number | null | undefined;
  /** The base's knowledge product (the bundle page: shown on the row, groups the picker). */
  product?: { id: string; name: string; thumbnail_url: string | null };
}

/** F50 Contract I: a quantity is sent as typed; the server (`input_rules.count`, at least 1; Σqty at least 2) refuses
 * with its sentence. `errors` are those refusals for this sell-way: `components` (the contents as a whole) and
 * `components.{i}.qty` (row i's quantity). */
export function SellWayContents({ idPrefix, items, bases, picking, errors, cross = false, empty, onQty, onRemove, onAdd, onPicking, onNewBase }: {
  idPrefix: string;
  items: ContentItem[];
  /** The bases that can be picked (step 4: this product's; bundle page: every finished product's). */
  bases: BaseOption[];
  picking: boolean;
  errors: Partial<Record<string, string>>;
  /** The bundle page: rows name their product, the picker groups by product; the server checks the product count. */
  cross?: boolean;
  /** The picker's body when nothing is left to pick (default: 「這個商品的基本賣法都放進來了」 + 「＋新增基本賣法」). */
  empty?: ReactNode;
  onQty: (index: number, qty: string) => void;
  onRemove: (index: number) => void;
  onAdd: (baseKey: string) => void;
  onPicking: (open: boolean) => void;
  onNewBase?: () => void;
}) {
  const byKey = new Map(bases.map((b) => [b.key, b]));
  const nameOf = (key: string) => byKey.get(key)?.name.trim() || "新的基本賣法";
  /** The row's accessible name: on the bundle page two products may both have a 「單盒」. */
  const labelOf = (key: string) => {
    const product = byKey.get(key)?.product;
    return cross && product ? `${product.name}・${nameOf(key)}` : nameOf(key);
  };
  const remaining = bases.filter((b) => !items.some((it) => it.base === b.key));
  const groups: { product: BaseOption["product"]; list: BaseOption[] }[] = [];
  for (const b of remaining) {
    const group = cross ? groups.find((g) => g.product?.id === b.product?.id) : groups[0];
    if (group) group.list.push(b);
    else groups.push({ product: b.product, list: [b] });
  }
  return (
    <div data-slot="sell-way-contents">
      <ul aria-label="裡面有什麼" className="flex flex-col gap-2">
        {items.map((it, i) => {
          const base = byKey.get(it.base);
          const name = nameOf(it.base);
          const label = labelOf(it.base);
          const qtyError = errors[`components.${i}.qty`];
          const bad = Boolean(qtyError);
          return (
            <li key={it.base}>
              <div className="flex items-center gap-2.5 rounded-[10px] border border-border bg-card px-3 py-2 max-[480px]:flex-wrap">
                <Tile size={32} url={base?.product?.thumbnail_url} />
                <div className="min-w-0 flex-1 max-[480px]:basis-[calc(100%-90px)]">
                  {cross && base?.product && <div className="text-xs text-muted-foreground [overflow-wrap:anywhere]">{base.product.name}</div>}
                  <b className="block font-semibold [overflow-wrap:anywhere]">{name}</b>
                  <div className="text-[11.5px] text-muted-foreground">
                    售價 {base?.price != null ? swAmount(base.price) : "還沒填"}・成本{" "}
                    {base?.cost === undefined ? "—" : base.cost !== null ? swAmount(base.cost) : <span className="font-medium text-warning">還沒填</span>}
                  </div>
                </div>
                <span className={cn(
                  "inline-flex w-[92px] shrink-0 items-center rounded-lg border bg-card px-2.5 focus-within:border-primary focus-within:shadow-[0_0_0_3px_var(--color-accent)] max-[480px]:ml-[42px]",
                  bad ? "border-danger" : "border-input",
                )}>
                  <span aria-hidden="true" className="text-muted-foreground">×</span>
                  <input id={`${idPrefix}-q${i}`} inputMode="numeric" autoComplete="off" aria-label={`${label}的數量`} aria-invalid={bad ? true : undefined}
                    value={it.qty} placeholder="數量" onChange={(e) => onQty(i, e.target.value)}
                    className="w-full min-w-0 border-0 bg-transparent px-1.5 py-2 text-[15px] font-semibold tabular-nums outline-none focus-visible:outline-none" />
                </span>
                <button type="button" aria-label={`拿掉${label}`} onClick={() => onRemove(i)}
                  className="rounded-md p-1.5 text-lg leading-none text-muted-foreground hover:bg-muted hover:text-danger">×</button>
              </div>
              {qtyError && <Err>{qtyError}</Err>}
            </li>
          );
        })}
      </ul>
      {errors.components && <Err>{errors.components}</Err>}
      {picking ? (
        <div data-slot="sell-way-picker" className="mt-2 rounded-[10px] bg-muted/60 p-3">
          <div className="mb-2 flex items-center justify-between gap-2 text-xs font-semibold text-muted-foreground">
            <span>選一種基本賣法，再填數量</span>
            {items.length > 0 && <Button type="button" variant="link" className="h-auto p-0 text-xs" onClick={() => onPicking(false)}>收起</Button>}
          </div>
          {groups.length > 0 ? (
            groups.map((g) => (
              <div key={g.product?.id ?? "-"} role={cross ? "group" : undefined} aria-label={cross ? g.product?.name : undefined}>
                {cross && g.product && <div className="mt-2.5 mb-1.5 text-xs font-semibold text-muted-foreground first:mt-0 [overflow-wrap:anywhere]">{g.product.name}</div>}
                <div className="flex flex-wrap gap-2">
                  {g.list.map((b) => (
                    <button key={b.key} type="button" onClick={() => onAdd(b.key)} aria-label={cross ? `放進「${labelOf(b.key)}」` : undefined}
                      className="flex items-center gap-2 rounded-[10px] border border-dashed border-input bg-card px-3 py-[7px] text-left text-[13px] hover:border-primary">
                      <Tile size={24} url={b.product?.thumbnail_url} />
                      <span className="flex flex-col leading-[1.35]">
                        <b className="font-semibold">{b.name.trim() || "新的基本賣法"}</b>
                        <span className="text-[11.5px] text-muted-foreground">售價 {b.price != null ? swAmount(b.price) : "還沒填"}</span>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))
          ) : empty ?? (
            <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted-foreground">
              這個商品的基本賣法都放進來了
              {onNewBase && <Button type="button" variant="link" className="h-auto p-0 text-[13px]" onClick={onNewBase}>＋新增基本賣法</Button>}
            </div>
          )}
        </div>
      ) : (
        <Button type="button" variant="link" className="mt-2.5 h-auto p-0 text-[13px]" onClick={() => onPicking(true)}>＋再放一種賣法</Button>
      )}
    </div>
  );
}

/** Prototype `.th`: the product photo when the page has one, else the empty tile (step 4 has no photo in its payload). */
export function Tile({ size, url }: { size: number; url?: string | null }) {
  const { src } = useAuthedImage(url ?? undefined);
  const box = { width: size, height: size };
  return src
    ? <img src={src} alt="" style={box} className="shrink-0 rounded-lg object-cover" />
    : <span aria-hidden="true" style={box} className="inline-block shrink-0 rounded-lg bg-gradient-to-br from-muted to-input" />;
}

function Err({ children }: { children: ReactNode }) {
  return <p role="alert" className="mt-1 text-[11.5px] text-danger">{children}</p>;
}
