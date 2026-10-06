import type { ReactNode } from "react";
import { Button } from "@/components/layout/ui/button";
import type { SellWayNumbers } from "@/lib/intakeProductApi";
import { cn } from "@/lib/utils";
import { Tile } from "./SellWayContents";
import { EstChip, swAmount, SwChip } from "./SellWayTable";

/** One sell-way on step 4 (prototype `summary()` / `editor()` of `.harness/scratch/prototype/f45-sell-way-components/app.js`):
 * folded, a summary row (name, 「一份」 or 「單盒 × 12 ＋ …」, 售價, 打平, 「成本還沒填」, its offer sentences, 編輯);
 * open, the inline editor (名稱, 商品 or 裡面有什麼, 價格, delete or 「…用到它」, 完成). Every number is the server's. */

export function SellWaySummary({ name, shape, content, numbers, typedPrice, costMissing, onEdit }: {
  name: string;
  shape: "base" | "composed";
  /** 「一份」 / 「單盒 × 12 ＋ 體驗包 × 2」 / 「還沒放東西」. */
  content: string;
  /** The server's numbers (null = not saved yet). */
  numbers: SellWayNumbers | null;
  /** The typed price, shown before the first save. */
  typedPrice: string;
  /** A base without its own cost (「成本還沒填」). */
  costMissing: boolean;
  onEdit: () => void;
}) {
  const n = numbers;
  const price = n ? (n.price !== null ? swAmount(n.price) : "—") : typedPrice.trim() || "—";
  const label = name.trim() || "（還沒取名）";
  const offers = n?.offer_sentences ?? [];
  return (
    <div data-sw-row={name} data-kind={shape}
      className="grid grid-cols-[minmax(0,1.3fr)_120px_170px_minmax(0,1.5fr)_auto] items-center gap-x-4 gap-y-2 border-t border-border py-3 first:border-t-0 max-[900px]:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
      <div className="flex min-w-0 flex-col max-[900px]:col-span-2">
        <span className="font-semibold [overflow-wrap:anywhere]">{label}</span>
        <span className="text-[11.5px] text-muted-foreground [overflow-wrap:anywhere]">{content}</span>
      </div>
      <div className="max-[900px]:order-3">
        <span className="block text-[11.5px] text-muted-foreground">售價</span>
        <b className="text-[15px] tabular-nums">{price}</b>
        {n?.price_derived && <EstChip className="ml-1.5" />}
      </div>
      <div className="max-[900px]:order-4 max-[900px]:col-span-2">
        <span className="block text-[11.5px] text-muted-foreground">打平</span>
        {n?.break_even != null ? (
          <>
            <b className="text-[15px] tabular-nums">{swAmount(n.break_even)}</b>
            {n.break_even_derived && <EstChip className="ml-1.5" />}
            {n.break_even <= 0 && <span className="block text-[11.5px] text-warning">{n.break_even < 0 ? "未投廣告已虧損" : "沒有可用廣告空間"}</span>}
          </>
        ) : (
          <SwChip tone="warn">還算不出來</SwChip>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1.5 max-[900px]:order-5 max-[900px]:col-span-3">
        {costMissing && <SwChip tone="warn">成本還沒填</SwChip>}
        {offers.length > 0
          ? offers.map((o) => <SwChip key={o} tone="ok" sentence>{o}</SwChip>)
          : <span className="text-[11.5px] whitespace-nowrap text-muted-foreground">沒有優惠</span>}
      </div>
      <Button type="button" variant="outline" size="sm" className="justify-self-end max-[900px]:order-2" aria-label={`編輯「${label}」`} onClick={onEdit}>
        編輯
      </Button>
    </div>
  );
}

export function SellWayEditor({ rowKey, shape, name, productName, showErrors, returnTo, usedBy, contents, price, onName, onDelete, onDone, busy }: {
  rowKey: string;
  shape: "base" | "composed";
  name: string;
  productName: string;
  showErrors: boolean;
  /** Opened from 「去填〈base〉的成本 →」 of this composed sell-way: the retbar and 「填好了，回到「…」」. */
  returnTo: string | null;
  /** The composed sell-ways that use this base (it cannot be deleted while used). */
  usedBy: string[];
  /** 「裡面有什麼」 (composed only). */
  contents: ReactNode;
  /** The price block. */
  price: ReactNode;
  onName: (name: string) => void;
  onDelete: () => void;
  onDone: () => void;
  busy: boolean;
}) {
  const isBase = shape === "base";
  const title = name.trim() || (isBase ? "新的基本賣法" : "新的組合");
  return (
    <div data-sw-row={name} data-kind={shape} data-state="editing"
      className="my-2.5 rounded-xl border border-primary bg-card px-[18px] py-4 shadow-[0_0_0_3px_var(--color-accent)] max-[480px]:px-3">
      {returnTo !== null && (
        <div data-slot="return-bar" className="mb-3.5 flex flex-wrap items-center gap-x-4 gap-y-2.5 rounded-[10px] bg-zone-watch px-3.5 py-2.5 text-[13px]">
          <span>「{returnTo}」要用{title}的成本才算得出打平</span>
          <Button type="button" variant="link" className="h-auto p-0 text-[13px]" busy={busy} onClick={onDone}>填好了，回到「{returnTo}」 →</Button>
        </div>
      )}
      <div className="mb-3.5 flex flex-wrap items-center gap-2.5">
        <SwChip tone={isBase ? "neutral" : "accent"}>{isBase ? "基本賣法" : "組合賣法"}</SwChip>
        <h2 className="text-[15px] font-semibold [overflow-wrap:anywhere]">{title}</h2>
      </div>
      <Q label={<label htmlFor={`${rowKey}-name`}>名稱</label>} first>
        <input id={`${rowKey}-name`} value={name} placeholder={isBase ? "例如：單盒、體驗包" : "例如：12 盒、5 盒＋2 包"} onChange={(e) => onName(e.target.value)}
          aria-invalid={showErrors && !name.trim() ? true : undefined}
          className={cn("w-full rounded-lg border bg-card px-3 py-[9px] text-sm focus:border-primary focus:shadow-[0_0_0_3px_var(--color-accent)] focus:outline-none focus-visible:outline-none",
            showErrors && !name.trim() ? "border-danger" : "border-input")} />
        {showErrors && !name.trim() && <p role="alert" className="mt-1 text-[11.5px] text-danger">請填賣法名稱</p>}
      </Q>
      <Q label={isBase ? "商品" : "裡面有什麼"}>
        {isBase ? (
          <div className="flex items-center gap-2.5 rounded-[10px] border border-border bg-background px-3 py-2">
            <Tile size={32} />
            <div className="min-w-0 flex-1">
              <b className="block font-semibold [overflow-wrap:anywhere]">{productName}</b>
              <div className="text-[11.5px] text-muted-foreground">一份就是一個單位，不用填數量</div>
            </div>
          </div>
        ) : contents}
      </Q>
      <Q label="價格">{price}</Q>
      <div className="mt-1 flex flex-wrap items-center gap-2.5 border-t border-border pt-3.5">
        {usedBy.length > 0 ? (
          <span className="text-[11.5px] text-muted-foreground">{usedBy.map((u) => `「${u}」`).join("")}用到它，先從組合拿掉才能刪</span>
        ) : (
          <Button type="button" variant="ghost" size="sm" className="text-danger hover:bg-zone-over hover:text-danger" busy={busy} onClick={onDelete}>
            刪除這個賣法
          </Button>
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2.5 max-[480px]:ml-0 max-[480px]:w-full">
          <Button type="button" variant="outline" className="border-primary text-primary hover:bg-accent max-[480px]:flex-1" busy={busy} onClick={onDone}>
            {returnTo !== null ? `填好了，回到「${returnTo}」` : "完成"}
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Prototype `.q`: the label column and its field. */
function Q({ label, first, children }: { label: ReactNode; first?: boolean; children: ReactNode }) {
  return (
    <div className={cn("grid grid-cols-[120px_minmax(0,1fr)] items-start gap-x-5 gap-y-2 py-3.5 max-[760px]:grid-cols-1", first ? "pt-0" : "border-t border-border")}>
      <b className="block pt-2 text-sm font-semibold max-[760px]:pt-0">{label}</b>
      <div className="min-w-0">{children}</div>
    </div>
  );
}
