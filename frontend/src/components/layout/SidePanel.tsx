import { useEffect, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/** 共用側板殼（票 B2-library）：抽自 `workbench/ThemePanel.tsx`／`inbox/PrototypePhasePanel.tsx`
 * 完全重複的覆蓋層＋滑出＋ESC關閉＋進場動畫，兩個既有呼叫端＋品牌智庫本票新增約十個，一次
 * 抽完。只抽「殼」（覆蓋層、抽屜定位、動畫、Escape）——header 內容兩邊本來就不同（ThemePanel
 * 只在讀取成功時顯示 header，PrototypePhasePanel 讀取中／失敗也一直顯示），header 留給呼叫端
 * 自己在 `children` 裡放，抽出前後每個呼叫端的畫面逐像素相同。 */
export function SidePanel({
  ariaLabel,
  onClose,
  widthClassName = "w-[28rem]",
  children,
}: {
  ariaLabel: string;
  onClose: () => void;
  widthClassName?: string;
  children: ReactNode;
}) {
  const [entered, setEntered] = useState(false);

  useEffect(() => {
    const id = requestAnimationFrame(() => setEntered(true));
    return () => cancelAnimationFrame(id);
  }, []);

  useEffect(() => {
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  return (
    <>
      <div
        aria-hidden="true"
        onClick={onClose}
        className={cn(
          "fixed inset-0 z-40 bg-foreground/20 transition-opacity duration-200 ease-out motion-reduce:duration-0 motion-reduce:transition-none",
          entered ? "opacity-100" : "opacity-0",
        )}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        className={cn(
          "fixed inset-y-0 right-0 z-50 flex max-w-full flex-col gap-5 overflow-y-auto",
          widthClassName,
          "border-l border-border bg-card p-6 shadow-[var(--shadow-card)]",
          "transition-[transform,opacity] duration-[220ms] ease-[cubic-bezier(0.23,1,0.32,1)]",
          "motion-reduce:transition-none motion-reduce:duration-0",
          entered ? "translate-x-0 opacity-100" : "translate-x-full opacity-0",
        )}
      >
        {children}
      </div>
    </>
  );
}
