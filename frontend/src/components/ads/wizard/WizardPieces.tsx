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

/** 「NT$1,580」, another currency by its code, 「價格未填」 when there is no current price (never NT$0). */
export function priceText(price: number | null, currency: string | null): string {
  const amount = formatAmount(price);
  if (amount === null) return "價格未填";
  return !currency || currency === "TWD" ? `NT$${amount}` : `${currency} ${amount}`;
}

/** A product `PickCard`: the thumbnail is an authenticated URL, loaded through `useAuthedImage` (a failed or
 * missing photo draws the neutral tile). */
export function ProductPickCard({ product }: { product: WizardProduct }) {
  const { src } = useAuthedImage(product.thumbnail_url ?? undefined);
  return (
    <PickCard
      value={product.id}
      title={product.name}
      thumbnailUrl={src}
      note={<span className="numeric">{priceText(product.price, product.currency)}</span>}
      badge={<Chip tone={product.has_cost ? "ok" : "warn"}>{product.has_cost ? "有成本" : "缺成本"}</Chip>}
    />
  );
}

export type UnderstoodKey = "product" | "objective" | "dates" | "budget" | "platform" | "audience";
const FIELD_ICON: Record<UnderstoodKey, LucideIcon> = {
  product: Box, objective: Target, dates: CalendarDays, budget: DollarSign, platform: InfinityIcon, audience: Smile,
};

const CHIP_BOX = "flex w-full items-center gap-3 rounded-xl border bg-card px-3.5 py-3 text-left";
const ICON_TILE = "grid size-9 shrink-0 place-items-center rounded-[10px] bg-accent text-accent-foreground";

/** `.uchip`: one understood field — icon tile, label, the value in bold, 「猜的，請確認」 on a dashed border when
 * the system guessed it, a pen. Pressing it opens `editor` in place (`.uchip` with the primary border). */
export function UnderstoodField({ field, label, value, guessed, editing, onEdit, editor }: {
  field: UnderstoodKey;
  label: string;
  value: ReactNode;
  guessed: boolean;
  editing: boolean;
  /** Omitted = the field cannot be edited right now (its options did not load). */
  onEdit?: () => void;
  editor?: ReactNode;
}) {
  const Icon = FIELD_ICON[field];
  const tile = <span aria-hidden="true" className={ICON_TILE}><Icon className="size-4" strokeWidth={1.75} /></span>;
  const name = <span className="w-16 shrink-0 text-xs text-muted-foreground">{label}</span>;
  if (editing && editor) {
    return (
      <div data-field={field} className={cn(CHIP_BOX, "flex-wrap border-primary")}>
        {tile}{name}
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">{editor}</div>
      </div>
    );
  }
  const body = (
    <>
      {tile}{name}
      <b className="min-w-0 flex-1 text-[15px] font-semibold [overflow-wrap:anywhere]">{value}</b>
      {guessed && <Chip tone="warn">猜的，請確認</Chip>}
      {onEdit && <span aria-hidden="true" className="text-muted-foreground">✎</span>}
    </>
  );
  const box = cn(CHIP_BOX, guessed ? "border-dashed border-grade-watch/55" : "border-border");
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
