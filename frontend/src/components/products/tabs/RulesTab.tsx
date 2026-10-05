import { Link } from "react-router-dom";
import { EmptyState } from "@/components/layout/EmptyState";
import type { ProductRule } from "@/lib/productsApi";
import { Badge } from "../shared/Badge";

/** 適用規則分頁（唯讀，契約 S6.36–S6.37）：品牌層規則＋本產品專屬規則合併顯示，
 * 品牌層規則只能到品牌智庫（S5）改，這裡不開編輯入口。 */
export function RulesTab({ brandId, productId, rules }: { brandId: string; productId: string; rules: ProductRule[] }) {
  return (
    <div className="flex flex-col gap-4">
      <h2 className="font-display text-lg text-foreground">適用規則</h2>

      {rules.length === 0 ? (
        <EmptyState
          title="這個產品沒有專屬的規則"
          description="品牌層的規則仍然適用。"
          actionHref={`/brands/${brandId}/library?tab=rules`}
          actionLabel="到品牌智庫新增"

        />
      ) : (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-left text-sm">
            <thead className="bg-muted text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">嚴重度</th>
                <th className="px-3 py-2 font-medium">類型</th>
                <th className="px-3 py-2 font-medium">內容</th>
                <th className="px-3 py-2 font-medium">來源</th>
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <tr key={rule.id} className="border-t border-border align-top">
                  <td className="whitespace-nowrap px-3 py-2">
                    <Badge tone={rule.severity === "hard" ? "danger" : "neutral"}>
                      {rule.severity === "hard" ? "必須遵守" : "建議遵守"}
                    </Badge>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <Badge>{rule.rule_type_label}</Badge>
                  </td>
                  <td className="px-3 py-2 text-foreground">{rule.content}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                    {rule.product_id === productId ? (
                      "本產品專屬"
                    ) : (
                      <>
                        來自品牌設定
                        <span aria-hidden="true"> ・ </span>
                        <Link to={`/brands/${brandId}/library?tab=rules`} className="text-primary hover:underline">
                          到品牌智庫修改
                        </Link>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
