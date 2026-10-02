import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { ActiveJobsBell } from "./ActiveJobsBell";
import { OrgMenu } from "@/components/auth";
import { useWorkspace } from "./WorkspaceContext";
import { Button } from "./ui/button";
import { cn } from "@/lib/utils";
import { getStatusSummary, type AdsStatusSummary } from "@/lib/adsStatusApi";

type SyncState = { status: "loading" } | { status: "error" } | { status: "ready"; summary: AdsStatusSummary };

/** F27（feature Decisions「queue auto refresh daily」）：不用輪詢，換頁重打一次就夠——投放
 * 中心本來就是每天一次的節奏，不需要即時性。`M/D HH:MM` 跟全站其餘日期格式一樣不補零日期、
 * 補零時分（`ads/home/status.ts::formatRevisitLabel` 先例），瀏覽器本地時區。 */
function formatSyncedAt(iso: string): string {
  const d = new Date(iso);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${hh}:${mm}`;
}

/** F27-I20（feature Decisions「Screens → Top bar」，contract I `status-summary`）：品牌路由才
 * 顯示，原型 `.top` 那顆按鈕（灰點＋「最近同步 …」＋警示晶片，連去讀取設定頁）。這支不從
 * `components/ads/patterns` 拿零件——layout 是共用零件櫃，只准 `@/lib/*`，零件在這裡用同一套
 * tone 手刻（跟 `patterns/Chip.tsx` 同一份 token，不是另一套視覺語言）。一次讀失敗就整塊不
 * 畫，殼層本身絕不現錯誤字；換頁（`location.pathname` 變）就重打一次。 */
function SyncStatus({ brandId }: { brandId: string }) {
  const location = useLocation();
  const [state, setState] = useState<SyncState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    getStatusSummary(brandId, controller.signal)
      .then((summary) => setState({ status: "ready", summary }))
      .catch(() => setState({ status: "error" }));
    return () => controller.abort();
  }, [brandId, location.pathname]);

  if (state.status !== "ready") return null;
  const { summary } = state;
  const failing = summary.failing_campaigns > 0;
  const syncedText = summary.last_success_at ? `最近同步 ${formatSyncedAt(summary.last_success_at)}` : "尚未同步";
  const fullText = `${syncedText}${failing ? `・${summary.failing_campaigns} 個活動讀取異常` : ""}`;

  // Merge smoke red (1024, ADR 0051 rule 4): the right group has to shrink, not this link — so
  // this can only give up its OWN width first. `min-w-0` (no `shrink-0`) lets the flex algorithm
  // actually shrink it; below `xl` (1280, same cutover `tokens.css` already uses for the sidebar)
  // the sync text folds away and only the dot + the open-items chip remain, `title` keeping the
  // full sentence reachable (hover / screen reader) instead of silently dropping it.
  return (
    <Link
      to={`/brands/${brandId}/ads/connections`}
      title={fullText}
      className="flex min-w-0 items-center gap-2 rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
    >
      <span
        aria-hidden="true"
        className={cn("inline-block h-2 w-2 shrink-0 rounded-full", failing ? "bg-warning" : "bg-success")}
      />
      <span className="hidden max-w-[220px] truncate whitespace-nowrap xl:inline">{fullText}</span>
      {summary.open_items > 0 && (
        <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-warning/10 px-2.5 py-1 text-xs text-warning">
          {summary.open_items} 項待處理
        </span>
      )}
    </Link>
  );
}

const LABELS: Record<string, string> = {
  library: "品牌智庫",
  products: "商品",
  ads: "投放中心",
  workbench: "素材工作檯",
  orders: "訂單與顧客",
  report: "顧問分析報告",
  intake: "品牌建檔",
  settings: "設定",
  inbox: "收件匣",
};
export function Topbar({
  brandId,
  collapsed,
  onToggleSidebar,
}: {
  brandId: string | null;
  collapsed: boolean;
  onToggleSidebar: () => void;
}) {
  const queryClient = useQueryClient();
  const { brands, identity } = useWorkspace();
  const { pathname } = useLocation();
  const parts = pathname.split("/").filter(Boolean);
  const brand = brands.find((b) => b.brand_id === brandId);
  const label = brandId
    ? (LABELS[parts[2]] ?? "經營概況")
    : (LABELS[parts[0]] ?? "品牌總覽");
  return (
    <header className="app-topbar max-md:gap-2 max-md:px-3!">
      <div className="flex min-w-0 items-center gap-3 max-md:gap-1.5">
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={collapsed ? "展開側欄" : "收合側欄"}
          onClick={onToggleSidebar}
        >
          {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
        </Button>
        <nav
          aria-label="目前位置"
          className="flex min-w-0 items-center gap-2 text-sm"
        >
          {brand && (
            <>
              <Link
                className="max-w-48 truncate text-muted-foreground max-md:hidden"
                to={`/brands/${brand.brand_id}`}
              >
                {brand.brand_name}
              </Link>
              <span className="text-border max-md:hidden">/</span>
            </>
          )}
          <span className="truncate font-medium">{label}</span>
        </nav>
      </div>
      <div className="flex min-w-0 items-center gap-3 max-md:gap-1.5">
        {brandId && <SyncStatus brandId={brandId} />}
        <ActiveJobsBell />
        {/* OrgMenu (components/auth, out of this issue's touch) prints the org name uncapped —
         * for a first-login personal org that's literally the sign-up email (`app/identity/
         * __init__.py`), which can be far longer than any real org name. This wrapper is the only
         * lever this file has on it: `min-w-0` lets it take the shrink instead of forcing the row
         * wider, `overflow-hidden` contains whatever doesn't fit instead of letting it push
         * `#root`'s scrollWidth past the viewport (the merge-smoke gate). */}
        {/* Below md the org menu lives in the sidebar drawer instead (F47-I02). */}
        <div className="min-w-0 overflow-hidden max-md:hidden">
          <OrgMenu
            identity={identity}
            onIdentityChanged={() => {
              void queryClient.invalidateQueries({ queryKey: ["identity"] });
            }}
          />
        </div>
      </div>
    </header>
  );
}
