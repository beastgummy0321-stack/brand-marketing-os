import { Button } from "@/components/layout/ui/button";
import { useEffect, useRef } from "react";

export interface RowMenuItem { label: string; onSelect: () => void; busy?: boolean; disabledReason?: string | null }

/** v10 `details.mn`: the 「⋯」 menu at the end of an ad row (換掉這一則／看紀錄). A native `<details>`, so it is
 * keyboard reachable without script; choosing an item, Escape or a click outside closes it.
 * `data-slot="row-menu"`. */
export function RowMenu({ label, items }: { label: string; items: RowMenuItem[] }) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current?.open && !ref.current.contains(e.target as Node)) ref.current.open = false; };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const shut = () => { if (ref.current) ref.current.open = false; };
  return (
    <details ref={ref} data-slot="row-menu" className="group/mn relative inline-block"
      onKeyDown={(e) => { if (e.key === "Escape" && ref.current?.open) { shut(); ref.current.querySelector("summary")?.focus(); } }}>
      <summary aria-label={label}
        className="grid size-[30px] cursor-pointer list-none place-items-center rounded-lg p-0 font-bold tracking-[1px] text-muted-foreground group-open/mn:bg-muted hover:bg-muted [&::-webkit-details-marker]:hidden">
        ⋯
      </summary>
      <div className="absolute top-[34px] right-0 z-[8] min-w-[190px] rounded-[10px] border border-border bg-card p-1.5 text-left shadow-lg">
        {items.map((item) => (
          <Button variant="ghost" key={item.label} type="button" busy={item.busy} disabledReason={item.disabledReason}
            onClick={() => { shut(); item.onSelect(); }}
            className="block h-auto w-full rounded-[7px] px-2.5 py-2 text-left text-[13px] hover:bg-muted disabled:opacity-45">
            {item.label}
          </Button>
        ))}
      </div>
    </details>
  );
}
