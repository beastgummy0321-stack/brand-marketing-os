import type { GuideCard } from "@/lib/api";

/** 駕駛艙常駐下一步指南卡（票 04-guide-card-engine）：最多 3 件，各附一鍵前往；
 * 沒有待辦顯示「一切正常」（規格使用者故事 10）。 */
export function GuideCards({ cards }: { cards: GuideCard[] }) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)]">
      <h2 className="font-display text-base text-foreground">下一步指南</h2>
      {cards.length === 0 ? (
        <p className="text-sm text-muted-foreground">一切正常，目前沒有待辦事項。</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {cards.map((card) => (
            <li key={card.action_url}>
              <a
                href={card.action_url}
                className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm text-foreground transition-colors hover:border-primary hover:text-primary"
              >
                {card.title}
                <span aria-hidden="true">→</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
