import type { ReactNode } from "react";

/** 設定頁小節卡片外框（票 B1-settings）：六個小節＋規則卡區塊共用同一張卡片樣式，
 * 視覺沿用駕駛艙卡片慣例（border＋shadow-card，見 tokens.css）。 */
export function SectionCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="surface">
      <div className="surface-header !block border-b border-border !pb-5">
        <h2 className="text-base text-foreground">{title}</h2>
        {description && (
          <p className="mt-2 max-w-[var(--width-prose)] text-sm leading-6 text-muted-foreground">{description}</p>
        )}
      </div>
      <div className="surface-body flex flex-col gap-5 !pt-5">{children}</div>
    </section>
  );
}
