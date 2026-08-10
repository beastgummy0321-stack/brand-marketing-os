import { useEffect, useId, useRef, useState, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";
import { GLOSSARY } from "@/lib/glossary";

/** 詞彙旁「?」小圖示（票 01-glossary-icon，G11 契約）：點擊開/關白話解釋 popover，點別處
 * 自動關閉——toggle／click-outside 沿用 `RejectReasonPicker` 的 pointerdown+ref 判斷模式
 * （repo 裡已經有，不重寫一份）。
 *
 * 跟 `RejectReasonPicker` 的差別：popover 用 `createPortal` 掛到 `document.body`，用
 * `position:fixed` ＋ `getBoundingClientRect` 算座標，不用 `absolute`。原因：這顆會被放進
 * `MatrixPage.tsx` 的 `overflow-x-auto` 格線容器、`ThemePanel.tsx` 的 `overflow-y-auto`
 * 側板——CSS 規格規定「只設 overflow-x 或只設 overflow-y」時，另一軸的計算值會連動變成
 * `auto`（不是 `visible`），兩層容器因此都會裁切 `absolute` 定位的子元素，跟契約 G11 驗收
 * 清單第 5 條、原型測出的 popover 被裁切是同一種坑。`fixed` 相對視窗定位，不受任何祖先
 * `overflow` 影響，一次解掉全部呼叫點，不必每個呼叫點各自判斷要不要 portal。
 *
 * `termKey` 刻意收 `string`（不是字典 key 的聯合型別）：查無詞條時要顯示備援訊息、不留白
 * 不報錯（AC），型別若鎖死成已註冊的 key，這條防呆永遠走不到，等於沒做。
 *
 * ponytail: popover 開著時捲動視窗不會跟著按鈕移動（沒接 scroll 監聽重算座標）——
 * click 開、click-outside 關的短暫互動，先不做；要邊捲邊跟著走再加 scroll 監聽。
 *
 * 這顆「?」按鈕可能被放進矩陣格的主題卡（MatrixCell.tsx，整排本身也可點）裡，click 要
 * `stopPropagation`，否則點「?」會連帶觸發外層卡片的 onClick、把側板一起打開——跟這顆
 * 圖示「只開白話解釋」的行為對不上。 */
export function GlossaryTerm({ termKey }: { termKey: string }) {
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const popoverId = useId();
  const entry = GLOSSARY[termKey];

  useEffect(() => {
    if (!open) return;
    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node;
      if (btnRef.current?.contains(target) || popoverRef.current?.contains(target)) return;
      setOpen(false);
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  function toggle(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation();
    if (!open && btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect();
      setCoords({ top: rect.bottom + 4, left: rect.left });
    }
    setOpen((v) => !v);
  }

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={toggle}
        onKeyDown={(event) => {
          // Enter／空白鍵原生就會讓瀏覽器對這顆 <button> 補發 click（走 toggle 的
          // stopPropagation），但 keydown 本身仍會往上冒泡——外層若是矩陣卡片那顆
          // role="button" 的整排（也監聽 Enter／空白鍵），沒攔住的話按鍵盤一樣會誤觸卡片。
          // Escape 不擋，讓它照樣冒泡到 document 的關閉監聽。
          if (event.key === "Enter" || event.key === " ") event.stopPropagation();
        }}
        aria-expanded={open}
        aria-controls={open ? popoverId : undefined}
        aria-label={`${entry?.term ?? termKey}是什麼`}
        className={cn(
          "inline-flex h-[1.15rem] w-[1.15rem] shrink-0 items-center justify-center rounded-full border text-[0.68rem] font-bold leading-none",
          open
            ? "border-primary bg-primary text-primary-foreground"
            : "border-border text-muted-foreground hover:border-primary hover:text-primary",
        )}
      >
        ?
      </button>
      {open &&
        coords &&
        createPortal(
          <div
            ref={popoverRef}
            id={popoverId}
            role="tooltip"
            style={{ position: "fixed", top: coords.top, left: coords.left }}
            className={cn(
              "z-50 w-64 rounded-md border border-border bg-card p-3 text-sm shadow-[var(--shadow-card)]",
              entry ? "text-secondary" : "text-danger",
            )}
          >
            <span className="mb-1 block font-semibold text-foreground">
              {entry?.term ?? "這個詞還沒有說明"}
            </span>
            {entry?.text ?? "之後補上就會顯示在這裡。"}
          </div>,
          document.body,
        )}
    </>
  );
}
