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
    <section className="flex flex-col gap-4 rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)]">
      <div className="flex flex-col gap-1">
        <h2 className="font-display text-base text-foreground">{title}</h2>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  );
}
