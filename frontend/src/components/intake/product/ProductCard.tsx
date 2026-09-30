import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import type { BundleCardData, ProductCardData, ProductSuggestion, SellWayBrief } from "@/lib/intakeProductApi";
import { useAuthedImage } from "@/lib/useAuthedImage";
import { cn } from "@/lib/utils";

/** One card of the products grid, prototype `.pc` of `.harness/scratch/prototype/f41-onboarding/index.html`:
 * `#/plist` (full: summary line, state chip, one row per sell-way, 「繼續建檔 →」 on drafts) and the `#/home`
 * 「你的商品」 block (`compact`: one line, the chip or 「繼續 →」 on drafts). Every number and label comes from
 * `GET /api/intake/brands/{b}/products` as is; the card only formats integers. */

const brandPath = (brandId: string) => `/brands/${encodeURIComponent(brandId)}`;

/** Product onboarding (F43-I08); without a step a finished product opens its last step. */
export const productOnboardingPath = (brandId: string, productId: string, step?: number | null) =>
  `${brandPath(brandId)}/products/${encodeURIComponent(productId)}/onboarding${step ? `?step=${step}` : ""}`;
export const newProductPath = (brandId: string) => `${brandPath(brandId)}/products/new`;
/** The bundle page (F43-I13). */
export const newBundlePath = (brandId: string) => `${brandPath(brandId)}/products/bundles/new`;
export const bundlePath = (brandId: string, bundleId: string) =>
  `${brandPath(brandId)}/products/bundles/${encodeURIComponent(bundleId)}`;

const amount = (value: number) => Math.round(value).toLocaleString("zh-TW");

/** 「399・打平 249」; a sell-way without a price or a known cost says so instead of printing 0. */
function priceLine(way: SellWayBrief): string {
  return `${way.price === null ? "未定價" : amount(way.price)}・打平 ${way.break_even === null ? "未知" : amount(way.break_even)}`;
}

/** Prototype `.chip.ok` / `.chip.warn` (the kit's `Chip` lives in `components/ads/patterns`, not exported). */
function StateChip({ state }: { state: "ready" | "draft" }) {
  const ready = state === "ready";
  return (
    <span
      data-slot="chip"
      data-tone={ready ? "ok" : "warn"}
      className={cn(
        "inline-flex shrink-0 items-center rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
        ready ? "bg-zone-ok text-success" : "bg-zone-watch text-warning",
      )}
    >
      {ready ? "可以投放" : "建到一半"}
    </span>
  );
}

function OfferChip({ label }: { label: string }) {
  return (
    <span data-slot="chip" data-tone="ok" className="inline-flex shrink-0 items-center rounded-full bg-zone-ok px-1.5 text-[11px] font-medium text-success">
      {label}
    </span>
  );
}

/** Prototype `.th` (a product photo) and `.th.x` (none). */
function Thumb({ url, size }: { url: string | null; size: number }) {
  const { src } = useAuthedImage(url ?? undefined);
  const box = { width: size, height: size };
  return src ? (
    <img src={src} alt="" style={box} className="shrink-0 rounded-lg object-cover" />
  ) : (
    <span aria-hidden="true" style={box} className="inline-block shrink-0 rounded-lg bg-muted" />
  );
}

function SellWayRow({ way, label }: { way: SellWayBrief; label?: string }) {
  return (
    <div data-slot="sell-way-row" className="flex justify-between gap-2">
      <span className="flex min-w-0 flex-wrap items-center gap-1">
        {label && <span className="[overflow-wrap:anywhere]">{label}</span>}
        {way.offer_labels.map((offer) => <OfferChip key={offer} label={offer} />)}
      </span>
      <span className="shrink-0 whitespace-nowrap tabular-nums">{priceLine(way)}</span>
    </div>
  );
}

