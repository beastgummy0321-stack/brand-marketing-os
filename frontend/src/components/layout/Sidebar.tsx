import { NAV_TOP, NAV_MODULES, NAV_FOOTER } from "@/config/navigation";
import { NavGroup } from "./NavGroup";

export function Sidebar() {
  return (
    <nav
      aria-label="主導覽"
      className="flex w-[var(--width-sidebar)] shrink-0 flex-col justify-between border-r border-border bg-card p-4"
    >
      <div className="flex flex-col gap-6">
        <NavGroup items={NAV_TOP} />
        <div>
          <p className="px-3 pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            模組
          </p>
          <NavGroup items={NAV_MODULES} />
        </div>
      </div>
      <NavGroup items={NAV_FOOTER} />
    </nav>
  );
}
