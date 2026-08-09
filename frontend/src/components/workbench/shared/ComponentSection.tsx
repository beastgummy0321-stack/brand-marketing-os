import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { rejectComponent, type ThemeComponentData } from "@/lib/workbenchApi";
import { CopyIconButton } from "./CopyIconButton";
import { FoldedText } from "./FoldedText";
import { RejectReasonPicker } from "./RejectReasonPicker";

/** 文案列表元件（票 17 共用元件，抽出獨立檔給票 18 輪播的廣告層 5 則文案直接重用，
 * 不重做——見票 18 AC「廣告層文案 UI 沿用票 17 的文案列表元件」）：標題列＋逐則列，
 * 每則帶純圖示複製鈕＋退件選單，超字元件顯示折疊線，相似度偏高標黃。 */
export function ComponentSection({
  title,
  components,
  charBudget,
  headerExtra,
  brandId,
  cycleId,
  onComponentUpdated,
}: {
  title: string;
  components: ThemeComponentData[];
  /** null＝這個型別沒有字數預算（圖片提示詞），不套折疊線。 */
  charBudget: number | null;
  headerExtra?: ReactNode;
  brandId: string;
  cycleId: string;
  onComponentUpdated: (updated: ThemeComponentData) => void;
}) {
  if (components.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">
          {title}（{components.length}）
        </h3>
        {headerExtra}
      </div>
      <div className="flex flex-col gap-2">
        {components.map((component) => (
          <ComponentRow
            key={component.id}
            component={component}
            charBudget={charBudget}
            brandId={brandId}
            cycleId={cycleId}
            onComponentUpdated={onComponentUpdated}
          />
        ))}
      </div>
    </div>
  );
}

/** 單則元件列：純內容複製＋退件選單＋超字折疊線＋相似度標黃。`fieldLabel` 選填──輪播卡片
 * （票 18）同一張卡塞了圖片提示詞／卡標題／卡說明三種欄位，需要一個小標籤分清楚是哪一欄；
 * 單圖／廣告層文案不需要，維持原樣不傳即可。 */
export function ComponentRow({
  component,
  charBudget,
  brandId,
  cycleId,
  onComponentUpdated,
  fieldLabel,
}: {
  component: ThemeComponentData;
  charBudget: number | null;
  brandId: string;
  cycleId: string;
  onComponentUpdated: (updated: ThemeComponentData) => void;
  fieldLabel?: string;
}) {
  // sqlite INTEGER 0/1，不是 JS boolean（workbenchApi.ts ThemeComponentData 註解）。
  const similar = !!component.similarity_flag;
  const overBudget = !!component.over_budget;

  return (
    <div
      className={cn(
        "flex items-start gap-2 rounded-md border border-border px-3 py-2",
        similar && "border-warning/30 bg-warning/10",
      )}
    >
      <div className="min-w-0 flex-1">
        {fieldLabel && (
          <p className="mb-0.5 text-xs font-medium text-muted-foreground">{fieldLabel}</p>
        )}
        {overBudget && charBudget !== null ? (
          <FoldedText content={component.content} charBudget={charBudget} />
        ) : (
          <p className="text-sm text-foreground">{component.content}</p>
        )}
        {similar && (
          <span className="mt-1 inline-block rounded-full border border-warning/30 bg-warning/10 px-2 py-0.5 text-xs font-medium text-warning">
            相似度偏高
          </span>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <CopyIconButton ariaLabel="複製這則" getText={() => component.content} />
        {component.rejected ? (
          <span
            className="whitespace-nowrap rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground"
            title={component.reject_reason_label ?? undefined}
          >
            已退件
          </span>
        ) : (
          <RejectReasonPicker
            onReject={async (reasonCode) => {
              const updated = await rejectComponent(brandId, cycleId, component.id, reasonCode);
              onComponentUpdated(updated);
            }}
          />
        )}
      </div>
    </div>
  );
}
