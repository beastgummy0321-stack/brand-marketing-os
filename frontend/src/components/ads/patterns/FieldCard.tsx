import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { Pencil } from "lucide-react";
import { Badge } from "@/components/layout/ui/badge";
import { Button } from "@/components/layout/ui/button";

/** 摘要欄位卡（F04-I07，圖 4「理解如下」）：元件不管編輯狀態，只負責顯示與觸發
 * `onEdit`；`editing` 為 true 時把 `value` 換成呼叫端傳進來的 input（`children`）。 */
export function FieldCard({
  icon: Icon,
  label,
  value,
  emptyText,
  source,
  onEdit,
  editing = false,
  children,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  emptyText: string;
  source: "user" | "system";
  onEdit?: () => void;
  editing?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className="surface flex items-center gap-3 p-4">
      <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent">
        <Icon className="size-4 text-primary" />
      </div>
      <div className="flex-1">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">{label}</span>
          <Badge variant="secondary">{source === "user" ? "你說的" : "系統帶入"}</Badge>
        </div>
        {editing ? children : <p className="text-[15px] font-semibold">{value || emptyText}</p>}
      </div>
      {onEdit && (
        <Button variant="ghost" size="sm" onClick={onEdit}>
          <Pencil />
        </Button>
      )}
    </div>
  );
}
