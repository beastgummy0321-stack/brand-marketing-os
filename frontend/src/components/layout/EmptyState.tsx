import { Link } from "react-router-dom";

/** 共用空狀態卡片（票 02 起沿用，票 03 抽出給駕駛艙頁共用）：讀取中／讀取失敗／
 * 沒有資料都走這一顆，不必每頁各刻一份（規格使用者故事 21：沒資料時要有「這頁幹嘛＋
 * 第一步按鈕」，不是一片空白）。
 *
 * actionHref 可能指向 SPA 內部路徑（票 05-spa-routing 起要用 `Link` 導航，例如
 * 駕駛艙讀取失敗退回總覽）或 SPA 外的舊版 Jinja 頁面（例如總覽沒有品牌時導去舊版
 * 建檔頁）；呼叫端用 `actionInternal` 註明是哪一種，預設外部（一般 `<a>`）。 */
export function EmptyState({
  title,
  description,
  actionHref,
  actionLabel,
  actionInternal = false,
}: {
  title: string;
  description: string;
  actionHref?: string;
  actionLabel?: string;
  actionInternal?: boolean;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-card p-12 text-center shadow-[var(--shadow-card)]">
      <h1 className="font-display text-2xl text-foreground">{title}</h1>
      <p className="max-w-md text-sm text-muted-foreground">{description}</p>
      {actionHref && actionLabel && (
        actionInternal ? (
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
        )
      )}
    </div>
  );
}
