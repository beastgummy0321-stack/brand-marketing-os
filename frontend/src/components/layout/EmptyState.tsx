/** 共用空狀態卡片（票 02 起沿用，票 03 抽出給駕駛艙頁共用）：讀取中／讀取失敗／
 * 沒有資料都走這一顆，不必每頁各刻一份（規格使用者故事 21：沒資料時要有「這頁幹嘛＋
 * 第一步按鈕」，不是一片空白）。 */
export function EmptyState({
  title,
  description,
  actionHref,
  actionLabel,
}: {
  title: string;
  description: string;
  actionHref?: string;
  actionLabel?: string;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-card p-12 text-center shadow-[var(--shadow-card)]">
      <h1 className="font-display text-2xl text-foreground">{title}</h1>
      <p className="max-w-md text-sm text-muted-foreground">{description}</p>
      {actionHref && actionLabel && (
        <a
          href={actionHref}
          className="mt-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          {actionLabel}
        </a>
      )}
    </div>
  );
}
