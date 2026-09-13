export interface TimelineItem {
  id: string;
  time: string;
  title: string;
  detail?: string;
}

/** 時間軸（F04-I07）：每一筆的文字都是後端給的字串，元件不拼、不翻譯 kind。 */
export function ActionTimeline({ items, emptyText }: { items: TimelineItem[]; emptyText: string }) {
  if (items.length === 0) {
    return <p className="py-6 text-center text-sm text-muted-foreground">{emptyText}</p>;
  }

  return (
    <div className="relative flex flex-col gap-4 pl-4">
      <div className="absolute top-1 bottom-1 left-[3px] w-px bg-border" />
      {items.map((item) => (
        <div key={item.id} className="relative">
          <div className="absolute top-1.5 left-[-13px] size-[7px] rounded-full bg-primary" />
          <p className="text-xs text-muted-foreground">{item.time}</p>
          <p className="text-sm font-semibold">{item.title}</p>
          {item.detail && <p className="text-xs text-muted-foreground">{item.detail}</p>}
        </div>
      ))}
    </div>
  );
}
