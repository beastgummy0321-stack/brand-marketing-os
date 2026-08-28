import { ActiveJobsBell } from "./ActiveJobsBell";
import { Link } from "react-router-dom";
import { OrgMenu } from "@/components/auth/OrgMenu";

export function Topbar() {
  return (
    <header className="flex h-[var(--height-topbar)] shrink-0 items-center justify-between border-b border-border bg-card px-6">
      <span className="font-display text-lg font-medium text-foreground">行銷駕駛艙</span>
      <div className="flex items-center gap-4">
        <OrgMenu />
        <ActiveJobsBell />
        <Link
          to="/"
          className="text-sm font-medium text-primary underline-offset-4 hover:underline"
        >
          回到舊版介面
        </Link>
      </div>
    </header>
  );
}
