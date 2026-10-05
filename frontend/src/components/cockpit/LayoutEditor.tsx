import { ArrowDown, ArrowUp, RotateCcw } from "lucide-react";
import { SidePanel } from "@/components/layout/SidePanel";
import { Button } from "@/components/layout/ui/button";
import { Input } from "@/components/layout/ui/input";
import {
  METRICS,
  WIDGETS,
  reorderWidgets,
  type DashboardView,
} from "@/lib/dashboardLayout";
export const metricLabels = {
  spend: "廣告花費",
  impressions: "曝光次數",
  clicks: "點擊次數",
  ctr: "點擊率",
  roas: "Meta ROAS",
};
export const widgetLabels = {
  spend: "活動花費分布",
  performance: "素材成效比較",
  campaigns: "活動概況",
  inbox: "待處理",
  commerce: "本月營收與毛利",
};
export function LayoutEditor({
  view,
  onChange,
  onClose,
  onReset,
  onDelete,
  canDelete,
}: {
  view: DashboardView;
  onChange: (view: DashboardView) => void;
  onClose: () => void;
  onReset: () => void;
  onDelete: () => void;
  canDelete: boolean;
}) {
  const empty = view.metrics.length + view.widgets.length <= 1;
  return (
    <SidePanel ariaLabel="自訂看板版面" onClose={onClose}>
      <div>
        <h2 className="text-xl">自訂版面</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          變更會立即套用，儲存在此瀏覽器的目前帳號、組織與品牌。
        </p>
      </div>
      <label className="grid gap-2 text-sm font-medium">
        檢視名稱
        <Input
          maxLength={24}
          value={view.name}
          onChange={(e) => onChange({ ...view, name: e.target.value })}
          onBlur={() => {
            if (!view.name.trim()) onChange({ ...view, name: "自訂檢視" });
          }}
        />
      </label>
      <fieldset className="grid gap-3">
        <legend className="mb-3 font-semibold">關鍵指標</legend>
        {METRICS.map((id) => (
          <label key={id} className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={view.metrics.includes(id)}
              disabled={empty && view.metrics.includes(id)}
              onChange={(e) =>
                onChange({
                  ...view,
                  metrics: e.target.checked
                    ? METRICS.filter(
                        (m) => view.metrics.includes(m) || m === id,
                      )
                    : view.metrics.filter((m) => m !== id),
                })
              }
            />
            {metricLabels[id]}
          </label>
        ))}
      </fieldset>
      <fieldset className="grid gap-3 border-t border-border pt-5">
        <legend className="pr-2 font-semibold">看板區塊</legend>
        {WIDGETS.map((id) => (
          <label key={id} className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={view.widgets.some((w) => w.id === id)}
              disabled={empty && view.widgets.some((w) => w.id === id)}
              onChange={(e) =>
                onChange({
                  ...view,
                  widgets: e.target.checked
                    ? [...view.widgets, { id, width: "half" }]
                    : view.widgets.filter((w) => w.id !== id),
                })
              }
            />
            {widgetLabels[id]}
          </label>
        ))}
      </fieldset>
      <div className="grid gap-3">
        <h3>區塊順序與寬度</h3>
        {view.widgets.map((w, i) => (
          <div key={w.id} className="rounded-lg border border-border p-3">
            <div className="mb-2 flex items-center justify-between">
              <span>{widgetLabels[w.id]}</span>
              <div className="flex gap-1">
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`${widgetLabels[w.id]}上移`}
                  disabledReason={i === 0 ? "已在最上方" : null}
                  onClick={() =>
                    onChange(reorderWidgets(view, w.id, view.widgets[i - 1].id))
                  }
                >
                  <ArrowUp />
                </Button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`${widgetLabels[w.id]}下移`}
                  disabledReason={i === view.widgets.length - 1 ? "已在最下方" : null}
                  onClick={() =>
                    onChange(reorderWidgets(view, w.id, view.widgets[i + 1].id))
                  }
                >
                  <ArrowDown />
                </Button>
              </div>
            </div>
            <select
              aria-label={`${widgetLabels[w.id]}寬度`}
              value={w.width}
              onChange={(e) =>
                onChange({
                  ...view,
                  widgets: view.widgets.map((item) =>
                    item.id === w.id
                      ? { ...item, width: e.target.value as typeof w.width }
                      : item,
                  ),
                })
              }
            >
              <option value="narrow">窄版 · 1/3</option>
              <option value="half">半版 · 1/2</option>
              <option value="wide">寬版 · 2/3</option>
              <option value="full">全寬</option>
            </select>
          </div>
        ))}
      </div>
      <p className="rounded-lg bg-muted p-3 text-xs text-muted-foreground">
        粉絲成長、Reels 與貼文觀看數將在串接品牌經營資料後加入。
      </p>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={onReset}>
          <RotateCcw />
          重設此檢視
        </Button>
        {canDelete && (
          <Button
            variant="ghost"
            className="text-destructive"
            onClick={onDelete}
          >
            刪除此檢視
          </Button>
        )}
        <Button className="ml-auto" onClick={onClose}>
          完成
        </Button>
      </div>
    </SidePanel>
  );
}
