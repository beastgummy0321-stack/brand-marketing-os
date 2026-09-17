import { useEffect, useId, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

/** 進階收合（F04-I07）：R9「不點開是不會看到」的機器實作——進階設定永遠是同一頁裡的
 * 收合區塊，不是模式切換、不是第二頁、不是第二份資料模型。 */
export function Disclosure({
  label,
  children,
  defaultOpen = false,
  open: controlledOpen,
  onOpenChange,
}: {
  label: string;
  children: ReactNode;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const open = controlledOpen ?? uncontrolledOpen;
  const [hasOpened, setHasOpened] = useState(open);
  const contentId = useId();

  useEffect(() => {
    if (open) setHasOpened(true);
  }, [open]);

  function toggle() {
    const next = !open;
    if (next) setHasOpened(true);
    if (controlledOpen === undefined) setUncontrolledOpen(next);
    onOpenChange?.(next);
  }

  return (
    <div className="surface">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={contentId}
        onClick={toggle}
        className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left text-sm font-medium"
      >
        {label}
        <ChevronDown className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {hasOpened && (
        <div
          id={contentId}
          hidden={!open}
          inert={!open}
          aria-hidden={open ? undefined : true}
          className="border-t border-border px-4 py-3"
        >
          {children}
        </div>
      )}
    </div>
  );
}
