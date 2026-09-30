import type { ReactNode } from "react";
import {
  Box, CalendarDays, DollarSign, Heart, Infinity as InfinityIcon, Mail, Megaphone, MousePointerClick,
  ShoppingCart, Smartphone, Smile, Store, Target, type LucideIcon,
} from "lucide-react";
import { Skeleton } from "@/components/layout/Skeleton";
import { useAuthedImage } from "@/lib/useAuthedImage";
import type { WizardProduct } from "@/lib/adsWizardApi";
import { cn } from "@/lib/utils";
import { Chip, FlowHeader, PickCard, ReadFailed, WaitLine, formatAmount, type FlowStep } from "../patterns";

/** Screen pieces of the new-campaign wizard v10 (F30-I05, prototype `newHead()`/`newStep1()`/`newStep2()`).
 * Only layout built with tokens and compositions of kit pieces live here; the kit pieces themselves come from
 * `../patterns`. */

export const newCampaignPath = (brandId: string, createdId?: string | null) =>
  `/brands/${brandId}/ads/new${createdId ? `?created=${encodeURIComponent(createdId)}` : ""}`;

/** `newHead()`: 選商品與目標 → 系統理解 → 策略. Step 1 links back only once a campaign exists (its picks reload
 * from it; going back never creates a second campaign). */
export function wizardSteps(brandId: string, createdId?: string | null): FlowStep[] {
  return [
    { label: "選商品與目標", to: createdId ? newCampaignPath(brandId, createdId) : undefined },
    { label: "系統理解" },
    { label: "策略" },
  ];
}

const OBJECTIVE_ICON: Record<string, LucideIcon> = {
  購買: ShoppingCart, 名單: Mail, 流量: MousePointerClick, 知名度: Megaphone, 互動: Heart, "App 推廣": Smartphone, 來店: Store,
};
/** The icon tile of an objective card (`.pk.goal .ic`); an objective the catalog adds later gets a neutral target. */
export function ObjectiveIcon({ objective }: { objective: string }) {
  const Icon = OBJECTIVE_ICON[objective] ?? Target;
  return <Icon className="size-5" strokeWidth={1.75} />;
}

/** 「NT$1,580」, another currency by its code, 「價格未填」 when there is no usable current price (never NT$0). */
export function priceText(price: number | null, currency: string | null): string {
  const amount = price !== null && price > 0 ? formatAmount(price) : null;
  if (amount === null) return "價格未填";
  return !currency || currency === "TWD" ? `NT$${amount}` : `${currency} ${amount}`;
}

/** 「打平 669・組合價＋免運」: the sell-way's break-even (「缺成本」 when its cost is not set, 「打平算不出」 when the
 * cost is set but no current price) and its offers (「沒有優惠」 when none). */
export function sellWayNote(way: WizardProduct): string {
  const be = way.break_even !== null ? `打平 ${formatAmount(way.break_even) ?? "未知"}` : way.has_cost ? "打平算不出" : "缺成本";
  return `${be}・${way.offer_labels.length ? way.offer_labels.join("＋") : "沒有優惠"}`;
}

/** `#/new` `.pk` (F43-I15): one sell-way as a `PickCard` — 「〈賣法〉 〈price〉」 over 「打平 〈be〉・〈offers〉」. The
 * thumbnail is an authenticated URL, loaded through `useAuthedImage` (a failed or missing photo draws the neutral
 * tile). */
export function SellWayPickCard({ way }: { way: WizardProduct }) {
  const { src } = useAuthedImage(way.thumbnail_url ?? undefined);
  return (
    <PickCard
      value={way.id}
      title={`${way.display_name} ${priceText(way.price, way.currency)}`}
      thumbnailUrl={src}
      note={<span className="numeric">{sellWayNote(way)}</span>}
    />
  );
}

/** The six campaign fields plus `cap` (F36-I04: 「每賣一筆最多花」, the optional per-sale cap saved through the target). */
export type UnderstoodKey = "product" | "objective" | "dates" | "budget" | "platform" | "audience" | "cap";
const FIELD_ICON: Record<UnderstoodKey, LucideIcon> = {
  product: Box, objective: Target, dates: CalendarDays, budget: DollarSign, platform: InfinityIcon, audience: Smile, cap: Target,
};

