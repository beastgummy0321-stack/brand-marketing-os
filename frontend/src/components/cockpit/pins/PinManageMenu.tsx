import { useRef, useState } from "react";
import { useEffect } from "react";
import { PINNED_VIEW_LIMIT, type PinnedViewCatalogItem, type PinnedViewKey } from "@/lib/pinnedViewsApi";

/** S3P.2-4：chips 尾端「管理視圖」下拉選單——目錄全部項目＋checkbox，勾滿上限時其餘
 * disabled，勾選即刻送出（不用「儲存」按鈕，鐵則④即時回饋）。純前端下拉，不裝額外的
 * popover 套件（原生 `position` + 點外面關閉即可，ladder 第四階）。 */
export function PinManageMenu({
  catalog,
  pinned,
  savingKey,
  errorByKey,
  onToggle,
}: {
  catalog: PinnedViewCatalogItem[];
  pinned: PinnedViewKey[];
  savingKey: PinnedViewKey | null;
  errorByKey: Partial<Record<PinnedViewKey, string>>;
  onToggle: (key: PinnedViewKey) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const atLimit = pinned.length >= PINNED_VIEW_LIMIT;

  useEffect(() => {
    if (!open) return;
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="rounded-full border border-border px-3 py-1 text-xs font-medium text-muted-foreground hover:border-primary hover:text-primary"
      >
        管理視圖
      </button>
      {open && (
        <div className="absolute right-0 top-full z-20 mt-2 w-72 rounded-[var(--radius-xl)] border border-border bg-card p-3 shadow-[var(--shadow-card-hover)]">
          <ul className="flex flex-col gap-1.5">
            {catalog.map((item) => {
              const checked = pinned.includes(item.key);
              const disabled = savingKey === item.key || (atLimit && !checked);
              return (
                <li key={item.key}>
                  <label
                    className={
                      "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm " +
                      (disabled ? "cursor-not-allowed text-muted-foreground/60" : "cursor-pointer text-foreground hover:bg-muted")
                    }
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={disabled}
                      onChange={() => onToggle(item.key)}
                      className="h-4 w-4 rounded border-border"
                    />
                    {item.label}
                    {savingKey === item.key && <span className="ml-auto text-xs text-muted-foreground">送出中…</span>}
                  </label>
                  {errorByKey[item.key] && <p className="px-2 text-xs text-danger">{errorByKey[item.key]}</p>}
                </li>
              );
            })}
          </ul>
          {atLimit && (
            <p className="mt-2 border-t border-border pt-2 text-xs text-muted-foreground">
              已釘選 {PINNED_VIEW_LIMIT} 個上限，先取消一個才能再選
            </p>
          )}
        </div>
      )}
    </div>
  );
}
