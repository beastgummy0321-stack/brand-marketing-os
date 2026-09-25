import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { Grade } from "./Chip";
import { Thumb } from "./LoopPieces";
import { GradeTermChip } from "./Term";

/** v10 `.pickrow` (cleanup proposal 「自己挑要關哪幾則」): the whole row is the checkbox's label — tick box,
 * thumbnail, name, grade chip (plain: a tap toggles the box), and the numbers on the right. An unticked row
 * dims its thumbnail and name. `data-slot="pick-row"`, `data-variant` on/off. */
export function PickRow({ checked, onChange, name, thumbnailUrl, grade, gradeLabel, action = "關掉", aside, disabled }: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  name: string;
  thumbnailUrl: string | null;
  grade: Grade | null;
  gradeLabel?: string | null;
  /** Verb for the checkbox's accessible name: 「關掉「<name>」」. */
  action?: string;
  aside?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label data-slot="pick-row" data-variant={checked ? "on" : "off"}
      className="grid cursor-pointer grid-cols-[22px_36px_minmax(0,1fr)_auto_auto] items-center gap-3 border-t border-border py-[9px] first:border-t-0">
      <input type="checkbox" className="m-0 size-[18px]" checked={checked} disabled={disabled}
        onChange={(e) => onChange(e.target.checked)} aria-label={`${action}「${name}」`} />
      <span className={cn(!checked && "opacity-50")}><Thumb url={thumbnailUrl} size={36} /></span>
      <span className={cn("font-medium [overflow-wrap:anywhere]", !checked && "opacity-50")}>{name}</span>
      <GradeTermChip grade={grade} label={gradeLabel} plain />
      <span className="numeric text-right text-xs">{aside}</span>
    </label>
  );
}
