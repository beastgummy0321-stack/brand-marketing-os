import { useEffect, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  BarChart3,
  BookOpen,
  CalendarDays,
  ChevronDown,
  Check,
  FileChartColumn,
  Inbox,
  LayoutGrid,
  Package,
  Plus,
  Settings,
  Users,
  Wand2,
} from "lucide-react";
import { useWorkspace } from "./WorkspaceContext";
import { Logo } from "./Logo";
import { brandDestination } from "./brandNavigation";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { cn } from "@/lib/utils";

const BRAND_NAV = [
  { label: "經營概況", suffix: "", icon: BarChart3 },
  { label: "投放中心", suffix: "/ads", icon: CalendarDays },
  { label: "素材工作檯", suffix: "/workbench", icon: Wand2 },
  { label: "訂單與顧客", suffix: "/orders", icon: Users },
  { label: "商品", suffix: "/products", icon: Package },
  { label: "品牌智庫", suffix: "/library", icon: BookOpen },
  { label: "顧問分析報告", suffix: "/report", icon: FileChartColumn },
];
export function Sidebar({
  brandId,
  collapsed,
  overlayOpen = false,
}: {
  brandId: string | null;
  collapsed: boolean;
  /** Below `md` (F47-I02): the sidebar is hidden unless the top-bar control opened it as an overlay.
   * `tokens.css` `.app-sidebar` is unlayered CSS, so the narrow-only overrides are `!` utilities. */
  overlayOpen?: boolean;
}) {
  const { brands, scope, identity, brandsLoading, brandsError, refreshBrands } =
    useWorkspace();
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  const [lastBrand, setLastBrand] = useState<string | null>(() => {
    try {
      return localStorage.getItem(`brand-os:last-brand:${scope}`);
    } catch {
      return null;
    }
  });
  const selectedId =
    brandId ??
    (brands.some((b) => b.brand_id === lastBrand) ? lastBrand : null);
  const selected = brands.find((b) => b.brand_id === selectedId);
  useEffect(() => {
    if (brandId && brands.some((b) => b.brand_id === brandId)) {
      setLastBrand(brandId);
      try {
        localStorage.setItem(`brand-os:last-brand:${scope}`, brandId);
      } catch {
        /* navigation still works */
      }
    }
  }, [brandId, brands, scope]);
  function switchBrand(id: string) {
    navigate(brandDestination(id, pathname, search));
  }
  function nav(
    to: string,
    label: string,
    Icon: typeof LayoutGrid,
    end = false,
  ) {
    return (
      <NavLink
        key={to}
        to={to}
        end={end}
        className="nav-item"
        title={collapsed ? label : undefined}
      >
        <Icon aria-hidden="true" />
        {!collapsed && <span>{label}</span>}
      </NavLink>
    );
  }
  return (
    <aside
      className={cn(
        "app-sidebar",
        collapsed && "is-collapsed",
        overlayOpen
          ? "max-md:fixed! max-md:inset-y-0 max-md:left-0 max-md:z-40 max-md:shadow-xl"
          : "max-md:hidden!",
      )}
    >
      <Link to="/" className="mb-6 px-1" aria-label="行銷駕駛艙首頁">
        <Logo compact={collapsed} />
      </Link>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            aria-label="切換品牌"
            className={cn(
              "flex min-w-0 items-center gap-2.5 rounded-lg border border-border p-3 text-left hover:bg-muted",
              collapsed && "justify-center p-2",
            )}
          >
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-semibold text-white">
              {selected?.brand_name.slice(0, 2).toUpperCase() || "B"}
            </span>
            {!collapsed && (
              <>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">
                    {selected?.brand_name ??
                      (brandsLoading ? "載入品牌…" : "選擇品牌")}
                  </span>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    目前品牌
                  </span>
                </span>
                <ChevronDown size={14} />
              </>
            )}
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="right" align="start" className="w-72">
          <DropdownMenuLabel>切換品牌</DropdownMenuLabel>
          {brands.map((b) => (
            <DropdownMenuItem
              key={b.brand_id}
              onSelect={() => switchBrand(b.brand_id)}
              className="justify-between"
            >
              <span className="truncate">{b.brand_name}</span>
              {selectedId === b.brand_id && <Check size={14} />}
            </DropdownMenuItem>
          ))}
          {brandsError && (
            <DropdownMenuItem onSelect={refreshBrands}>
              載入失敗，重新載入
            </DropdownMenuItem>
          )}
          {!brands.length && !brandsLoading && !brandsError && (
            <p className="px-2 py-3 text-xs text-muted-foreground">
              尚未建立品牌
            </p>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => navigate("/intake/new")}>
            <Plus size={15} />
            新增品牌
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <nav aria-label="主導覽" className="min-h-0 flex-1 overflow-y-auto pb-4">
        {!collapsed && <p className="nav-group-label">工作區</p>}
        <div className={cn("space-y-1", collapsed && "mt-5")}>
          {nav("/", "品牌總覽", LayoutGrid, true)}
          {nav("/inbox", "收件匣", Inbox)}
        </div>
        {selected && (
          <>
            {!collapsed && <p className="nav-group-label">品牌經營</p>}
            <div className={cn("space-y-1", collapsed && "mt-4")}>
              {BRAND_NAV.slice(0, 4).map((n) =>
                nav(
                  `/brands/${selected.brand_id}${n.suffix}`,
                  n.label,
                  n.icon,
                  !n.suffix,
                ),
              )}
            </div>
            {!collapsed && <p className="nav-group-label">品牌資料</p>}
            <div className={cn("space-y-1", collapsed && "mt-4")}>
              {BRAND_NAV.slice(4).map((n) =>
                nav(`/brands/${selected.brand_id}${n.suffix}`, n.label, n.icon),
              )}
            </div>
          </>
        )}
      </nav>
      {nav("/settings", "設定", Settings)}
      <div className="mt-3 flex items-center gap-2.5 border-t border-border px-2 pt-4">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-semibold text-primary">
          {identity.user.email.slice(0, 2).toUpperCase()}
        </span>
        {!collapsed && (
          <span className="min-w-0">
            <span className="block truncate text-xs font-medium">
              {identity.org.name}
            </span>
            <span className="block truncate text-[11px] text-muted-foreground">
              {identity.user.email}
            </span>
          </span>
        )}
      </div>
    </aside>
  );
}
