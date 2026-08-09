/** 快速生成殼按鈕（畫面1）：G12 還沒 grill，先畫殼定位、不接後端（同舊版素材頁「直接
 * 生圖（建置中）」空殼先例，ADR 0008）。純視覺，`disabled` 讓螢幕閱讀器與鍵盤操作都
 * 認得出這兩顆按不下去，不只是外觀變灰。 */
export function QuickGenerateStub() {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)]">
      <h2 className="font-display text-base text-foreground">快速生成</h2>
      <p className="text-xs text-muted-foreground">建置中，之後開放不必進任務就能直接生成。</p>
      <div className="flex gap-3">
        <button
          type="button"
          disabled
          className="flex-1 cursor-not-allowed whitespace-nowrap rounded-md border border-dashed border-border px-4 py-3 text-sm text-muted-foreground/70"
        >
          生一支影片腳本（建置中）
        </button>
        <button
          type="button"
          disabled
          className="flex-1 cursor-not-allowed whitespace-nowrap rounded-md border border-dashed border-border px-4 py-3 text-sm text-muted-foreground/70"
        >
          生一組圖片提示詞（建置中）
        </button>
      </div>
    </div>
  );
}
