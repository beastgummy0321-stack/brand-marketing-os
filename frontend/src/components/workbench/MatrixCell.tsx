import { cn, PRESS_FEEDBACK } from "@/lib/utils";
import { formatUsd } from "@/lib/format";
import type { MatrixFormatCell } from "@/lib/workbenchApi";
import { GlossaryTerm } from "./shared/GlossaryTerm";

/** 已採用／候選標籤：沿用 CampaignStageBadge 的圓角膠囊配色手法，直接借 --color-success
 * token，不新增顏色。側板（票 17）也要用同一顆標籤，故 export。
 * 文字固定用 text-muted-foreground，不套 text-success：text-success 疊在 bg-success/10
 * 上量出來只有 2.95:1，不到一般文字要求的 4.5:1（同票 20 findings，做法同 CopyIconButton
 * 的 iconColor 註解）。
 * 注意：只換文字顏色不夠——bg-success/10 會把文字的實際底色從卡片白變成淡綠，
 * text-muted-foreground 疊在 bg-success/10 上量出來仍只有 4.27:1，沒過 4.5:1（Python 驗算
 * 過，見票說明）。所以連 bg-success/10 一起拿掉，狀態色只留在 border-success/30（非文字，
 * 邊框只需 3:1 且狀態文字本身已用文字重複表達，不算唯一辨識手段），文字底色維持卡片白，
 * 對比穩定在 4.76:1。 */
export function ThemeStatusTag({ status }: { status: string }) {
  const adopted = status === "adopted";
  return (
    <span
      className={cn(
        "shrink-0 rounded-full border px-2 py-0.5 text-xs font-medium text-muted-foreground",
        adopted ? "border-success/30" : "border-border",
      )}
    >
      {adopted ? (
        "已採用"
      ) : (
        /* 「候選」旁的白話詞彙圖示（票 01-glossary-icon，G11 契約）：只做這個字，「已採用」
         * 不需要——persona 實測只點名「候選」看不懂，見 CONTEXT.md「詞彙表機制」節。這顆
         * 標籤側板（ThemePanel）也共用，圖示跟著一起出現在兩處，避免依情境分岔成兩份標籤。 */
        <span className="inline-flex items-center gap-1">
          候選
          <GlossaryTerm termKey="candidate" />
        </span>
      )}
    </span>
  );
}

/** 矩陣單一格（切角 × 格式）：三態之一。
 * - themed：已有主題，逐則列名稱＋狀態標籤（完整內容留給側板，票 17）。
 * - empty：灰卡「＋ 生成主題」，標預估費用，點下去打生成 API；`errorMessage` 有值時
 *   代表上一次生成失敗，顯示在灰卡下方（不是靜默失敗）。
 * - generating：前端自己疊的進行中態（伺服器不會回這個狀態，見 workbenchApi.ts 註解），
 *   有明確文字說明在等什麼，不是空白轉圈（票 29 等待頁誠實化精神）。 */
export function MatrixCell({
  cell,
  isGenerating,
  errorMessage,
  onGenerate,
  onOpenTheme,
}: {
  cell: MatrixFormatCell;
  isGenerating: boolean;
  errorMessage?: string;
  onGenerate: () => void;
  /** 點主題卡開側板（票 17）：不換頁，矩陣頁狀態原地保留。`siblingThemeIds` 是這格（同一
   * 切角＋格式）全部主題的 id，票 19 影片側板要橫向比較同一切角的多支腳本會用到；單圖／
   * 輪播格式忽略這個參數。 */
  onOpenTheme: (themeId: string, siblingThemeIds: string[]) => void;
}) {
  if (isGenerating) {
    return (
      <div className="flex flex-col items-center justify-center gap-1 rounded-lg border border-border bg-card p-3 text-center shadow-[var(--shadow-card)]">
        <p className="text-sm font-medium text-foreground">生成中…</p>
        <p className="text-xs text-muted-foreground">AI 正在寫這則主題，需要一點時間，請耐心等候</p>
      </div>
    );
  }

  if (cell.state === "themed") {
    const siblingThemeIds = cell.themes.map((t) => t.id);
    return (
      <div className="flex flex-col gap-1.5">
        {cell.themes.map((theme) => (
          // 票 01-glossary-icon：這排原本是 <button>，但「候選」徽章旁現在多了個 GlossaryTerm
          // 的「?」按鈕——<button> 內不得再放互動元素（HTML content model 禁止、螢幕閱讀器也
          // 不吃這套嵌套），改用 role="button"＋tabIndex 手動補鍵盤啟用，語意等價於原本的
          // <button>。
          <div
            key={theme.id}
            role="button"
            tabIndex={0}
            onClick={() => onOpenTheme(theme.id, siblingThemeIds)}
            onKeyDown={(event) => {
              if (event.key !== "Enter" && event.key !== " ") return;
              event.preventDefault();
              onOpenTheme(theme.id, siblingThemeIds);
            }}
            className={cn(
              "flex w-full cursor-pointer items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 py-2 text-left shadow-[var(--shadow-card)] hover:border-primary",
              PRESS_FEEDBACK,
            )}
          >
            <span className="truncate text-sm text-foreground" title={theme.name}>
              {theme.name}
            </span>
            <ThemeStatusTag status={theme.status} />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      <button
        type="button"
        onClick={onGenerate}
        className={cn(
          "flex flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-border bg-card p-3 text-center text-sm text-muted-foreground shadow-[var(--shadow-card)] hover:border-primary hover:text-primary",
          PRESS_FEEDBACK,
        )}
      >
        <span>＋ 生成主題</span>
        <span className="tabular-nums text-xs">預估 {formatUsd(cell.estimated_cost)}</span>
      </button>
      {errorMessage && <p className="text-xs text-danger">{errorMessage}</p>}
    </div>
  );
}
