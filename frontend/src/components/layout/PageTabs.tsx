import type { ReactNode } from "react";
export function PageTabs<T extends string>({
  items,
  value,
  onChange,
  label = "頁面分頁",
}: {
  items: { value: T; label: string; count?: number; icon?: ReactNode }[];
  value: T;
  onChange: (value: T) => void;
  label?: string;
}) {
  return (
    <div className="page-tabs" role="group" aria-label={label}>
      {items.map((item) => (
        <button
          type="button"
          key={item.value}
          className="page-tab"
          aria-pressed={value === item.value}
          onClick={() => onChange(item.value)}
        >
          {item.icon}
          {item.label}
          {item.count !== undefined && (
            <span className="rounded bg-muted px-1.5 text-xs numeric">
              {item.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
