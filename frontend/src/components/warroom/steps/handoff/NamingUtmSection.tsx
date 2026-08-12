import { useEffect, useState } from "react";
import { fetchNamingCheck, type NamingCheckResult, type UtmCheckResult } from "@/lib/warroomApi";
import { Badge } from "../../shared/Badge";

/** 命名與 UTM 檢查（S8.28-30，新設計，廣告強化第 3 項）：純函數比對，不擋流程，通不過只顯示
 * 提示。UTM 官方標準第 5 個經典參數 `utm_term`（來源：Google Analytics 官方說明
 * support.google.com/analytics/answer/10917952，查證日 2026-08-12）本系統刻意不使用——
 * Meta 是興趣／受眾投放不是關鍵字搜尋廣告，顯示「不適用」而非「缺漏」。 */
export function NamingUtmSection({ brandId, cycleId }: { brandId: string; cycleId: string }) {
  const [data, setData] = useState<{ naming: NamingCheckResult; utm: UtmCheckResult[] } | null>(null);

  useEffect(() => {
    fetchNamingCheck(brandId, cycleId).then(setData);
  }, [brandId, cycleId]);

  if (!data) return null;
  if (data.utm.length === 0) return null; // 交接包還沒產生，沒有東西可檢查

  return (
    <div id="naming-utm-block" className="flex flex-wrap items-center gap-2 rounded-md border border-border p-3 text-sm">
      <Badge tone={data.naming.passed ? "success" : "danger"}>命名檢查：{data.naming.passed ? "通過" : "未過"}</Badge>
      {!data.naming.passed && (
        <span className="text-xs text-muted-foreground">
          {data.naming.duplicates.map((d) => `「${d.value}」重複`).join("、")}
          {data.naming.duplicates.length > 0 && "。這是系統自動產生的命名，一般不會發生，如發生請回報。"}
        </span>
      )}
      <Badge tone={data.utm.every((u) => u.passed) ? "success" : "warning"}>
        UTM 檢查：{data.utm.every((u) => u.passed) ? "全部齊全" : `${data.utm.filter((u) => !u.passed).length} 組缺漏`}
      </Badge>
      <span className="text-xs text-muted-foreground">utm_term：不適用（非搜尋型廣告）</span>
    </div>
  );
}
