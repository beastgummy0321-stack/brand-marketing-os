import { useQueryClient } from "@tanstack/react-query";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Link, useLocation } from "react-router-dom";
import { ActiveJobsBell } from "./ActiveJobsBell";
import { OrgMenu } from "@/components/auth";
import { useWorkspace } from "./WorkspaceContext";
import { Button } from "./ui/button";

const LABELS: Record<string, string> = {
  library: "品牌智庫",
  products: "產品",
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
    <header className="app-topbar">
      <div className="flex min-w-0 items-center gap-3">
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
                className="max-w-48 truncate text-muted-foreground"
                to={`/brands/${brand.brand_id}`}
              >
                {brand.brand_name}
              </Link>
              <span className="text-border">/</span>
            </>
          )}
          <span className="truncate font-medium">{label}</span>
        </nav>
      </div>
      <div className="flex shrink-0 items-center gap-3">
        <ActiveJobsBell />
        <OrgMenu
          identity={identity}
          onIdentityChanged={() => {
            void queryClient.invalidateQueries({ queryKey: ["identity"] });
          }}
        />
      </div>
    </header>
  );
}
