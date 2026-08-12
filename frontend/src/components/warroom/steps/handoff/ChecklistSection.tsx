import { useEffect, useState } from "react";
import { fetchChecklist, toggleChecklistItem, type ChecklistItem } from "@/lib/warroomApi";
import { Badge } from "../../shared/Badge";

/** 投放前檢查清單（S8.25-27，吸收 `ads_checklist.html`）：一次性（品牌層）＋每期必看兩類，
 * 兩類都不擋流程——完不完成不影響階段判讀，只是完成度供交接包顯示。 */
export function ChecklistSection({ brandId, cycleId }: { brandId: string; cycleId: string }) {
  const [items, setItems] = useState<ChecklistItem[] | null>(null);

  function load() {
    fetchChecklist(brandId, cycleId).then(setItems);
  }
  useEffect(load, [brandId, cycleId]);

  async function toggle(item: ChecklistItem, scope: "one-time" | "cycle") {
    await toggleChecklistItem(brandId, cycleId, scope, item.key);
    load();
  }

  if (!items) return <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">讀取中…</div>;

  const oneTime = items.slice(0, 1);
  const cycleItems = items.slice(1);
  const doneCount = items.filter((i) => i.checked).length;

  return (
    <div className="rounded-lg border border-border bg-card p-4 shadow-[var(--shadow-card)]">
      <div className="flex items-center justify-between">
        <p className="font-medium text-foreground">投放前檢查清單</p>
        <Badge tone={doneCount === items.length ? "success" : "neutral"}>{doneCount}／{items.length}</Badge>
      </div>
      <ul className="mt-2 flex flex-col gap-2 text-sm">
        {oneTime.map((item) => (
          <li key={item.key} className="flex items-start gap-2">
            <input type="checkbox" checked={item.checked} onChange={() => void toggle(item, "one-time")} className="mt-0.5" />
            <span>
              {item.label}（品牌層，跨檔期共用）
              {item.flagged && <span className="ml-1"><Badge tone="warning">{item.flagged_reason ?? "異常訊號"}</Badge></span>}
              <span className="block text-xs text-muted-foreground">{item.help}</span>
            </span>
          </li>
        ))}
        {cycleItems.map((item) => (
          <li key={item.key} className="flex items-start gap-2">
            <input type="checkbox" checked={item.checked} onChange={() => void toggle(item, "cycle")} className="mt-0.5" />
            <span>
              {item.label}
              {item.hint && <span className="ml-1"><Badge tone="warning">{item.hint}</Badge></span>}
              <span className="block text-xs text-muted-foreground">{item.help}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