const CHIP_BOX = "flex w-full items-center gap-3 rounded-xl border bg-card px-3.5 py-3 text-left";
const ICON_TILE = "grid size-9 shrink-0 place-items-center rounded-[10px] bg-accent text-accent-foreground";

/** `.uchip`: one understood field — icon tile, label, the value in bold, 「猜的，請確認」 on a dashed border when
 * the system guessed it, a pen. Pressing it opens `editor` in place (`.uchip` with the primary border).
 * F36 `capChip()` adds three optional states the six fields never set: `empty` (`.uchip.empty`: a neutral dashed
 * border and a muted value — an optional field left blank, not a guess), a `hint` line under the value (`.val`),
 * and `wide` (`.uchip.editing` spans both grid columns while editing). */
export function UnderstoodField({ field, label, value, guessed, editing, onEdit, editor, empty, hint, wide }: {
  field: UnderstoodKey;
  label: string;
  value: ReactNode;
  guessed: boolean;
  editing: boolean;
  /** Omitted = the field cannot be edited right now (its options did not load). */
  onEdit?: () => void;
  editor?: ReactNode;
  empty?: boolean;
  hint?: ReactNode;
  wide?: boolean;
}) {
  const Icon = FIELD_ICON[field];
  const tile = <span aria-hidden="true" className={ICON_TILE}><Icon className="size-4" strokeWidth={1.75} /></span>;
  const name = <span className="w-16 shrink-0 text-xs text-muted-foreground">{label}</span>;
  if (editing && editor) {
    return (
      <div data-field={field} className={cn(CHIP_BOX, "flex-wrap border-primary", wide && "md:col-span-2")}>
        {tile}{name}
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">{editor}</div>
      </div>
    );
  }
  const text = <b className={cn("min-w-0 flex-1 text-[15px]", empty ? "font-medium text-muted-foreground" : "font-semibold", "[overflow-wrap:anywhere]")}>{value}</b>;
  const body = (
    <>
      {tile}{name}
      {hint
        ? <span className="flex min-w-0 flex-1 flex-col gap-0.5">{text}<span className="text-xs text-muted-foreground">{hint}</span></span>
        : text}
      {guessed && <Chip tone="warn">猜的，請確認</Chip>}
      {onEdit && <span aria-hidden="true" className="text-muted-foreground">✎</span>}
    </>
  );
  const box = cn(CHIP_BOX, guessed ? "border-dashed border-grade-watch/55" : empty ? "border-dashed border-border" : "border-border");
  return onEdit
    ? <button type="button" data-field={field} aria-label={`改${label}`} onClick={onEdit} className={cn(box, "hover:border-primary")}>{body}</button>
    : <div data-field={field} className={box}>{body}</div>;
}

/** The six field slots while the fields are not there yet (`.uchip` + `.skel`). */
export function UnderstoodSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className={cn(CHIP_BOX, "border-border")}>
          <span className={ICON_TILE} />
          <div className="flex-1">
            <Skeleton className="h-3.5 w-[30%]" />
            <Skeleton className="mt-2 h-3.5 w-[70%]" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Step 2 while the create call is understanding the picks (`newStep2()` before `parsed`): a running wait line,
 * or the prototype's fail box with 重試 — the picks stay on step 1. */
export function UnderstandingView({ brandId, failed, waitedSeconds, onRetry }: {
  brandId: string;
  failed: string | null;
  waitedSeconds: number;
  onRetry: () => void;
}) {
  return (
    <>
      <FlowHeader steps={wizardSteps(brandId)} current={1} title={failed ? "系統理解" : "系統理解中"} purpose="整理你選的內容" />
      {failed
        ? <ReadFailed what={`系統理解的結果讀不到（${failed}）；你選的商品和目標都還在`} onRetry={onRetry} />
        : <WaitLine title="系統正在理解你選的內容" status="running" position={null} total={null} waitedSeconds={waitedSeconds} />}
      <UnderstoodSkeleton />
    </>
  );
}
