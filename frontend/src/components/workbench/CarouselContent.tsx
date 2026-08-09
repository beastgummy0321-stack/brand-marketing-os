import {
  CAROUSEL_CHAR_BUDGETS,
  NARRATIVE_TYPE_LABELS,
  type ThemeComponentData,
} from "@/lib/workbenchApi";
import { ComponentRow, ComponentSection } from "./shared/ComponentSection";

/** 一張卡固定讀的三～四個欄位，順序也是顯示順序：圖片提示詞 → 卡標題 → 卡說明 →
 * 商品連結（只有多商品型才有這個元件型別，見 app/creative/theme_engine.py
 * normalize_carousel()）。用固定陣列而不是依賴後端回傳順序或物件鍵序（同 ThemePanel.tsx
 * SingleImageContent 的既有原則）。 */
const CARD_FIELD_ORDER = ["card_image_prompt", "card_title", "card_description", "card_product_link"];

const CARD_FIELD_LABELS: Record<string, string> = {
  card_image_prompt: "圖片提示詞",
  card_title: "卡標題",
  card_description: "卡說明",
  card_product_link: "商品連結",
};

/** 輪播主題內容（畫面 4，票 18-panel-carousel）：敘事骨架標記＋有序卡片序列（各卡圖片
 * 提示詞＋卡標題＋卡說明，各自複製／退件）＋廣告層 5 則主要文案（全卡共用）。重用票 17
 * 的側板殼（ThemePanel）與共用元件（CopyIconButton／RejectReasonPicker／FoldedText／
 * ComponentSection、ComponentRow）——退件與複製走跟單圖一模一樣的 ComponentRow 呼叫，
 * 不分叉出第二套邏輯（AC「退件行為與票 17 完全一致」）。本檔只管輪播特有的「依 sequence
 * 分組成卡＋卡與卡之間看得出順序」版面。 */
export function CarouselContent({
  brandId,
  cycleId,
  components,
  onComponentUpdated,
}: {
  brandId: string;
  cycleId: string;
  components: ThemeComponentData[];
  onComponentUpdated: (updated: ThemeComponentData) => void;
}) {
  const narrativeType =
    components.find((c) => c.component_type === "narrative_type")?.content ?? null;
  const bodies = components.filter((c) => c.component_type === "body");

  const cardsBySequence = new Map<number, ThemeComponentData[]>();
  for (const component of components) {
    if (component.sequence === null || !CARD_FIELD_ORDER.includes(component.component_type)) {
      continue;
    }
    const fields = cardsBySequence.get(component.sequence) ?? [];
    fields.push(component);
    cardsBySequence.set(component.sequence, fields);
  }
  const sequences = [...cardsBySequence.keys()].sort((a, b) => a - b);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-foreground">
            卡片序列（{sequences.length}）
          </h3>
          {narrativeType && (
            <span className="rounded-full border border-border px-2 py-0.5 text-xs font-medium text-muted-foreground">
              {NARRATIVE_TYPE_LABELS[narrativeType] ?? narrativeType}・{sequences.length} 卡
            </span>
          )}
        </div>
        <div className="flex flex-col">
          {sequences.map((sequence, index) => {
            const fields = (cardsBySequence.get(sequence) ?? []).slice().sort(
              (a, b) =>
                CARD_FIELD_ORDER.indexOf(a.component_type) -
                CARD_FIELD_ORDER.indexOf(b.component_type),
            );
            return (
              <div key={sequence} className="flex gap-3">
                {/* 順序關係：編號圓點＋往下的連接線（非裝飾性數字浮水印），跟下一張卡的圓點
                    銜接，讀出來是「這是一串有先後關係的卡」。編號本身不隱藏給螢幕閱讀器──
                    連接線沒有文字內容，天然不會被念出來。 */}
                <div className="flex flex-col items-center">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-border bg-muted text-xs font-semibold tabular-nums text-foreground">
                    {sequence}
                  </span>
                  {index < sequences.length - 1 && (
                    <span aria-hidden="true" className="my-1 w-px flex-1 bg-border" />
                  )}
                </div>
                <div className="flex flex-1 flex-col gap-2 pb-4">
                  {fields.map((component) => (
                    <ComponentRow
                      key={component.id}
                      component={component}
                      charBudget={CAROUSEL_CHAR_BUDGETS[component.component_type] ?? null}
                      brandId={brandId}
                      cycleId={cycleId}
                      onComponentUpdated={onComponentUpdated}
                      fieldLabel={CARD_FIELD_LABELS[component.component_type]}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <ComponentSection
        title="主要文案"
        components={bodies}
        charBudget={CAROUSEL_CHAR_BUDGETS.body}
        brandId={brandId}
        cycleId={cycleId}
        onComponentUpdated={onComponentUpdated}
      />
    </div>
  );
}
