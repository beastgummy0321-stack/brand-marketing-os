import { useEffect } from "react";

const checked = new WeakSet<Event>();
/** Guard ordinary links, workspace tabs and closing/reloading a tab while local text exists. */
export function useAssetDraftGuard(dirty: boolean, message = "仍有未儲存的素材文案或選檔。離開將放棄這些本機編輯；已保存的原檔與安排會保留。確定離開？") {
  useEffect(() => {
    if (!dirty) return;
    const unload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    const navigate = (e: MouseEvent) => {
      if (checked.has(e) || !(e.target instanceof Element)) return;
      const target = e.target.closest("a[href]:not([download]), .page-tab");
      if (!target || target.getAttribute("target") === "_blank" || target.getAttribute("aria-pressed") === "true") return;
      checked.add(e);
      if (!window.confirm(message)) { e.preventDefault(); e.stopPropagation(); }
    };
    window.addEventListener("beforeunload", unload); document.addEventListener("click", navigate, true);
    return () => { window.removeEventListener("beforeunload", unload); document.removeEventListener("click", navigate, true); };
  }, [dirty, message]);
}
