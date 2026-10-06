import { Check } from "lucide-react";
import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/layout/ui/button";
import { cn } from "@/lib/utils";

/** Head and bottom bar of an onboarding flow, prototype `head(kind, cur, title, purpose)` and
 * `bar({back, hint, html})` of `.harness/scratch/prototype/f41-onboarding/index.html`: crumb, step
 * dots with inline labels, h1 + one purpose line; a sticky bottom bar. Shared by the seven brand
 * steps (`BRAND_STEPS`) and, with its own crumb and step list, by product onboarding (F43).
 * `data-slot` values are what `frontend/scripts/ui-evidence.cjs` matches to the prototype pieces. */

/** Prototype `BSTEPS`: 1 基本 · 2 AI 讀網站 · 3 品牌是誰 · 4 證據與政策 · 5 素材 · 6 接工具 · 7 完成. */
export const BRAND_STEPS = ["基本", "AI 讀網站", "品牌是誰", "證據與政策", "素材", "接工具", "完成"];

export interface CrumbItem {
  label: string;
  /** In-app link (a parent page). */
  to?: string;
  /** The flow's own name (`<b>` in the prototype). */
  strong?: boolean;
}

/** 「品牌建檔 › 〈品牌〉」; a brand not created yet has no name. */
export function brandCrumb(brandName: string): CrumbItem[] {
  const name = brandName.trim();
  return name ? [{ label: "品牌建檔", strong: true }, { label: name }] : [{ label: "品牌建檔", strong: true }];
}

/** Where the flow is: what the wizard hands to every step so each renders the same head. */
export interface StepNav {
  crumb: CrumbItem[];
  steps: string[];
  /** 1-based. */
  current: number;
  /** Steps the user may jump to by their dot (visited ones; every step on re-entry). */
  canSelect?: (step: number) => boolean;
  onSelect?: (step: number) => void;
}

export function OnboardingStepHead({ crumb, steps, current, canSelect, onSelect, title, purpose }: StepNav & {
  title?: string;
  purpose?: string;
}) {
  return (
    <header data-slot="flow-header">
      <nav aria-label="建檔位置" className="flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
        {crumb.map((item, i) => (
          <Fragment key={`${i}-${item.label}`}>
            {i > 0 && <span aria-hidden="true">›</span>}
            {item.to ? (
              <Link to={item.to} className="text-muted-foreground hover:text-primary">{item.label}</Link>
            ) : item.strong ? (
              <b className="font-semibold text-foreground">{item.label}</b>
            ) : (
              <span className="[overflow-wrap:anywhere]">{item.label}</span>
            )}
          </Fragment>
        ))}
      </nav>
      <div className="mt-3 mb-1">
        <ol className="mb-3.5 flex flex-wrap items-center gap-y-1.5">
          {steps.map((label, i) => {
            const step = i + 1;
            const done = step < current;
            const on = step === current;
            const dot = cn(
              "grid size-[26px] shrink-0 place-items-center rounded-full p-0 text-xs font-semibold",
              done || on ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
              on && "shadow-[0_0_0_5px_var(--color-accent)]",
            );
            const mark = done ? <Check size={13} strokeWidth={3} aria-hidden="true" /> : step;
            const selectable = !on && !!onSelect && !!canSelect?.(step);
            return (
              <li key={label} className="flex items-center" aria-current={on ? "step" : undefined}>
                {i > 0 && <span className="mr-2 h-px w-[18px] bg-border" aria-hidden="true" />}
                {selectable ? (
                  <button type="button" className={cn(dot, "hover:opacity-85")} aria-label={`回到${label}`} onClick={() => onSelect(step)}>
                    {mark}
                  </button>
                ) : (
                  <span className={dot}>{mark}</span>
                )}
                <span className={cn("mr-2 ml-[7px] text-[12.5px] whitespace-nowrap", on ? "font-semibold text-foreground" : "text-muted-foreground")}>
                  {label}
                </span>
              </li>
            );
          })}
        </ol>
        {title && <h1 className="text-[26px] leading-tight font-[650] tracking-[-0.025em]">{title}</h1>}
        {purpose && <p className="mt-1 text-[15px] text-muted-foreground">{purpose}</p>}
      </div>
    </header>
  );
}

export interface BarBack {
  label: string;
  onClick: () => void;
}

/** Prototype `.bar`: sticky at the bottom of the page; back on the left, hint + actions on the right
 * (same sticky technique and page-padding bleed as the ads flow bar). */
export function OnboardingBar({ back, hint, children }: { back?: BarBack; hint?: string; children?: ReactNode }) {
  return (
    <div data-slot="action-bar" className="sticky bottom-0 z-10 -mx-[22px] mt-2 flex flex-wrap items-center gap-3 border-t border-border bg-card/95 px-5 py-3 backdrop-blur xl:-mx-7">
      {back && (
        <Button type="button" variant="ghost" onClick={back.onClick}>
          ← {back.label}
        </Button>
      )}
      <div className="ml-auto flex flex-wrap items-center justify-end gap-2.5">
        {hint && <small className="text-xs text-muted-foreground">{hint}</small>}
        {children}
      </div>
    </div>
  );
}

/** The bar's primary button (`.btn.pri`). F51 Contract D: it forwards `busy`／`disabledReason` to `Button`, so a
 * greyed-out 下一步 says why. */
export function BarNext({ label, busy, disabledReason, onClick, type = "button" }: {
  label: string;
  busy?: boolean;
  disabledReason?: string | null;
  onClick?: () => void;
  type?: "button" | "submit";
}) {
  return (
    <Button type={type} size="lg" className="font-semibold" busy={busy} disabledReason={disabledReason}
      onClick={onClick}>
      {label} →
    </Button>
  );
}
