import { Link } from "react-router-dom";
import type { WorkbenchTask } from "@/lib/workbenchApi";

/** 單張任務卡（畫面1）：來源標籤／檔期名／已生成 N/M 格／已採用 X 則，點卡進矩陣頁
 * （票 16，本票只建路由殼）。 */
export function TaskCard({ brandId, task }: { brandId: string; task: WorkbenchTask }) {
  return (
    <Link
      to={`/brands/${encodeURIComponent(brandId)}/workbench/${encodeURIComponent(task.cycle_id)}`}
      className="flex flex-col gap-2 rounded-lg border border-border bg-card p-5 shadow-[var(--shadow-card)] transition-colors hover:border-primary"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2">
          <span className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">
            {task.source}
          </span>
          <span className="text-sm font-medium text-foreground">{task.cycle_label}</span>
        </span>
        <span className="flex items-center gap-1 text-sm font-medium text-primary">
          繼續處理
          <span aria-hidden="true">→</span>
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        已生成 <span className="tabular-nums">{task.generated_cells}</span>／
        <span className="tabular-nums">{task.total_cells}</span> 格・已採用{" "}
        <span className="tabular-nums">{task.adopted_count}</span> 則
      </p>
    </Link>
  );
}
