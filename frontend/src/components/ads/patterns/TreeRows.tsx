import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Thumb } from "./LoopPieces";

/** v10 `tabStructure()` `.tree2` (F30): campaign → ad groups → ads. The root node (`.node.root`) sits left with a
 * connector into the spine; each group block (`.sblk`) is a group node (`.node.set`) beside its leaf list
 * (`.leafs` / `.leaf`). A leaf is a 28px thumbnail, the ad name, then the caller's chip and number (one right-aligned
 * cell that wraps under a long name instead of squeezing it, F31-I12). A leaf with
 * `missing` shows the dashed empty tile and 「缺素材」 instead of the name (a draft slot without material);
 * `dimmed` is the half-transparent 關閉中 row. `data-slot="tree-rows"`. */

export interface TreeNodeInfo { kind: string; name: string; note?: ReactNode }
export interface TreeLeaf {
  key: string;
  name: string;
  thumbnailUrl: string | null;
  missing?: boolean;
  missingLabel?: string;
  dimmed?: boolean;
  chip?: ReactNode;
  value?: ReactNode;
}
export interface TreeGroup extends TreeNodeInfo { key: string; leaves: TreeLeaf[] }

function Node({ node, root = false, children }: { node: TreeNodeInfo; root?: boolean; children?: ReactNode }) {
  return (
    <div className={cn("relative rounded-[10px] border px-3.5 py-3", root ? "border-primary bg-accent/50" : "border-border bg-card")}>
      <div className="text-[11.5px] text-muted-foreground">{node.kind}</div>
      <b className="font-semibold [overflow-wrap:anywhere]">{node.name}</b>
      {node.note && <div className="text-xs text-muted-foreground">{node.note}</div>}
      {children}
    </div>
  );
}

export function TreeRows({ root, groups }: { root: TreeNodeInfo; groups: TreeGroup[] }) {
  return (
    <div data-slot="tree-rows" className="grid grid-cols-[190px_minmax(0,1fr)] items-start gap-x-7 max-[1180px]:grid-cols-[160px_minmax(0,1fr)]">
      <Node node={root} root><span aria-hidden="true" className="absolute top-[26px] -right-[30px] w-[30px] border-t-2 border-border" /></Node>
      <ul className="m-0 flex min-w-0 list-none flex-col gap-4 border-l-2 border-border py-0 pr-0 pl-[22px]">
        {groups.map((g) => (
          <li key={g.key} className="grid grid-cols-[190px_minmax(0,1fr)] items-start gap-x-[22px] max-[1180px]:grid-cols-[160px_minmax(0,1fr)]">
            <Node node={g}><span aria-hidden="true" className="absolute top-[26px] -left-6 w-[22px] border-t-2 border-border" /></Node>
            <ul aria-label={g.name} className="m-0 list-none border-l-2 border-border py-0 pr-0 pl-[18px]">
              {g.leaves.map((leaf) => (
                <li key={leaf.key} data-variant={leaf.missing ? "missing" : leaf.dimmed ? "dimmed" : "ad"}
                  className={cn("relative flex flex-wrap items-center gap-x-2.5 gap-y-1 py-1.5", leaf.dimmed && "opacity-50")}>
                  <span aria-hidden="true" className="absolute top-1/2 -left-[18px] w-3.5 border-t-2 border-border" />
                  {leaf.missing
                    ? <span aria-hidden="true" className="size-7 shrink-0 rounded-lg border-[1.5px] border-dashed border-grade-thin bg-muted" />
                    : <Thumb url={leaf.thumbnailUrl} size={28} />}
                  {/* The name grows from its own width with a floor, so a long name never shrinks to a one-character
                      column beside the chip and number (1024); when they do not fit, they wrap under it instead. */}
                  <span className="min-w-[8rem] flex-[1_1_auto] text-xs font-medium [overflow-wrap:anywhere]">
                    {leaf.missing ? <span className="text-muted-foreground">{leaf.missingLabel ?? "缺素材"}</span> : leaf.name}
                  </span>
                  {(leaf.chip || leaf.value !== undefined) && (
                    <span data-part="facts" className="ml-auto flex max-w-full items-center justify-end gap-2.5">
                      {leaf.chip}
                      {leaf.value !== undefined && <b className="numeric min-w-[76px] text-right text-xs font-semibold">{leaf.value}</b>}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}
