import { useEffect, useState, type ReactNode } from "react";
import { Breadcrumb } from "@/components/layout/Breadcrumb";
import { EmptyState } from "@/components/layout/EmptyState";
import { fetchWorkbenchTasks, type WorkbenchTask } from "@/lib/workbenchApi";
import { QuickGenerateStub } from "./QuickGenerateStub";
import { TaskCard } from "./TaskCard";

/** 素材工作檯入口（畫面1，票 15-workbench-entry）：列出上游派來的任務卡＋快速生成殼區。
 * 品牌由路徑參數 `/brands/:brandId/workbench` 決定，比照 CockpitPage 的 LoadState
 * 判別聯集寫法。 */
type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; tasks: WorkbenchTask[] };

export function WorkbenchPage({ brandId }: { brandId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchWorkbenchTasks(brandId)
      .then((tasks) => {
        if (!cancelled) setState({ status: "ready", tasks });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : "讀取失敗，請稍後再試。",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [brandId]);

  let content: ReactNode;
  if (state.status === "loading") {
    content = <EmptyState title="讀取中…" description="正在載入這個品牌的工作檯任務。" />;
  } else if (state.status === "error") {
    content = (
      <EmptyState
        title="讀取失敗"
        description={state.message}
        actionHref={`/brands/${encodeURIComponent(brandId)}`}
        actionInternal
        actionLabel="回品牌駕駛艙"
      />
    );
  } else if (state.tasks.length === 0) {
    content = (
      <EmptyState
        title="目前沒有排程派來的生成任務"
        description="工作檯只顯示其他模組派來的生成任務，不會憑空出現。從廣告模組核准一份計畫後，任務會出現在這裡。"
      />
    );
  } else {
    content = (
      <div className="flex flex-col gap-3">
        {state.tasks.map((task) => (
          <TaskCard key={task.cycle_id} brandId={brandId} task={task} />
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <Breadcrumb items={[{ label: "跨品牌總覽", href: "/" }, { label: "素材工作檯" }]} />
      <div>
        <h1 className="font-display text-2xl text-foreground">素材工作檯</h1>
        <p className="text-sm text-muted-foreground">上游派來的任務</p>
      </div>
      {content}
      <QuickGenerateStub />
    </div>
  );
}
