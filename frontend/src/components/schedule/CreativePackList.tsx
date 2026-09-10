import { Link } from "react-router-dom";
import { CopyIconButton } from "@/components/layout/CopyIconButton";
import { EmptyState } from "@/components/layout/EmptyState";
import { Skeleton } from "@/components/layout/Skeleton";
import { Badge } from "@/components/layout/ui/badge";
import { LENGTH_HINTS, LENGTH_LABELS } from "@/lib/workbenchApi";
import type { ScheduleBrief } from "@/lib/scheduleApi";

// ADR 0060：這個元件屬於 schedule 這個功能資料夾，不 import 任何
// `frontend/src/components/workbench/` 底下的東西——`LENGTH_HINTS`／`LENGTH_LABELS`
// 從兩邊都能拿的 `lib/workbenchApi.ts` 各自 import 一份（那支檔案的檔頭註解就是為了
// 這個用途寫的），其餘畫面邏輯（字數計算、❌ 行讀法）複製、不 import
// `BriefDetail.tsx`（那支檔案本身也不對外匯出，見 `components/workbench/index.ts`）。

const STATUS_LABELS: Record<string, string> = {
  queued: "處理中", running: "處理中", done: "文案完成", failed: "失敗",
  closed: "已關閉", missing: "尚未建立",
};

function charCount(text: string): number {
  return text.replace(/\n/g, "").length;
}

// app/workbench/jobs.py 把每一項驗證結果拼成 "✅ path：message" / "❌ path：message"
// 存進 body_json.validation（字串陣列，不是物件陣列）——這裡照實際寫回去的形狀讀。
function failLine(validation: string[], path: string): string | null {
  const prefix = `❌ ${path}：`;
  return validation.find((line) => line.startsWith(prefix)) ?? null;
}

function CopyTabs({ copy }: { copy: NonNullable<ScheduleBrief["copy"]> }) {
  const key = copy.copy_length;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3">
        <p className="text-sm font-medium">{LENGTH_LABELS[key]}</p>
        <p className="text-xs text-muted-foreground">{LENGTH_HINTS[key]}</p>
        {copy.bodies.map((text, i) => {
          const fail = failLine(copy.validation, `${key}[${i + 1}]`);
          return (
            <div key={i} className="flex flex-col gap-1 rounded-md border border-border p-3">
              <div className="flex items-start justify-between gap-2">
                <p className="whitespace-pre-wrap text-sm">{text}</p>
                <CopyIconButton ariaLabel={`複製第 ${i + 1} 則`} getText={() => text} />
              </div>
              <span className="numeric text-xs text-muted-foreground">{charCount(text)} 字</span>
              {fail && <p className="text-xs text-danger">{fail}</p>}
            </div>
          );
        })}
      </div>

      {copy.warnings.length > 0 && (
        <div className="flex flex-col gap-1 text-sm text-muted-foreground">
          <span className="text-xs font-medium">模型的提醒</span>
          <ul className="list-disc pl-5">
            {copy.warnings.map((text, i) => (
              <li key={i}>{text}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-col gap-2">
        <span className="text-xs font-medium text-muted-foreground">標題</span>
        {copy.headlines.map((text, i) => (
          <div key={i} className="flex items-center justify-between gap-2 text-sm">
            <span>{text}</span>
            <CopyIconButton ariaLabel={`複製標題 ${i + 1}`} getText={() => text} />
          </div>
        ))}
      </div>
      <div className="flex flex-col gap-2">
        <span className="text-xs font-medium text-muted-foreground">說明</span>
        {copy.descriptions.map((text, i) => (
          <div key={i} className="flex items-center justify-between gap-2 text-sm">
            <span>{text}</span>
            <CopyIconButton ariaLabel={`複製說明 ${i + 1}`} getText={() => text} />
          </div>
        ))}
      </div>
    </div>
  );
}

function CreativePackCard({ brandId, brief }: { brandId: string; brief: ScheduleBrief }) {
  const processing = brief.status === "queued" || brief.status === "running";
  const failed = brief.status === "failed";
  const workbenchHref = brief.brief_id
    ? `/brands/${encodeURIComponent(brandId)}/workbench?brief=${encodeURIComponent(brief.brief_id)}`
    : `/brands/${encodeURIComponent(brandId)}/workbench`;

  return (
    <div className="surface">
      <div className="surface-header">
        <h2>{brief.node_name}</h2>
        <div className="flex items-center gap-2">
          <Badge variant={failed ? "destructive" : "secondary"}>
            {STATUS_LABELS[brief.status] ?? brief.status}
          </Badge>
          {brief.copy?.is_adopted && <Badge variant="secondary">已採用</Badge>}
        </div>
      </div>
      <div className="surface-body flex flex-col gap-4">
        {processing && (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-8 w-64" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        )}
        {failed && (
          <div role="alert" className="flex flex-col gap-2">
            <p className="text-sm text-danger">{brief.last_error ?? "產出失敗。"}</p>
            <Link to={workbenchHref} className="text-sm text-primary underline-offset-4 hover:underline">
              到工作檯再產一輪
            </Link>
          </div>
        )}
        {!processing && !failed && (
          <>
            {brief.copy ? <CopyTabs copy={brief.copy} /> : <p className="text-sm text-muted-foreground">還沒有文案。</p>}
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3 text-sm">
              <span className="text-muted-foreground">
                圖片提示詞：{brief.image_prompts ? `已產第 ${brief.image_prompts.generation_round} 輪` : "尚未產"}
              </span>
              <Link to={workbenchHref} className="text-primary underline-offset-4 hover:underline">
                到工作檯
              </Link>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** 票 05（design-system §5.1 素材準備 stage）：一個最深層節點一張卡——文案在這裡讀、複製；
 * 換版本、重新產一輪、產圖片提示詞都在素材工作檯做（ADR 0068「一個產出者」，這裡不重複那些
 * 控制項）。`briefs` 已經是活動樹的文件順序（`app/schedule/state.py` `_briefs_for_tree`）。 */
export function CreativePackList({ brandId, briefs }: { brandId: string; briefs: ScheduleBrief[] }) {
  if (briefs.length === 0) {
    return (
      <div className="surface">
        <EmptyState title="還沒有素材工單" description="投放結構的每個廣告節點展開成功後，會自動出現在這裡。" />
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-5">
      {briefs.map((brief) => (
        <CreativePackCard key={brief.node_key} brandId={brandId} brief={brief} />
      ))}
    </div>
  );
}
