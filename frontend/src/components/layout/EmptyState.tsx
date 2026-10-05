import { Link } from "react-router-dom";
import { Button } from "./ui/button";

/** 共用空狀態卡片（票 02 起沿用，票 03 抽出給駕駛艙頁共用）：讀取中／讀取失敗／
 * 沒有資料都走這一顆，不必每頁各刻一份（規格使用者故事 21：沒資料時要有「這頁幹嘛＋
 * 第一步按鈕」，不是一片空白）。
 *
 * actionHref 可能指向 SPA 內部路徑（票 05-spa-routing 起要用 `Link` 導航，例如
 * 駕駛艙讀取失敗退回總覽）或 SPA 外的舊版 Jinja 頁面（例如總覽沒有品牌時導去舊版
 * 建檔頁）；呼叫端用 `actionInternal` 註明是哪一種，預設外部（一般 `<a>`）。
 *
 * `onAction`（票 B1-inbox／B1-settings）：失敗態要「重新載入」同一份資料，不是導去
 * 別頁——這種情境傳 `onAction` 代替 `actionHref`，按鈕改觸發回呼而非導航。兩者互斥，
 * `onAction` 優先於 `actionHref`。
 *
 * F51 Contract D: the `onAction` button is a `Button` — `actionBusy` while the action it started runs (no
 * sentence; the label says 產生中…), `actionDisabledReason` when it cannot run (printed under it).
 * `actionDisabled` is deprecated (F51-I13 removes it once its callers pass one of the two). */
export function EmptyState({
  title,
  description,
  actionHref,
  actionLabel,
  actionInternal = false,
  actionDisabled = false,
  actionBusy = false,
  actionDisabledReason,
  onAction,
}: {
  title: string;
  description: string;
  actionHref?: string;
  actionLabel?: string;
  actionInternal?: boolean;
  /** @deprecated pass `actionBusy` or `actionDisabledReason` (F51 Contract D). */
  actionDisabled?: boolean;
  actionBusy?: boolean;
  actionDisabledReason?: string | null;
  onAction?: () => void;
}) {
  return (
    <div className="empty-state surface gap-3">
      <h2 className="text-lg text-foreground">{title}</h2>
      <p className="max-w-md text-sm text-muted-foreground">{description}</p>
      {actionLabel && onAction ? (
        <Button
          type="button"
          onClick={onAction}
          busy={actionBusy}
          disabledReason={actionDisabledReason}
          disabled={actionDisabled} // DISABLED_OK: forwards the deprecated prop until F51-I13 removes it
          className="mt-2"
        >
          {actionLabel}
        </Button>
      ) : (
        actionHref &&
        actionLabel &&
        (actionInternal ? (
          <Link
            to={actionHref}
            className="mt-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
          >
            {actionLabel}
          </Link>
        ) : (
          <a
            href={actionHref}
            className="mt-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
          >
            {actionLabel}
          </a>
        ))
      )}
    </div>
  );
}