function CardHead({ thumbs, name, to, line, right }: {
  thumbs: ReactNode;
  name: string;
  to: string;
  line: string;
  right: ReactNode;
}) {
  return (
    <div className="flex items-center gap-2.5">
      {thumbs}
      <div className="min-w-0 flex-1">
        <Link to={to} className="font-semibold text-foreground [overflow-wrap:anywhere] hover:text-primary">{name}</Link>
        <div className="text-[11.5px] text-muted-foreground">{line}</div>
      </div>
      {right}
    </div>
  );
}

const CARD = "flex flex-col gap-2.5 rounded-xl border border-border bg-card p-3.5";

function ContinueButton({ to, label }: { to: string; label: string }) {
  return (
    <Button asChild variant="outline" size="sm" className="self-start font-medium">
      <Link to={to}>{label}</Link>
    </Button>
  );
}

export type ProductCardProps = { brandId: string; compact?: boolean } & (
  | { product: ProductCardData; bundle?: undefined }
  | { bundle: BundleCardData; product?: undefined }
);

/** A knowledge product (with its sell-ways) or a bundle. */
export function ProductCard(props: ProductCardProps) {
  const { brandId, compact = false } = props;
  const thumbSize = compact ? 40 : 44;
  if (props.product) {
    const p = props.product;
    const draft = p.state === "draft";
    const next = productOnboardingPath(brandId, p.id, draft ? (p.step ?? 1) : null);
    const line = compact && !draft && p.sell_ways.length > 0
      ? p.sell_ways.map((w) => (w.price === null ? w.name : `${w.name} ${amount(w.price)}`)).join("・")
      : p.summary;
    const right = compact && draft
      ? <ContinueButton to={next} label="繼續 →" />
      : <StateChip state={p.state} />;
    return (
      <div data-slot="product-card" data-state={p.state} className={CARD}>
        <CardHead thumbs={<Thumb url={p.thumbnail_url} size={thumbSize} />} name={p.name} to={next} line={line} right={right} />
        {!compact && p.sell_ways.length > 0 && (
          <div className="flex flex-col gap-1 text-[12.5px]">
            {p.sell_ways.map((way) => <SellWayRow key={way.id} way={way} label={way.name} />)}
          </div>
        )}
        {!compact && draft && <ContinueButton to={next} label="繼續建檔 →" />}
      </div>
    );
  }
  const b = props.bundle;
  const size = compact ? 30 : 36;
  const thumbs = (
    <span className="flex">
      {(b.thumbnails.length > 0 ? b.thumbnails : [null]).map((url, i) => <Thumb key={`${i}-${url}`} url={url} size={size} />)}
    </span>
  );
  const line = compact
    ? `組合・${b.price === null ? "未定價" : amount(b.price)}`
    : `事實與證據沿用 ${new Set(b.components.map((c) => c.product_id)).size} 個商品`;
  return (
    <div data-slot="product-card" data-state={b.state} className={CARD}>
      <CardHead thumbs={thumbs} name={b.name} to={bundlePath(brandId, b.id)} line={line} right={<StateChip state={b.state} />} />
      {!compact && (
        <div className="flex flex-col gap-1 text-[12.5px]">
          <SellWayRow way={b} />
        </div>
      )}
    </div>
  );
}

/** A product the brand scan read that is not created yet: 「繼續建檔 →」 creates it (the page owns the call). */
export function SuggestionCard({ suggestion, busy, error, onContinue }: {
  suggestion: ProductSuggestion;
  busy: boolean;
  error: string | null;
  onContinue: () => void;
}) {
  return (
    <div data-slot="product-card" data-state="suggestion" className={CARD}>
      <div className="flex items-center gap-2.5">
        <Thumb url={null} size={44} />
        <div className="min-w-0 flex-1">
          <b className="font-semibold [overflow-wrap:anywhere]">{suggestion.name}</b>
          <div className="text-[11.5px] text-muted-foreground">AI 讀到了，還沒確認</div>
        </div>
      </div>
      <Button type="button" variant="outline" size="sm" className="self-start font-medium" disabled={busy} onClick={onContinue}>
        繼續建檔 →
      </Button>
      {error && <p role="alert" className="text-xs text-danger">{error}</p>}
    </div>
  );
}
