import { cn } from "@/lib/utils";
import type { ComplianceHit } from "@/lib/workbenchApi";

/** 生成當下即掃的法務／品牌命中標記（票 S1-01：scan-on-generate）：一則命中一顆徽章，
 * 徽章上只顯示命中的短字（`term`），完整說明句（`message`）當 title tooltip，滑鼠停留
 * 或螢幕閱讀器都讀得到，不必把整句塞進畫面。
 *
 * `category === "law" || "unbacked_claim"` 用既有 danger token（可能違法或編造規格／交易
 * 條件，後果比品牌自己的偏好重）；`category === "brand"` 沿用既有相似度徽章的 warning
 * token（ComponentSection.tsx 既有的 `相似度偏高` 徽章），不新增顏色。
 *
 * `hits` 可能是 `undefined`——`adoptTheme()`／`rejectComponent()` 兩支路由沒有重新掃描，
 * 回應不帶 `compliance_hits`（見 workbenchApi.ts ThemeComponentData 註解），這裡當空清單
 * 處理，不假設呼叫端一定先過濾過。 */
export function ComplianceBadges({ hits }: { hits: ComplianceHit[] | undefined }) {
  const list = hits ?? [];
  if (list.length === 0) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {list.map((hit, index) => (
        <span
          key={index}
          title={hit.message}
          className={cn(
            "inline-block rounded-full border px-2 py-0.5 text-xs font-medium",
            hit.category === "brand"
              ? "border-warning/30 bg-warning/10 text-warning"
              : "border-danger/30 bg-danger/10 text-danger",
          )}
        >
          {hit.term}
        </span>
      ))}
    </div>
  );
}

/** 一批命中裡有沒有法規／查無佐證類（`law`／`unbacked_claim`）——`ComponentRow` 用來決定
 * 整列要不要套跟 `similar` 同一種 danger 邊框樣式（票面「A row with a law-category hit
 * also gets the destructive border/background」）。 */
export function hasDangerHit(hits: ComplianceHit[] | undefined): boolean {
  return (hits ?? []).some((hit) => hit.category === "law" || hit.category === "unbacked_claim");
}
