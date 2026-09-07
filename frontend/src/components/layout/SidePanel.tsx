import { useRef, type ReactNode } from "react";
import { Sheet, SheetContent, SheetTitle } from "./ui/sheet";
import { cn } from "@/lib/utils";

/** Shared modal side panel: Radix handles focus trapping, Escape and outside click. */
export function SidePanel({
  ariaLabel,
  onClose,
  widthClassName = "w-[32rem]",
  children,
}: {
  ariaLabel: string;
  onClose: () => void;
  widthClassName?: string;
  children: ReactNode;
}) {
  const trigger = useRef(
    document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null,
  );
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent
        aria-describedby={undefined}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          trigger.current?.focus();
        }}
        className={cn(
          "max-w-[90vw] overflow-y-auto bg-card p-6 pt-12 sm:max-w-none",
          widthClassName,
        )}
      >
        <SheetTitle className="sr-only">{ariaLabel}</SheetTitle>
        {children}
      </SheetContent>
    </Sheet>
  );
}
